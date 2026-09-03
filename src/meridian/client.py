"""Model client: structured extraction, response caching, cost and latency.

Every call is cached under a key built from the model, prompt version, schema,
a fixed temperature tag, run index and the image bytes, so a hit is the response
to that exact request. Both the extractor and the harness recompute the key on
read. Replay mode never falls back to the network.
"""
from __future__ import annotations

import functools
import hashlib
import json
import os
import time
from typing import Dict, Optional, Tuple

from meridian.schema import FIELD_ORDER, response_schema
from meridian.settings import (CACHE, CONFIG, DOCS, MAX_INTERVAL_S, MIN_INTERVAL_S,
                               PROMPT_VERSION, RATE_LIMIT_ATTEMPTS)

PROMPT = """You are extracting fields from a document submitted to Meridian Claims Group for payment processing.

Return exactly the six fields in the schema. For each field give the value and your confidence that the value is exactly correct.

Rules:
- Transcribe values exactly as printed on the document. Do not reformat, round, or correct them.
- If the document genuinely does not contain a field, return null for that value. Never infer a field from context, and never compute one by arithmetic from other numbers on the page.
- If the document is not a claims document at all, return null for every field rather than mapping unrelated values onto them.
- Confidence must be honest and use the full 0.0-1.0 range. A value you read from a clear, unambiguous label deserves high confidence; a value that is smudged, handwritten, or one of several plausible candidates deserves low confidence. Do not default to high confidence.

You must also reconcile the document. Transcribe every priced line item, sum those amounts, and report whether that sum equals the stated total. A claim whose itemisation does not add up to its total must not be paid without review, so this verdict matters as much as the total itself. Report reconciles as false if they differ by any amount at all, however small. If the document has no itemisation or no stated total, return null.

A wrong value costs Meridian far more than a flagged one. When genuinely unsure, say so in the confidence rather than guessing."""


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()[:16]


def load_pricing() -> dict:
    with open(os.path.join(CONFIG, "pricing.json")) as fh:
        return json.load(fh)


def cost_usd(model: str, usage: dict, pricing: Optional[dict] = None) -> float:
    """Dollar cost of one call from token counts.

    Thinking tokens bill at the output rate, so they are added to output tokens
    before pricing.
    """
    p = (pricing or load_pricing())["models"][model]
    out = usage.get("output_tokens", 0) + usage.get("thinking_tokens", 0)
    return (usage.get("input_tokens", 0) / 1e6) * p["input_per_mtok"] + \
           (out / 1e6) * p["output_per_mtok"]


def cache_key(model: str, doc_id: str, run: int, image_sha: str, schema_sha: str) -> str:
    # "t0" stands in for the temperature (always 0.0). Kept as a literal because
    # changing the key format would invalidate the committed cache.
    raw = "|".join([model, PROMPT_VERSION, doc_id, str(run), image_sha, schema_sha, "t0"])
    return hashlib.sha256(raw.encode()).hexdigest()[:20]


def schema_sha() -> str:
    """Hash of the response schema as sent; part of every cache key."""
    return _sha(json.dumps(response_schema(), sort_keys=True).encode())


@functools.lru_cache(maxsize=None)
def file_sha(path: str) -> str:
    with open(path, "rb") as fh:
        return _sha(fh.read())


def record_is_fresh(rec: dict, model: str, doc_id: str, run: int,
                    image_sha: str, schema: str) -> bool:
    """Was this cached record produced for exactly this request?

    The key is recomputed from the current image bytes, schema and prompt
    version. Without the check, regenerating the corpus would score new
    documents against old responses, which does not crash and gives plausible
    wrong numbers. The extractor treats a mismatch as a miss; the harness
    refuses to score it.
    """
    return rec.get("cache_key") == cache_key(model, doc_id, run, image_sha, schema)


def cache_path(model: str, split: str, run: int, doc_id: str) -> str:
    return os.path.join(CACHE, model, "%s-run%d" % (split, run), doc_id + ".json")


class Client:
    def __init__(self, replay: bool = False):
        self.replay = replay
        self._interval = MIN_INTERVAL_S
        self._last_call = 0.0
        self.pricing = load_pricing()
        self._schema = response_schema()
        self._schema_sha = schema_sha()
        self._genai = None
        self._images: Dict[str, Tuple[bytes, str]] = {}

    @property
    def schema_sha(self) -> str:
        """Hash of the response schema; part of every cache key."""
        return self._schema_sha

    @property
    def genai(self):
        """The SDK client. Built lazily so replay mode needs no API key."""
        return self._client()

    def _client(self):
        if self._genai is None:
            key = os.environ.get("GEMINI_API_KEY")
            if not key:
                raise RuntimeError(
                    "GEMINI_API_KEY is not set. Copy .env.example to .env and fill "
                    "it in. Scoring the committed cache with meridian-evaluate needs no key.")
            from google import genai
            self._genai = genai.Client(api_key=key)
        return self._genai

    def call(self, model: str, png: bytes):
        """One structured-output request. Returns (response, usage, latency_s).

        The only place the request is built. extract() adds caching and pacing
        on top; throughput.py adds a shared rate gate. Latency is the service time
        of this attempt with no sleeps included.
        """
        from google.genai import types
        started = time.time()
        resp = self.genai.models.generate_content(
            model=model,
            contents=[types.Part.from_bytes(data=png, mime_type="image/jpeg"), PROMPT],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=self._schema,
                temperature=0.0),
        )
        u = resp.usage_metadata
        usage = {
            "input_tokens": u.prompt_token_count or 0,
            "output_tokens": u.candidates_token_count or 0,
            "thinking_tokens": getattr(u, "thoughts_token_count", None) or 0,
            "cached_tokens": getattr(u, "cached_content_token_count", None) or 0,
        }
        return resp, usage, round(time.time() - started, 3)

    def image(self, doc_id: str) -> Tuple[bytes, str]:
        if doc_id not in self._images:
            with open(os.path.join(DOCS, doc_id + ".jpg"), "rb") as fh:
                data = fh.read()
            self._images[doc_id] = (data, _sha(data))
        return self._images[doc_id]

    def extract(self, model: str, doc_id: str, split: str, run: int) -> dict:
        """One extraction, served from cache when the stored key matches.

        A file at the cache path is not enough on its own. The stored cache_key
        is compared with one recomputed from the current image bytes, prompt and
        schema, so regenerating the corpus cannot serve old responses for new
        documents.
        """
        path = cache_path(model, split, run, doc_id)
        png, image_sha = self.image(doc_id)
        expected = cache_key(model, doc_id, run, image_sha, self._schema_sha)

        if os.path.exists(path):
            with open(path) as fh:
                cached = json.load(fh)
            if cached.get("cache_key") == expected:
                # A recorded failure gets one more attempt in live mode. cache_hit
                # is for the caller's bookkeeping and is not written to disk.
                if not (cached.get("error") and not self.replay):
                    cached["cache_hit"] = True
                    return cached
            if self.replay:
                raise RuntimeError(
                    "Replay mode: stale cache for %s / %s run %d.\n"
                    "  cached key   %s\n  expected key %s\n"
                    "The document, prompt or schema changed since this response was "
                    "recorded. Refusing to score a new input against an old output."
                    % (model, doc_id, run, cached.get("cache_key"), expected))
            # Live mode: the request changed, so fetch it again.

        if self.replay:
            raise RuntimeError(
                "Replay mode: no cached response for %s / %s / %s run %d.\n"
                "Replay never calls the API. Run the live extract command to "
                "populate the cache." % (model, split, doc_id, run))

        record = {
            "cache_key": expected,
            "doc_id": doc_id, "model": model, "split": split, "run": run,
            "request": {"prompt_version": PROMPT_VERSION, "temperature": 0.0,
                        "image_sha": image_sha, "schema_sha": self._schema_sha},
        }
        for attempt in range(RATE_LIMIT_ATTEMPTS):
            self._pace()
            started = time.time()
            try:
                # Latency covers the successful attempt only; back-off sleeps
                # are not model latency.
                resp, usage, record["latency_s"] = self.call(model, png)
                usage.pop("cached_tokens", None)      # keep the record shape stable
                record["usage"] = usage
                record["response"] = self._parse(resp.text)
                # An unparseable body is a failed call, not a claim that every
                # field is absent. Scored as such: excluded by name.
                record["error"] = (None if record["response"] is not None
                                   else "unparseable response: %r" % (resp.text or "")[:200])
                record["attempts"] = attempt + 1
                break
            except Exception as exc:                      # noqa: BLE001
                msg = str(exc)
                if ("429" in msg or "503" in msg) and attempt < RATE_LIMIT_ATTEMPTS - 1:
                    self._interval = min(self._interval * 1.6 + 1.0, MAX_INTERVAL_S)
                    time.sleep(self._interval)
                    continue
                # A failed call is recorded rather than raised. scorable_docs()
                # then excludes the document by name before anything is scored.
                record["latency_s"] = round(time.time() - started, 3)
                record["usage"] = {"input_tokens": 0, "output_tokens": 0, "thinking_tokens": 0}
                record["response"] = None
                record["error"] = "%s: %s" % (type(exc).__name__, str(exc)[:300])
                record["attempts"] = attempt + 1
                break

        record["cost_usd"] = round(cost_usd(model, record["usage"], self.pricing), 8)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            json.dump(record, fh, indent=2, sort_keys=True)
            fh.write("\n")
        record["cache_hit"] = False
        return record

    def _pace(self) -> None:
        wait = self._interval - (time.time() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.time()

    @staticmethod
    def _parse(text: Optional[str]) -> Optional[dict]:
        """Parse structured output defensively. Malformed pieces become None or 0."""
        if not text:
            return None
        try:
            data = json.loads(text)
        except (ValueError, TypeError):
            return None
        if not isinstance(data, dict):
            return None
        out = {}
        for f in FIELD_ORDER:
            cell = data.get(f) or {}
            if not isinstance(cell, dict):
                cell = {}
            conf = cell.get("confidence")
            try:
                conf = float(conf)
            except (TypeError, ValueError):
                conf = 0.0
            out[f] = {"value": cell.get("value"), "confidence": max(0.0, min(1.0, conf))}

        items = data.get("line_items")
        out["line_items"] = [
            {"description": str(li.get("description", "")), "amount": li.get("amount")}
            for li in items if isinstance(li, dict)
        ] if isinstance(items, list) else []

        try:
            rconf = float(data.get("reconciliation_confidence"))
        except (TypeError, ValueError):
            rconf = 0.0
        out["reconciliation"] = {
            # The model's own sum and verdict, kept apart from line_items so the
            # harness can recompute both independently.
            "line_items_sum": data.get("line_items_sum"),
            "reconciles": data.get("reconciles"),
            "confidence": max(0.0, min(1.0, rconf)),
        }
        return out
