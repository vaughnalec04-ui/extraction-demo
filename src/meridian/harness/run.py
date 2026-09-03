"""Evaluation harness.

Scores cached responses and never calls the API. Extraction and scoring are
separate so a threshold sweep is free and a demo is deterministic.

  meridian-evaluate --split tune --tune-thresholds
  meridian-evaluate --split test

Thresholds are swept on the tune split only. The chosen values are written to
config/thresholds.json and read back for the test run, so no test score comes
from a threshold that saw test data.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
from typing import Dict, List, Optional, Sequence

from meridian.harness import metrics
from meridian.harness.configs import CONFIGS, resolve
from meridian.schema import FIELD_ORDER, PAYMENT_CRITICAL
from meridian.client import file_sha, record_is_fresh, schema_sha
from meridian.settings import (
    BOOTSTRAP_RESAMPLES,
    BOOTSTRAP_SEED,
    CACHE,
    CONFIG,
    DATA,
    DOCS,
    DOC_EXT,
    MERIDIAN_BAR,
    MONTHLY_VOLUME,
    PRIMARY,
    RESULTS,
    VERIFIER)


def load_labels() -> Dict[str, dict]:
    with open(os.path.join(DATA, "labels.jsonl")) as fh:
        return {r["doc_id"]: r for r in (json.loads(l) for l in fh)}


def load_split(split: str) -> List[str]:
    with open(os.path.join(DATA, "splits.json")) as fh:
        return json.load(fh)[split]


def load_cache(model: str, split: str, run: int, doc_ids: Sequence[str]) -> Dict[str, dict]:
    """Cached records for these documents, each checked against the current
    image bytes, schema and prompt version. A stale record is refused, not
    scored: the harness never calls the API, so it cannot repair one."""
    out = {}
    schema = schema_sha()
    for d in doc_ids:
        p = os.path.join(CACHE, model, "%s-run%d" % (split, run), d + ".json")
        if not os.path.exists(p):
            raise SystemExit(
                "Missing cached response: %s\nRun extraction for this split/run "
                "first, or check out a commit whose cache matches this corpus." % p)
        with open(p) as fh:
            rec = json.load(fh)
        image = file_sha(os.path.join(DOCS, d + DOC_EXT))
        if not record_is_fresh(rec, model, d, run, image, schema):
            raise SystemExit(
                "Stale cached response: %s\nIt was produced for a different image, "
                "schema or prompt version than the one on disk. Regenerated corpus? "
                "Re-run extraction, or check out the commit whose corpus matches "
                "this cache. Refusing to score it." % p)
        out[d] = rec
    return out


def available_runs(split: str) -> int:
    """Highest run index for which every reader has a cache directory."""
    n = 0
    while True:
        nxt = n + 1
        if all(os.path.isdir(os.path.join(CACHE, m, "%s-run%d" % (split, nxt)))
               for m in (PRIMARY, VERIFIER)):
            n = nxt
        else:
            return n


def scorable_docs(split: str, runs: int) -> Dict[str, object]:
    """Documents every reader and run covers, plus the ones dropped.

    Quota can leave a document uncovered for one reader. Scoring the union
    would compare configurations over different document sets, so the
    intersection is scored and every exclusion is recorded by name.
    """
    all_ids = load_split(split)
    covered = set(all_ids)
    for model in (PRIMARY, VERIFIER):
        for run in range(1, runs + 1):
            d = os.path.join(CACHE, model, "%s-run%d" % (split, run))
            present = {f[:-5] for f in os.listdir(d)} if os.path.isdir(d) else set()
            usable = set()
            for doc in present:
                with open(os.path.join(d, doc + ".json")) as fh:
                    rec = json.load(fh)
                # A failed call or an unparseable body is not a set of answers.
                if not rec.get("error") and rec.get("response") is not None:
                    usable.add(doc)
            covered &= usable
    excluded = [d for d in all_ids if d not in covered]
    return {"scored": [d for d in all_ids if d in covered],
            "excluded": excluded,
            "n_total": len(all_ids), "n_scored": len(covered)}


def score(config: str, split: str, run: int, tau_abstain: float,
          tau_escalate: float, labels: Dict[str, dict],
          doc_ids: Optional[Sequence[str]] = None) -> dict:
    """Score one configuration over one split at one run index."""
    doc_ids = list(doc_ids) if doc_ids is not None else load_split(split)
    primary = load_cache(PRIMARY, split, run, doc_ids)
    verifier = ({d: None for d in doc_ids} if config == "primary_solo"
                else load_cache(VERIFIER, split, run, doc_ids))

    instances, confidences, strata, fields = [], [], [], []
    costs, latencies, escalations, call_errors = [], [], 0, 0
    recon_rows = []

    for d in doc_ids:
        resolved, usage = resolve(config, primary[d], verifier.get(d),
                                  tau_abstain, tau_escalate)
        costs.append(usage["cost_usd"])
        latencies.append(usage["latency_s"])
        call_errors += len(usage["errors"])
        escalated = resolved.pop("_escalated", False)
        if escalated:
            escalations += 1
        lab = labels[d]

        # Reconciliation is scored from the reader that supplied the emitted
        # values, so one model's arithmetic is not credited to another's
        # extraction.
        if config == "verifier_solo":
            src_rec = verifier.get(d)
        elif config == "cascade" and escalated:
            src_rec = verifier.get(d)
        else:
            src_rec = primary[d]
        row = metrics.score_reconciliation(lab, (src_rec or {}).get("response"))
        if config == "double_key" and resolved["total_amount"]["abstained"] and row.get("applicable"):
            # The readers disagreed on the total, so the field went to review.
            # The verdict on that total goes with it rather than being scored
            # from one reader's value.
            row["applicable"] = False
            row["routed_to_review"] = True
        recon_rows.append(row)

        for f in FIELD_ORDER:
            cell = resolved[f]
            inst = metrics.classify(f, lab["fields"][f], cell["value"], cell["abstained"])
            inst["doc_id"] = d
            instances.append(inst)
            confidences.append(cell["confidence"])
            strata.append(lab["stratum"])
            fields.append(f)

    overall = metrics.summarize(instances)
    pay_idx = [i for i, f in enumerate(fields) if f == PAYMENT_CRITICAL]

    return {
        "config": config, "split": split, "run": run,
        "thresholds": {"tau_abstain": tau_abstain, "tau_escalate": tau_escalate},
        "n_documents": len(doc_ids),
        "overall": overall,
        "by_field": metrics.by_key(instances, fields),
        "by_stratum": metrics.by_key(instances, strata),
        "payment_critical": metrics.summarize([instances[i] for i in pay_idx]),
        "calibration": metrics.calibration(instances, confidences),
        "reconciliation": metrics.summarize_reconciliation(recon_rows),
        "cost": {
            "mean_usd_per_doc": round(statistics.mean(costs), 8),
            "total_usd": round(sum(costs), 6),
            "monthly_usd_at_40k_docs": round(statistics.mean(costs) * MONTHLY_VOLUME, 2),
        },
        "latency": {
            "p50_s": round(_pct(latencies, 50), 3),
            "p95_s": round(_pct(latencies, 95), 3),
            "mean_s": round(statistics.mean(latencies), 3),
            "_note": "serial wall-clock as measured; double_key's two calls "
                     "are independent and could run concurrently (not measured)",
        },
        "escalation_rate": round(escalations / len(doc_ids), 6) if config == "cascade" else None,
        "escalation": metrics.wilson(escalations, len(doc_ids)) if config == "cascade" else None,
        "api_call_errors": call_errors,
        # Consumed by evaluate() for the paired comparison; not written out.
        "_instances": instances,
    }


def _pct(values: Sequence[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * (p / 100.0)
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


# --- threshold tuning (tune split only) -----------------------------------

def sweep_grid(labels: Dict[str, dict], split: str = "tune") -> List[float]:
    """Candidate thresholds drawn from the confidences observed on tune.

    A fixed 0.0..1.0 grid would put most of its points where no prediction
    lands. Using observed values means every candidate separates something.
    """
    seen = set()
    for model in (PRIMARY, VERIFIER):
        for d in load_split(split):
            p = os.path.join(CACHE, model, "%s-run1" % split, d + ".json")
            if not os.path.exists(p):
                continue
            with open(p) as fh:
                rec = json.load(fh)
            for f in FIELD_ORDER:
                cell = (rec.get("response") or {}).get(f) or {}
                try:
                    seen.add(round(float(cell.get("confidence", 0.0)), 4))
                except (TypeError, ValueError):
                    pass
    grid = sorted(seen | {0.0})
    # A threshold has to sit just above an observed confidence to exclude it.
    return sorted({0.0} | {round(v + 1e-4, 6) for v in grid})


def tune(labels: Dict[str, dict]) -> dict:
    """Choose thresholds on the tune split.

    Objective: maximise coverage subject to normalized accuracy on covered
    items clearing Meridian's 97% bar. Automate as much as possible without
    dropping below the bar on what is automated. If no threshold clears the
    bar, that is reported rather than relaxed.
    """
    grid = sweep_grid(labels)
    chosen, sweeps = {}, {}
    # Same intersection rule as the test path so both splits use one policy.
    tune_docs = scorable_docs("tune", 1)["scored"]

    for config in CONFIGS:
        rows = []
        candidates = grid if config != "double_key" else [0.0]
        for tau_a in candidates:
            esc_grid = grid if config == "cascade" else [0.0]
            for tau_e in esc_grid:
                r = score(config, "tune", 1, tau_a, tau_e, labels, tune_docs)
                rows.append({
                    "tau_abstain": tau_a, "tau_escalate": tau_e,
                    "coverage": r["overall"]["coverage"]["point"],
                    "accuracy_on_covered": r["overall"]["normalized_match_on_covered"]["point"],
                    "abstention_precision": r["overall"]["abstention_precision"]["point"],
                    "cost_per_doc": r["cost"]["mean_usd_per_doc"],
                    "escalation_rate": r["escalation_rate"],
                })
        feasible = [x for x in rows
                    if x["accuracy_on_covered"] is not None
                    and x["accuracy_on_covered"] >= MERIDIAN_BAR
                    and x["coverage"] > 0]
        if feasible:
            best = max(feasible, key=lambda x: (x["coverage"], -x["cost_per_doc"]))
            met = True
        else:
            best = max(rows, key=lambda x: (x["accuracy_on_covered"] or 0, x["coverage"]))
            met = False
        chosen[config] = {"tau_abstain": best["tau_abstain"],
                          "tau_escalate": best["tau_escalate"],
                          "bar_met_on_tune": met,
                          "tune_coverage": best["coverage"],
                          "tune_accuracy_on_covered": best["accuracy_on_covered"]}
        sweeps[config] = rows
    return {"chosen": chosen, "sweeps": sweeps, "grid_size": len(grid),
            "objective": "maximise coverage subject to normalized accuracy on "
                         "covered >= %.2f" % MERIDIAN_BAR,
            "tuned_on": "tune split, run 1, never test"}


def evaluate(labels: Dict[str, dict], split: str, runs: int, thresholds: dict,
             doc_ids: Optional[Sequence[str]] = None) -> dict:
    """Score every configuration across `runs` repeats and report the spread."""
    per_config, first_run = {}, {}
    for config in CONFIGS:
        t = thresholds["chosen"][config]
        run_results = [score(config, split, r, t["tau_abstain"], t["tau_escalate"],
                             labels, doc_ids)
                       for r in range(1, runs + 1)]
        first_run[config] = run_results[0].pop("_instances")
        for r in run_results[1:]:
            r.pop("_instances", None)
        per_config[config] = {
            "runs": run_results,
            "variance": _variance(run_results),
            "thresholds_from_tune": t,
        }
    # Every configuration was scored on the same documents, so the difference
    # from the primary reader alone is a paired quantity. Run 1 only.
    base = first_run["primary_solo"]
    for config in CONFIGS:
        per_config[config]["paired_vs_primary_solo"] = (
            None if config == "primary_solo"
            else metrics.paired_difference(first_run[config], base,
                                           BOOTSTRAP_RESAMPLES, BOOTSTRAP_SEED))
    return per_config


def _variance(run_results: List[dict]) -> dict:
    """Run-to-run spread on the headline figures. Expected to be zero at
    temperature 0; a non-zero spread is a finding."""
    def pull(path):
        vals = []
        for r in run_results:
            node = r
            for k in path:
                node = node[k]
            if node is not None:
                vals.append(node)
        return vals

    out = {}
    for name, path in [
        ("normalized_match_on_covered", ("overall", "normalized_match_on_covered", "point")),
        ("coverage", ("overall", "coverage", "point")),
        ("abstention_precision", ("overall", "abstention_precision", "point")),
        ("payment_critical_accuracy", ("payment_critical", "normalized_match_on_covered", "point")),
        ("ece", ("calibration", "ece")),
        ("recon_model_verdict_accuracy", ("reconciliation", "model_verdict", "accuracy", "point")),
        ("recon_code_verdict_accuracy", ("reconciliation", "code_verdict", "accuracy", "point")),
        ("cost_per_doc", ("cost", "mean_usd_per_doc")),
        ("p50_latency_s", ("latency", "p50_s")),
    ]:
        vals = pull(path)
        out[name] = {
            "runs": vals,
            "min": min(vals) if vals else None,
            "max": max(vals) if vals else None,
            "median": round(statistics.median(vals), 6) if vals else None,
            "spread": round(max(vals) - min(vals), 6) if vals else None,
        }
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Score cached responses.")
    ap.add_argument("--split", default="test", choices=["tune", "test"])
    ap.add_argument("--runs", type=int, default=3,
                    help="repeats to score; reduced to what the cache holds")
    ap.add_argument("--tune-thresholds", action="store_true",
                    help="sweep thresholds on the tune split and write them out")
    ap.add_argument("--out", default=os.path.join(RESULTS, "results.json"))
    args = ap.parse_args()

    labels = load_labels()
    tpath = os.path.join(CONFIG, "thresholds.json")

    if args.tune_thresholds:
        tuned = tune(labels)
        os.makedirs(os.path.dirname(tpath), exist_ok=True)
        with open(tpath, "w") as fh:
            json.dump(tuned, fh, indent=2, sort_keys=True)
            fh.write("\n")
        print("thresholds written to %s" % tpath)
        for c, v in sorted(tuned["chosen"].items()):
            print("  %-12s tau_abstain=%-8s tau_escalate=%-8s bar_met_on_tune=%s"
                  % (c, v["tau_abstain"], v["tau_escalate"], v["bar_met_on_tune"]))
        return

    if not os.path.exists(tpath):
        raise SystemExit("No tuned thresholds. Run with --tune-thresholds first.")
    with open(tpath) as fh:
        thresholds = json.load(fh)

    # Score the runs the cache holds. Asking for 3 when 1 is cached is a
    # normal thing to do from the README; score 1 and say so.
    available = available_runs(args.split)
    if available < args.runs:
        print("NOTE: %d run(s) requested but only %d cached for every reader on "
              "the %s split; scoring %d." % (args.runs, available, args.split, available))
        args.runs = available
    if args.runs == 0:
        raise SystemExit("No complete cached run for the %s split. Run the extract "
                         "command first." % args.split)

    cov = scorable_docs(args.split, args.runs)
    if not cov["scored"]:
        raise SystemExit("Every document is missing from at least one reader's cache "
                         "for the %s split. Nothing can be scored." % args.split)
    if cov["excluded"]:
        print("NOTE: %d of %d documents excluded (not covered by every reader "
              "and run): %s" % (len(cov["excluded"]), cov["n_total"],
                                ", ".join(cov["excluded"])))
    results = {
        "meta": {
            "models": {"primary": PRIMARY, "verifier": VERIFIER},
            "split_scored": args.split,
            "runs": args.runs,
            "documents_scored": cov["n_scored"],
            "documents_excluded": cov["excluded"],
            "exclusion_reason": ("not covered by every reader and run"
                                 if cov["excluded"] else None),
            "meridian_bar": MERIDIAN_BAR,
            "thresholds_tuned_on": thresholds["tuned_on"],
            "tuning_objective": thresholds["objective"],
        },
        "thresholds": thresholds["chosen"],
        "coverage": cov,
        "configs": evaluate(labels, args.split, args.runs, thresholds, cov["scored"]),
        "frontier": None,
    }
    results["frontier"] = _frontier(results["configs"])

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as fh:
        json.dump(results, fh, indent=2, sort_keys=True)
        fh.write("\n")

    from meridian.harness.report import render
    render(results)
    print("\nmachine-readable results: %s" % args.out)


def _frontier(per_config: dict) -> List[dict]:
    """One point per configuration, ready to plot from the JSON.

    Run 1 throughout, so every point and its interval describe the same run.
    Run-to-run spread is under each configuration's variance block.
    """
    pts = []
    for config, block in sorted(per_config.items()):
        first = block["runs"][0]
        pts.append({
            "config": config,
            "run": first["run"],
            "cost_per_doc": first["cost"]["mean_usd_per_doc"],
            "monthly_usd_at_40k_docs": first["cost"]["monthly_usd_at_40k_docs"],
            "accuracy_on_covered": first["overall"]["normalized_match_on_covered"]["point"],
            "accuracy_ci": first["overall"]["normalized_match_on_covered"],
            "coverage": first["overall"]["coverage"]["point"],
            "abstention_precision": first["overall"]["abstention_precision"]["point"],
            "payment_critical_accuracy": first["payment_critical"]["normalized_match_on_covered"]["point"],
            "ece": first["calibration"]["ece"],
            "p50_latency_s": first["latency"]["p50_s"],
            "recon_bad_claim_recall": first["reconciliation"].get("bad_claim_recall_model", {}).get("point"),
            "recon_model_verdict_accuracy": first["reconciliation"].get("model_verdict", {}).get("accuracy", {}).get("point"),
            "recon_code_verdict_accuracy": first["reconciliation"].get("code_verdict", {}).get("accuracy", {}).get("point"),
            "recon_false_pass_model": first["reconciliation"].get("model_verdict", {}).get("false_pass"),
            "recon_false_pass_code": first["reconciliation"].get("code_verdict", {}).get("false_pass"),
        })
    return pts


if __name__ == "__main__":
    main()
