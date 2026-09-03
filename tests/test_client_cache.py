"""The cache-freshness guard.

Regenerating the corpus and scoring new documents against old responses would
not crash and would produce plausible wrong numbers. The key is recomputed
from the image bytes on every read and replay refuses a mismatch.

Replay is exercised with GEMINI_API_KEY unset, which also shows that scoring
the committed cache needs no key.
"""
import json
import os

import pytest

from meridian import client as client_mod


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    cache, docs = tmp_path / "cache", tmp_path / "docs"
    docs.mkdir()
    monkeypatch.setattr(client_mod, "CACHE", str(cache))
    monkeypatch.setattr(client_mod, "DOCS", str(docs))
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    return docs


def _write_cache(model, doc_id, key, **extra):
    p = client_mod.cache_path(model, "test", 1, doc_id)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as fh:
        json.dump({"cache_key": key, "response": {}, "error": None, **extra}, fh)
    return p


def test_fresh_cache_is_a_hit_and_needs_no_key(sandbox):
    (sandbox / "d1.jpg").write_bytes(b"document version one")
    c = client_mod.Client(replay=True)
    _, sha = c.image("d1")
    _write_cache("m", "d1", client_mod.cache_key("m", "d1", 1, sha, c.schema_sha))
    rec = c.extract("m", "d1", "test", 1)
    assert rec["cache_hit"] is True


def test_replay_refuses_stale_entry(sandbox):
    (sandbox / "d1.jpg").write_bytes(b"document version one")
    c = client_mod.Client(replay=True)
    _, sha = c.image("d1")
    _write_cache("m", "d1", client_mod.cache_key("m", "d1", 1, sha, c.schema_sha))

    (sandbox / "d1.jpg").write_bytes(b"document version two")   # corpus regenerated
    with pytest.raises(RuntimeError, match="stale"):
        client_mod.Client(replay=True).extract("m", "d1", "test", 1)


def test_replay_refuses_missing_entry(sandbox):
    (sandbox / "d1.jpg").write_bytes(b"document")
    with pytest.raises(RuntimeError, match="no cached response"):
        client_mod.Client(replay=True).extract("m", "d1", "test", 1)


def test_cache_key_covers_every_input():
    base = client_mod.cache_key("m", "d1", 1, "img-a", "schema-a")
    assert base != client_mod.cache_key("m2", "d1", 1, "img-a", "schema-a")   # model
    assert base != client_mod.cache_key("m", "d2", 1, "img-a", "schema-a")    # document
    assert base != client_mod.cache_key("m", "d1", 2, "img-a", "schema-a")    # run index
    assert base != client_mod.cache_key("m", "d1", 1, "img-b", "schema-a")    # image bytes
    assert base != client_mod.cache_key("m", "d1", 1, "img-a", "schema-b")    # schema
    assert base == client_mod.cache_key("m", "d1", 1, "img-a", "schema-a")    # deterministic


def test_live_client_requires_key(sandbox):
    (sandbox / "d1.jpg").write_bytes(b"document")
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        client_mod.Client(replay=False).genai


def test_cost_bills_thinking_tokens_at_the_output_rate():
    pricing = {"models": {"m": {"input_per_mtok": 1.0, "output_per_mtok": 10.0}}}
    no_think = client_mod.cost_usd("m", {"input_tokens": 1_000_000, "output_tokens": 100_000,
                                         "thinking_tokens": 0}, pricing)
    with_think = client_mod.cost_usd("m", {"input_tokens": 1_000_000, "output_tokens": 100_000,
                                           "thinking_tokens": 100_000}, pricing)
    assert no_think == pytest.approx(1.0 + 1.0)
    assert with_think == pytest.approx(1.0 + 2.0)


def test_parse_tolerates_malformed_model_output():
    parse = client_mod.Client._parse
    assert parse(None) is None
    assert parse("not json") is None
    assert parse("[]") is None
    out = parse(json.dumps({"total_amount": {"value": "1.00", "confidence": "high"},
                            "line_items": "nope", "reconciliation_confidence": None}))
    assert out["total_amount"]["confidence"] == 0.0          # unparseable -> 0
    assert out["line_items"] == []
    assert out["reconciliation"]["confidence"] == 0.0
    out = parse(json.dumps({"claim_id": {"value": "x", "confidence": 7}}))
    assert out["claim_id"]["confidence"] == 1.0              # clamped


def test_prompt_text_is_pinned_to_its_version():
    """The cache key carries PROMPT_VERSION, not the prompt text, so an edit
    to PROMPT without a version bump would serve stale responses. This pins
    the text. When PROMPT changes, bump PROMPT_VERSION and update the hash."""
    from meridian.client import PROMPT, _sha
    from meridian.settings import PROMPT_VERSION
    assert PROMPT_VERSION == "v2-reconciliation"
    assert _sha(PROMPT.encode())[:16] == "bb1b5dd56c14a3e2"


def test_record_is_fresh_rejects_a_different_image_schema_or_run():
    from meridian.client import cache_key, record_is_fresh
    rec = {"cache_key": cache_key("m", "doc", 1, "img", "sch")}
    assert record_is_fresh(rec, "m", "doc", 1, "img", "sch")
    assert not record_is_fresh(rec, "m", "doc", 1, "other-img", "sch")
    assert not record_is_fresh(rec, "m", "doc", 1, "img", "other-schema")
    assert not record_is_fresh(rec, "m", "doc", 2, "img", "sch")
    assert not record_is_fresh({}, "m", "doc", 1, "img", "sch")


def test_transient_errors_are_recognised_by_status_code_then_by_message():
    from meridian.client import is_transient

    class ApiError(Exception):
        def __init__(self, code, msg):
            super().__init__(msg)
            self.code = code

    assert is_transient(ApiError(429, "RESOURCE_EXHAUSTED"))
    assert is_transient(ApiError(503, "UNAVAILABLE"))
    assert not is_transient(ApiError(400, "INVALID_ARGUMENT mentioning 429 in the text"))
    assert not is_transient(ApiError(500, "internal"))
    assert is_transient(Exception("503 UNAVAILABLE: high demand"))        # no code attribute
    assert not is_transient(Exception("Connection reset"))
