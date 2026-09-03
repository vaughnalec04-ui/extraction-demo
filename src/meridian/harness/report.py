"""This module renders a results block in the terminal.

Everything printed here also exists in results.json; the JSON is the
artifact. Nothing is computed in this module. Every number on screen has a
field in the JSON; the scoring lives in metrics.py and run.py.
"""
from __future__ import annotations

from typing import Optional


def _ci(block: Optional[dict], pct: bool = True) -> str:
    if not block or block.get("point") is None:
        return "     n/a"
    s = 100.0 if pct else 1.0
    suffix = "%" if pct else ""
    return "%6.2f%s [%.1f-%.1f]" % (block["point"] * s, suffix,
                                    block["low"] * s, block["high"] * s)


def _rule(char: str = "-", width: int = 96) -> str:
    return char * width


def render(results: dict) -> None:
    meta = results["meta"]
    _header(meta)
    _frontier(results["frontier"], meta)
    _paired(results["configs"])
    for config, block in sorted(results["configs"].items()):
        _config(config, block)


# These functions render the top of the report.

def _header(meta: dict) -> None:
    print()
    print(_rule("="))
    print("MERIDIAN CLAIMS: EXTRACTION EVALUATION")
    print(_rule("="))
    print("split scored      : %s  (%d runs)" % (meta["split_scored"], meta["runs"]))
    print("readers           : primary=%s  verifier=%s"
          % (meta["models"]["primary"], meta["models"]["verifier"]))
    print("thresholds        : %s" % meta["thresholds_tuned_on"])
    print("objective         : %s" % meta["tuning_objective"])
    print("Meridian bar      : %.0f%% field-level accuracy" % (meta["meridian_bar"] * 100))


def _frontier(frontier: list, meta: dict) -> None:
    print()
    print(_rule("="))
    print("COST / ACCURACY FRONTIER   (run 1; run-to-run spread under each configuration)")
    print(_rule("="))
    print("%-13s %-22s %-10s %-10s %-11s %-9s %-7s %s"
          % ("config", "accuracy on covered", "coverage", "bad-claim", "abst.prec", "$/doc", "ECE", "p50"))
    print("%-13s %-22s %-10s %-10s" % ("", "", "", "recall"))
    print(_rule())
    for p in frontier:
        bar = "OK " if (p["accuracy_on_covered"] or 0) >= meta["meridian_bar"] else "-- "
        bcr = p.get("recon_bad_claim_recall")
        print("%-13s %s %s %-10s %-11s $%-8.5f %-7s %.2fs  %s"
              % (p["config"], _ci(p["accuracy_ci"]),
                 "%7.1f%%  " % ((p["coverage"] or 0) * 100),
                 ("%6.1f%%" % (bcr * 100)) if bcr is not None else "   n/a",
                 ("%6.1f%%" % (p["abstention_precision"] * 100))
                 if p["abstention_precision"] is not None else "   n/a",
                 p["cost_per_doc"],
                 "%.4f" % p["ece"] if p["ece"] is not None else "n/a",
                 p["p50_latency_s"], bar))
    print(_rule())
    print("abst.prec = of the field-instances flagged, the share that would "
          "have been wrong.")
    print("n/a means nothing was flagged, so the precision is 0/0 and undefined.")


# These functions render one configuration.

def _config(config: str, block: dict) -> None:
    first, var = block["runs"][0], block["variance"]
    _config_banner(config, block, first)
    _overall(first)
    _reconciliation(first.get("reconciliation") or {})
    _slices(first)
    _calibration(first["calibration"])
    _cost_and_latency(first)
    _variance(block["runs"], var)


def _config_banner(config: str, block: dict, first: dict) -> None:
    print()
    print(_rule("="))
    print("CONFIG: %s" % config.upper())
    print(_rule("="))
    t = block["thresholds_from_tune"]
    print("thresholds (from tune): abstain<%s  escalate<%s   bar met on tune: %s"
          % (t["tau_abstain"], t["tau_escalate"], t["bar_met_on_tune"]))
    if first.get("escalation_rate") is not None:
        esc = first.get("escalation") or {}
        band = " [%.1f–%.1f]" % (esc["low"] * 100, esc["high"] * 100) if esc else ""
        print("escalation rate       : %.1f%% of documents%s" % (first["escalation_rate"] * 100, band))
    if first.get("api_call_errors"):
        print("API call errors       : %d in scored documents (empty cells, scored as missed fields)"
              % first["api_call_errors"])


def _overall(first: dict) -> None:
    o = first["overall"]
    print()
    print("  exact match (covered)      %s" % _ci(o["exact_match_on_covered"]))
    print("  normalized match (covered) %s" % _ci(o["normalized_match_on_covered"]))
    print("  normalized match (all)     %s" % _ci(o["normalized_match_on_all"]))
    print("  coverage                   %s" % _ci(o["coverage"]))
    print("  abstention rate            %s" % _ci(o["abstention_rate"]))
    print("  abstention precision       %s" % _ci(o["abstention_precision"]))
    print("  abstention recall          %s" % _ci(o["abstention_recall"]))
    print("  PAYMENT-CRITICAL (total_amount)")
    print("      normalized match       %s"
          % _ci(first["payment_critical"]["normalized_match_on_covered"]))

    print()
    print("  error taxonomy (reported separately; the costs differ):")
    for kind, n in o["errors"].items():
        print("      %-22s %d" % (kind, n))
    print("      %-22s %d" % ("would-be-wrong total", o["would_be_wrong_total"]))


def _reconciliation(rc: dict) -> None:
    if not rc.get("n"):
        return
    mv, cv = rc["model_verdict"], rc["code_verdict"]
    print()
    print("  RECONCILIATION  (do the line items sum to the stated total?)"
          "   n=%d docs, %d inconsistent" % (rc["n"], rc["n_inconsistent_claims"]))
    print("      %-30s %-24s %s" % ("", "model does the sum", "python sums model's items"))
    print("      %-30s %-24s %s" % ("verdict accuracy",
                                    _ci(mv["accuracy"]), _ci(cv["accuracy"])))
    print("      %-30s %-24s %s" % ("bad-claim recall",
                                    _ci(rc["bad_claim_recall_model"]),
                                    _ci(rc["bad_claim_recall_code"])))
    print("      %-30s %-24s %s" % ("false pass  (wrong payout)",
                                    "%d" % mv["false_pass"], "%d" % cv["false_pass"]))
    print("      %-30s %-24s %s" % ("false flag  (review cost)",
                                    "%d" % mv["false_flag"], "%d" % cv["false_flag"]))
    print("      %-30s %s" % ("model arithmetic correct",
                              _ci(rc["model_arithmetic_accuracy"])))
    print("      %-30s %s" % ("line items read correctly",
                              _ci(rc["line_item_sum_accuracy"])))
    same = (mv["false_pass"] == cv["false_pass"] and mv["false_flag"] == cv["false_flag"])
    if same and rc["model_arithmetic_accuracy"]["point"] == 1.0:
        print("      -> both verdict paths fail on the same documents and the arithmetic")
        print("         is correct, so the errors are misread digits")


def _slices(first: dict) -> None:
    print()
    print("  per-field:")
    print("      %-18s %-22s %-22s %s" % ("field", "exact", "normalized", "coverage"))
    for field, blk in first["by_field"].items():
        print("      %-18s %s %s %s"
              % (field, _ci(blk["exact_match_on_covered"]),
                 _ci(blk["normalized_match_on_covered"]), _ci(blk["coverage"])))

    print()
    print("  per-stratum (normalized, on covered):")
    for stratum, blk in first["by_stratum"].items():
        print("      %-18s %s   errors=%d"
              % (stratum, _ci(blk["normalized_match_on_covered"]),
                 sum(blk["errors"].values())))


def _calibration(cal: dict) -> None:
    print()
    print("  calibration   ECE=%.4f   informative buckets=%d of %d occupied%s"
          % (cal["ece"], cal["informative_buckets"], cal["occupied_buckets"],
             "   *** DEGENERATE: not a curve ***" if cal["degenerate"] else ""))
    print("      %-12s %6s %12s %12s %8s" % ("bucket", "n", "mean conf", "observed", "gap"))
    for b in cal["buckets"]:
        if not b["n"]:
            continue
        print("      %-12s %6d %12.4f %12.4f %8.4f"
              % (b["bucket"], b["n"], b["mean_confidence"],
                 b["observed_accuracy"], b["gap"]))


def _cost_and_latency(first: dict) -> None:
    print()
    print("  cost:    $%.5f/doc   -> $%.2f/month at 40,000 docs"
          % (first["cost"]["mean_usd_per_doc"], first["cost"]["monthly_usd_at_40k_docs"]))
    print("  latency: p50 %.2fs   p95 %.2fs" % (first["latency"]["p50_s"],
                                                first["latency"]["p95_s"]))


def _variance(runs: list, var: dict) -> None:
    print()
    print("  run-to-run spread across %d runs (temperature 0):" % len(runs))
    for name, v in var.items():
        if v["spread"] is None:
            continue
        flag = "" if v["spread"] == 0 else "   <- non-zero at temp 0"
        print("      %-28s min=%-10s max=%-10s spread=%s%s"
              % (name, v["min"], v["max"], v["spread"], flag))


def _paired(per_config: dict) -> None:
    rows = [(c, b["paired_vs_primary_solo"]) for c, b in per_config.items()
            if b.get("paired_vs_primary_solo")]
    if not rows:
        return
    print("\nPaired against primary_solo, run 1. Same documents; bootstrap resamples documents.")
    print("  %-14s %-30s %-12s %-8s %s" % (
        "config", "wrong emissions (cand vs base)", "discordant", "exact p", "coverage change"))
    for c, p in rows:
        w, cv = p["wrong_emissions"], p["coverage"]
        print("  %-14s %-30s %-12s %-8s %s" % (
            c,
            "%d vs %d   [%+.1f, %+.1f] pts" % (w["candidate"], w["baseline"],
                                                100 * w["difference_ci"]["low"],
                                                100 * w["difference_ci"]["high"]),
            "%d / %d" % (w["candidate_only"], w["baseline_only"]),
            "%.2f" % w["exact_p"],
            "%+.1f pts [%+.1f, %+.1f]" % (100 * cv["difference_point"],
                                          100 * cv["difference_ci"]["low"],
                                          100 * cv["difference_ci"]["high"])))
