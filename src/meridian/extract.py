"""This program populates the response cache for a split.

Extraction and scoring are separate programs. This one fetches and caches raw
model responses. Thresholds, escalation and the cascade are all computed later
by the harness from the cached confidences, so a threshold sweep costs no API
calls and tuning is reproducible.

Example usage is shown below.
  meridian-extract --split tune --model gemini-3.5-flash-lite
  meridian-extract --split test --all-models --runs 3
"""
from __future__ import annotations

import argparse
import json
import os

from meridian.client import Client
from meridian.settings import DATA, PRIMARY, VERIFIER


def load_split(split: str):
    with open(os.path.join(DATA, "splits.json")) as fh:
        return json.load(fh)[split]


def run(models, split: str, runs: int) -> None:
    client = Client()
    doc_ids = load_split(split)
    for model in models:
        for run_idx in range(1, runs + 1):
            done = errs = hits = 0
            for doc_id in doc_ids:
                # Client.extract owns the freshness check and reports cache_hit.
                rec = client.extract(model, doc_id, split, run_idx)
                done += 1
                hits += 1 if rec.get("cache_hit") else 0
                errs += 1 if rec.get("error") else 0
                if not rec.get("cache_hit") and done % 10 == 0:
                    print("    %s run%d: %d/%d" % (model, run_idx, done, len(doc_ids)))
            print("  %-24s %s run%d: %d docs (%d cached, %d errors)"
                  % (model, split, run_idx, done, hits, errs))


def main() -> None:
    ap = argparse.ArgumentParser(description="Populate the response cache.")
    ap.add_argument("--split", default="tune", choices=["tune", "test"])
    ap.add_argument("--model", default=PRIMARY)
    ap.add_argument("--all-models", action="store_true", help="run both readers")
    ap.add_argument("--runs", type=int, default=1,
                    help="repeat count; each run is cached separately for variance")
    args = ap.parse_args()
    models = [PRIMARY, VERIFIER] if args.all_models else [args.model]
    print("extracting: split=%s models=%s runs=%d" % (args.split, models, args.runs))
    run(models, args.split, args.runs)


if __name__ == "__main__":
    main()
