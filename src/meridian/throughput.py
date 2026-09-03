"""Concurrent interactive execution and the throughput sweep.

Meridian processes about 40,000 documents a month, so throughput decides
whether the pipeline is deployable. The sustainable request rate is not in the
docs (FRICTION F-009) and a 429 does not say what the limit is (F-008), so
`sweep` finds where throughput stops scaling and errors start.

Run:  meridian-throughput --split test --levels 1,2,4,8,16
"""
from __future__ import annotations

import argparse
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional, Sequence

from meridian.client import Client, cost_usd, load_pricing
from meridian.settings import (DATA, MONTHLY_VOLUME, PRIMARY, RESULTS)


class RateGate:
    """Shared token bucket across workers.

    Per-worker back-off does not work here. N workers backing off on their own
    still put N times the load on one quota and thrash against it together.
    The gate holds the global rate; a 429 on any worker slows all of them.
    """

    def __init__(self, interval_s: float = 0.0, max_interval_s: float = 20.0):
        self._interval = interval_s
        self._max = max_interval_s
        self._next_free = 0.0
        self._lock = threading.Lock()
        self.throttle_events = 0

    def acquire(self) -> None:
        with self._lock:
            now = time.monotonic()
            start = max(now, self._next_free)
            self._next_free = start + self._interval
        wait = start - time.monotonic()
        if wait > 0:
            time.sleep(wait)

    def penalise(self) -> None:
        """Called on a 429/503 by any worker. Slows the whole pool."""
        with self._lock:
            self.throttle_events += 1
            self._interval = min(max(self._interval * 1.5, 0.5) + 0.25, self._max)

    def relax(self) -> None:
        """Called on sustained success. Recovers toward full speed."""
        with self._lock:
            if self._interval > 0:
                self._interval = max(0.0, self._interval * 0.93)

    @property
    def interval(self) -> float:
        return self._interval


def _one_call(client: Client, model: str, doc_id: str, gate: RateGate) -> dict:
    """A single extraction through the gate. Returns a timing record.

    The request is Client.call(), the same one the cached extractor uses, so
    throughput is measured on the production request.
    """
    image_bytes, _ = client.image(doc_id)
    attempts = 0
    started_total = time.monotonic()

    while attempts < 6:
        attempts += 1
        gate.acquire()
        t0 = time.monotonic()
        try:
            _, usage, service_s = client.call(model, image_bytes)
            gate.relax()
            # usage includes cached_tokens, which shows whether implicit caching
            # (on by default) hit any of the input.
            return {"doc_id": doc_id, "ok": True, "attempts": attempts,
                    "service_s": service_s,
                    "total_s": time.monotonic() - started_total, **usage}
        except Exception as exc:                                   # noqa: BLE001
            msg = str(exc)
            if "429" in msg or "503" in msg:
                gate.penalise()
                continue
            return {"doc_id": doc_id, "ok": False, "attempts": attempts,
                    "service_s": time.monotonic() - t0,
                    "total_s": time.monotonic() - started_total,
                    "error": "%s: %s" % (type(exc).__name__, msg[:160])}
    return {"doc_id": doc_id, "ok": False, "attempts": attempts,
            "total_s": time.monotonic() - started_total, "error": "429: gave up after 6 attempts"}


def run_concurrent(model: str, doc_ids: Sequence[str], workers: int,
                   gate: Optional[RateGate] = None) -> dict:
    """Run one pass at a fixed worker count and report measured throughput."""
    client = Client()
    client.genai                           # construct before timing starts
    for d in doc_ids:                      # warm the image cache off the clock
        client.image(d)

    gate = gate or RateGate()
    records: List[dict] = []
    wall_start = time.monotonic()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_one_call, client, model, d, gate) for d in doc_ids]
        for f in as_completed(futures):
            records.append(f.result())
    wall = time.monotonic() - wall_start

    ok = [r for r in records if r["ok"]]
    pricing = load_pricing()
    cost = sum(cost_usd(model, r, pricing) for r in ok)
    lat = sorted(r["service_s"] for r in ok) or [0.0]

    return {
        "model": model, "workers": workers, "n_documents": len(doc_ids),
        "wall_clock_s": round(wall, 2),
        "succeeded": len(ok), "failed": len(records) - len(ok),
        "throughput_docs_per_min": round(len(ok) / wall * 60, 1) if wall else 0.0,
        "throughput_docs_per_hour": round(len(ok) / wall * 3600, 0) if wall else 0.0,
        "hours_for_monthly_volume": round(MONTHLY_VOLUME / (len(ok) / wall * 3600), 2)
                                    if wall and ok else None,
        "service_latency_p50_s": round(lat[len(lat) // 2], 3),
        "service_latency_p95_s": round(lat[min(int(len(lat) * 0.95), len(lat) - 1)], 3),
        "throttle_events": gate.throttle_events,
        "final_gate_interval_s": round(gate.interval, 3),
        "retried_calls": sum(1 for r in records if r.get("attempts", 1) > 1),
        "cost_usd_total": round(cost, 6),
        "cost_usd_per_doc": round(cost / len(ok), 8) if ok else None,
        "cached_tokens_total": sum(r.get("cached_tokens", 0) for r in ok),
    }


def sweep(model: str, doc_ids: Sequence[str], levels: Sequence[int]) -> List[dict]:
    """Find the knee: where does adding workers stop adding throughput."""
    out = []
    for w in levels:
        print("  concurrency=%-3d ..." % w, end="", flush=True)
        # Fresh gate per level so back-off from one level does not carry into
        # the next measurement.
        r = run_concurrent(model, doc_ids, w, RateGate())
        out.append(r)
        print(" %6.1f docs/min  ok=%d fail=%d throttles=%d  p50=%.2fs"
              % (r["throughput_docs_per_min"], r["succeeded"], r["failed"],
                 r["throttle_events"], r["service_latency_p50_s"]))
        time.sleep(5)                      # let any burst quota recover
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Measure throughput across worker counts.")
    ap.add_argument("--model", default=PRIMARY)
    ap.add_argument("--split", default="test", choices=["tune", "test"])
    ap.add_argument("--levels", default="1,2,4,8,16")
    args = ap.parse_args()

    with open(os.path.join(DATA, "splits.json")) as fh:
        doc_ids = json.load(fh)[args.split]
    levels = [int(x) for x in args.levels.split(",")]
    print("concurrency sweep: model=%s split=%s n=%d" % (args.model, args.split, len(doc_ids)))
    rows = sweep(args.model, doc_ids, levels)
    out = os.path.join(RESULTS, "throughput.json")
    os.makedirs(RESULTS, exist_ok=True)
    with open(out, "w") as fh:
        json.dump({"monthly_volume": MONTHLY_VOLUME, "model": args.model,
                   "split": args.split, "sweep": rows}, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print("\nwritten to %s" % out)


if __name__ == "__main__":
    main()
