"""Batch API submission and polling.

Batch suits the overnight bulk: 50% of the interactive rate with a 24h target
turnaround. On this key every batches.create returned 400 FAILED_PRECONDITION
(FRICTION F-011), so this path is implemented against the SDK contract and
unverified.

Run:  meridian-batch --mode submit --split test
      meridian-batch --mode poll
"""
from __future__ import annotations

import argparse
import json
import os
import time
from typing import Sequence

from meridian.client import PROMPT, Client, cost_usd
from meridian.schema import response_schema
from meridian.settings import (DATA, PRIMARY, RESULTS)


BATCH_STATE_FILE = os.path.join(RESULTS, "batch_job.json")


def submit_batch(model: str, doc_ids: Sequence[str], display_name: str = "meridian-extract") -> dict:
    """Submit the corpus as one batch job.

    Batch suits the overnight bulk: 50% of the interactive rate with a 24h
    target turnaround. The same-day queue still needs the interactive path, so
    both are measured.
    """
    client = Client()
    schema = response_schema()
    requests = []
    for d in doc_ids:
        image_bytes, _ = client.image(d)
        requests.append({
            "contents": [{"parts": [
                {"inline_data": {"mime_type": "image/jpeg", "data": image_bytes}},
                {"text": PROMPT},
            ]}],
            "config": {
                "response_mime_type": "application/json",
                "response_schema": schema,
                "temperature": 0.0,
            },
        })

    t0 = time.monotonic()
    job = client.genai.batches.create(
        model=model, src=requests, config={"display_name": display_name})
    state = {
        "job_name": job.name, "model": model, "n_documents": len(doc_ids),
        "display_name": display_name,
        "submitted_state": str(job.state),
        "submit_seconds": round(time.monotonic() - t0, 2),
        "doc_ids": list(doc_ids),
    }
    os.makedirs(os.path.dirname(BATCH_STATE_FILE), exist_ok=True)
    with open(BATCH_STATE_FILE, "w") as fh:
        json.dump(state, fh, indent=2, sort_keys=True)
        fh.write("\n")
    return state


def poll_batch(budget_s: float = 600.0, interval_s: float = 20.0) -> dict:
    """Poll a submitted job for a bounded time and record the state it reaches.

    The documented target is 24h. "Submitted, not finished within the window"
    is a recordable result; waiting a day inside a demo is not.
    """
    with open(BATCH_STATE_FILE) as fh:
        state = json.load(fh)
    client = Client().genai
    t0 = time.monotonic()
    last = None
    while time.monotonic() - t0 < budget_s:
        job = client.batches.get(name=state["job_name"])
        last = str(job.state)
        if "SUCCEEDED" in last or "FAILED" in last or "CANCELLED" in last:
            break
        time.sleep(interval_s)

    state["final_state"] = last
    state["waited_s"] = round(time.monotonic() - t0, 1)
    state["completed_within_budget"] = bool(last and "SUCCEEDED" in last)

    if state["completed_within_budget"]:
        job = client.batches.get(name=state["job_name"])
        parsed, usage_in, usage_out, usage_think = [], 0, 0, 0
        responses = getattr(job.dest, "inlined_responses", None) or []
        for doc_id, item in zip(state["doc_ids"], responses):
            resp = getattr(item, "response", None)
            text = getattr(resp, "text", None) if resp else None
            u = getattr(resp, "usage_metadata", None) if resp else None
            if u:
                usage_in += u.prompt_token_count or 0
                usage_out += u.candidates_token_count or 0
                usage_think += getattr(u, "thoughts_token_count", None) or 0
            parsed.append({"doc_id": doc_id, "text": text,
                           "error": str(getattr(item, "error", "")) or None})
        interactive = cost_usd(state["model"], {
            "input_tokens": usage_in, "output_tokens": usage_out,
            "thinking_tokens": usage_think})
        state["usage"] = {"input_tokens": usage_in, "output_tokens": usage_out,
                          "thinking_tokens": usage_think}
        state["cost_usd_interactive_equivalent"] = round(interactive, 6)
        state["cost_usd_batch"] = round(interactive * 0.5, 6)   # published 50% rate
        state["cost_usd_per_doc_batch"] = round(interactive * 0.5 / len(parsed), 8) if parsed else None
        state["n_responses"] = len(parsed)
        state["n_errors"] = sum(1 for p in parsed if p["error"])
        with open(os.path.join(RESULTS, "batch_responses.json"), "w") as fh:
            json.dump(parsed, fh, indent=2, sort_keys=True)
            fh.write("\n")

    with open(BATCH_STATE_FILE, "w") as fh:
        json.dump(state, fh, indent=2, sort_keys=True)
        fh.write("\n")
    return state


def main() -> None:
    ap = argparse.ArgumentParser(description="Submit or poll a batch job.")
    ap.add_argument("--mode", required=True, choices=["submit", "poll"])
    ap.add_argument("--model", default=PRIMARY)
    ap.add_argument("--split", default="test", choices=["tune", "test"])
    ap.add_argument("--budget", type=float, default=600.0)
    args = ap.parse_args()

    if args.mode == "submit":
        with open(os.path.join(DATA, "splits.json")) as fh:
            doc_ids = json.load(fh)[args.split]
        s = submit_batch(args.model, doc_ids)
        print("submitted %s  state=%s  n=%d  (%.1fs)"
              % (s["job_name"], s["submitted_state"], s["n_documents"], s["submit_seconds"]))
    else:
        s = poll_batch(budget_s=args.budget)
        print("job %s -> %s after %.0fs (completed_in_budget=%s)"
              % (s["job_name"], s["final_state"], s["waited_s"], s["completed_within_budget"]))
        if s.get("cost_usd_per_doc_batch"):
            print("batch cost/doc $%.8f vs interactive $%.8f"
                  % (s["cost_usd_per_doc_batch"],
                     s["cost_usd_interactive_equivalent"] / s["n_responses"]))


if __name__ == "__main__":
    main()
