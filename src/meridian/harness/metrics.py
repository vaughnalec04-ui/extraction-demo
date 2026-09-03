"""This module holds the scoring primitives.

Three definitions matter most.

* A field-instance is one (document, field) pair. Rates are over
  field-instances because Meridian pays per field.
* "Abstained" means the system routed the field to the exception queue. It is
  not the same as the model answering null, which is a claim that the field is
  absent and can itself be right or wrong.
* Accuracy is always reported next to coverage. A system that abstains on
  everything has 100% accuracy on covered items.
"""
from __future__ import annotations

import math
import random
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Optional, Sequence

from meridian.schema import normalize
from meridian.settings import MIN_BUCKET_N

# These are the outcome labels for a scored field-instance.
CORRECT = "correct"                       # A value was emitted and it matches.
CORRECT_REJECT = "correct_rejection"      # The model said absent, and it is absent.
WRONG_VALUE = "wrong_value"               # The emitted value differs from the gt value.
MISSED_FIELD = "missed_field"             # The model said absent, but gt has a value.
HALLUCINATED = "hallucinated_field"       # The model emitted a value; gt has none.
ABSTAINED = "abstained"                   # The field was routed to the exception queue.

# The three error kinds carry different business costs and are reported apart.
ERROR_KINDS = (WRONG_VALUE, MISSED_FIELD, HALLUCINATED)


def wilson(successes: int, n: int, z: float = 1.959963985) -> Dict[str, float]:
    """This computes the Wilson score interval for a binomial proportion.

    It is used over the normal approximation because these proportions sit near
    1.0 at n=40 to 240, where the normal approximation gives intervals above 1.0.
    """
    if n == 0:
        return {"point": None, "low": None, "high": None, "n": 0}
    p = successes / n
    denom = 1.0 + (z * z) / n
    centre = p + (z * z) / (2 * n)
    margin = z * math.sqrt((p * (1 - p) + (z * z) / (4 * n)) / n)
    return {"point": round(p, 6),
            "low": round(max(0.0, (centre - margin) / denom), 6),
            "high": round(min(1.0, (centre + margin) / denom), 6),
            "n": n}


def classify(field: str, gt_raw: Optional[str], pred_raw: Optional[str],
             abstained: bool) -> Dict[str, object]:
    """This scores one field-instance.

    `would_be_*` records the outcome had the system not abstained. Abstention
    precision needs it: you have to know whether the suppressed value was going
    to be wrong.
    """
    gt_n, pred_n = normalize(field, gt_raw), normalize(field, pred_raw)
    exact = (gt_raw or "") == (pred_raw or "")

    if gt_n is None and pred_n is None:
        outcome, correct = CORRECT_REJECT, True
    elif gt_n is None:
        outcome, correct = HALLUCINATED, False
    elif pred_n is None:
        outcome, correct = MISSED_FIELD, False
    elif gt_n == pred_n:
        outcome, correct = CORRECT, True
    else:
        outcome, correct = WRONG_VALUE, False

    return {
        "field": field,
        "outcome": ABSTAINED if abstained else outcome,
        "abstained": abstained,
        "would_be_outcome": outcome,
        "would_be_correct": correct,
        "exact_match": bool(exact and correct),
        "normalized_match": correct,
        "gt": gt_raw, "pred": pred_raw,
    }


def summarize(instances: Sequence[dict]) -> Dict[str, object]:
    """This aggregates scored field-instances.

    Order follows the questions as they get asked: how much did it process
    (coverage), how right was it on that (accuracy_on_covered), what did it get
    wrong and how (error kinds), and was it right to flag what it flagged
    (abstention precision and recall).
    """
    n = len(instances)
    covered = [i for i in instances if not i["abstained"]]
    abstained = [i for i in instances if i["abstained"]]

    exact_ok = sum(1 for i in covered if i["exact_match"])
    norm_ok = sum(1 for i in covered if i["normalized_match"])

    # Over the whole population an abstention counts as not correct: the
    # document was not auto-processed.
    norm_ok_all = sum(1 for i in instances if not i["abstained"] and i["normalized_match"])

    errors = {k: sum(1 for i in covered if i["outcome"] == k) for k in ERROR_KINDS}

    would_be_wrong = sum(1 for i in instances if not i["would_be_correct"])
    caught = sum(1 for i in abstained if not i["would_be_correct"])

    return {
        "n_instances": n,
        "coverage": wilson(len(covered), n),
        "abstention_rate": wilson(len(abstained), n),

        "exact_match_on_covered": wilson(exact_ok, len(covered)),
        "normalized_match_on_covered": wilson(norm_ok, len(covered)),
        "normalized_match_on_all": wilson(norm_ok_all, n),

        "errors": errors,
        "error_rate_on_covered": wilson(sum(errors.values()), len(covered)),

        # Of what was flagged, this measures how much would have been wrong. A
        # system that flags everything drives this toward the base error rate.
        "abstention_precision": wilson(caught, len(abstained)),
        # Of everything that would have been wrong, this measures how much was caught.
        "abstention_recall": wilson(caught, would_be_wrong),
        "would_be_wrong_total": would_be_wrong,
    }


def calibration(instances: Sequence[dict], confidences: Sequence[float],
                n_buckets: int = 10, min_n: int = MIN_BUCKET_N) -> Dict[str, object]:
    """This buckets by stated confidence and compares against observed accuracy.

    It is scored on `would_be_correct` over all instances including abstained ones.
    Whether stated confidence predicts correctness is a property of the model
    rather than of the gate in front of it.

    ECE is the count-weighted mean gap between stated confidence and observed
    accuracy. A model that says 1.0 while being right 90% of the time scores
    0.10.

    A bucket with fewer than `min_n` predictions is reported but marked sparse
    and does not count toward the curve. The curve is degenerate unless at
    least two buckets are informative.
    """
    assert len(instances) == len(confidences)
    buckets: List[Dict[str, object]] = []
    total = len(instances)
    ece = 0.0

    for b in range(n_buckets):
        lo, hi = b / n_buckets, (b + 1) / n_buckets
        idx = [k for k, c in enumerate(confidences)
               if (c > lo or (b == 0 and c >= 0.0)) and c <= hi]
        if not idx:
            buckets.append({"bucket": "%.1f-%.1f" % (lo, hi), "n": 0,
                            "mean_confidence": None, "observed_accuracy": None,
                            "gap": None})
            continue
        correct = sum(1 for k in idx if instances[k]["would_be_correct"])
        acc = correct / len(idx)
        mean_conf = sum(confidences[k] for k in idx) / len(idx)
        gap = abs(mean_conf - acc)
        ece += (len(idx) / total) * gap
        buckets.append({
            "bucket": "%.1f-%.1f" % (lo, hi), "n": len(idx),
            "sparse": len(idx) < min_n,
            "mean_confidence": round(mean_conf, 6),
            "observed_accuracy": round(acc, 6),
            "accuracy_ci": wilson(correct, len(idx)),
            "gap": round(gap, 6),
        })

    occupied = sum(1 for b in buckets if b["n"])
    informative = sum(1 for b in buckets if b["n"] >= min_n)
    return {
        "buckets": buckets,
        "ece": round(ece, 6),
        "occupied_buckets": occupied,
        "informative_buckets": informative,
        "min_bucket_n": min_n,
        # Fewer than two informative buckets is not a curve. It is flagged in
        # the data so a chart does not imply resolution that is not there.
        "degenerate": informative <= 1,
    }


def by_key(instances: Sequence[dict], keys: Sequence[str]) -> Dict[str, dict]:
    """This slices summaries by a per-instance key (stratum, field, ...)."""
    out: Dict[str, List[dict]] = {}
    for inst, k in zip(instances, keys):
        out.setdefault(k, []).append(inst)
    return {k: summarize(v) for k, v in sorted(out.items())}


# The reconciliation section starts here.
# Reading the total is transcription. Checking the total against the
# itemization is adjudication. They fail for different reasons and are scored
# separately.


def _money(v) -> Optional[Decimal]:
    if v is None:
        return None
    n = normalize("total_amount", str(v))
    try:
        return Decimal(n) if n is not None else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def score_reconciliation(gt: dict, pred: Optional[dict]) -> Dict[str, object]:
    """This scores one document's reconciliation.

    Two verdicts come from the same model output.

      model_verdict  is the model's own `reconciles` boolean; it read the page and
                     did the arithmetic itself.
      code_verdict   is computed in Python, which sums the line items the model
                     extracted and compares them against the total the model
                     extracted.

    Both use identical extractions, so any gap between them is arithmetic. That
    separates a misread number from a bad addition. The first needs a better
    reader; the second means the model should not be doing the sum.
    """
    gt_rec = gt.get("reconciliation") or {}
    gt_verdict = gt_rec.get("reconciles")
    if gt_verdict is None:  # OOD or no stated total leaves nothing to reconcile.
        return {"applicable": False}

    pred = pred or {}
    items = pred.get("line_items") or []
    model_block = pred.get("reconciliation") or {}

    code_sum = Decimal("0")
    parsed_items = 0
    for li in items:
        amt = _money(li.get("amount"))
        if amt is not None:
            code_sum += amt
            parsed_items += 1

    stated = _money((pred.get("total_amount") or {}).get("value"))
    model_sum = _money(model_block.get("line_items_sum"))
    true_sum = _money(gt_rec.get("line_items_sum"))

    # The tolerance is sub-cent only. A claim off by a penny is still off.
    tol = Decimal("0.005")
    code_verdict = (abs(code_sum - stated) <= tol) if stated is not None else None
    model_verdict = model_block.get("reconciles")
    model_verdict = bool(model_verdict) if isinstance(model_verdict, bool) else None

    def outcome(v):
        if v is None:
            return "no_verdict"
        if v == gt_verdict:
            return "correct"
        # Passing a claim that does not add up is a wrong payout. Flagging one
        # that does is a review cost. They are kept apart.
        return "false_pass" if v is True else "false_flag"

    return {
        "applicable": True,
        "gt_reconciles": gt_verdict,
        "model_verdict": model_verdict,
        "code_verdict": code_verdict,
        "model_outcome": outcome(model_verdict),
        "code_outcome": outcome(code_verdict),
        # This records whether the model added its own extracted items correctly.
        "model_arithmetic_correct": (model_sum is not None
                                     and abs(model_sum - code_sum) <= tol),
        # These record whether it found the right number of line items and read them
        # correctly.
        "n_items_gt": len(gt_rec.get("line_items") or []),
        "n_items_pred": parsed_items,
        "item_count_correct": parsed_items == len(gt_rec.get("line_items") or []),
        "items_sum_matches_truth": (true_sum is not None
                                    and abs(code_sum - true_sum) <= tol),
        "confidence": model_block.get("confidence", 0.0),
    }


def summarize_reconciliation(rows: Sequence[dict]) -> Dict[str, object]:
    """This aggregates reconciliation scores, keeping the two verdict paths apart."""
    live = [r for r in rows if r.get("applicable")]
    n = len(live)
    if not n:
        return {"n": 0, "applicable": False,
                "routed_to_review": sum(1 for r in rows if r.get("routed_to_review"))}

    def verdict_block(key: str) -> Dict[str, object]:
        outcomes = [r[key] for r in live]
        correct = sum(1 for o in outcomes if o == "correct")
        return {
            "accuracy": wilson(correct, n),
            "false_pass": sum(1 for o in outcomes if o == "false_pass"),
            "false_flag": sum(1 for o in outcomes if o == "false_flag"),
            "no_verdict": sum(1 for o in outcomes if o == "no_verdict"),
        }

    inconsistent = [r for r in live if r["gt_reconciles"] is False]
    caught_model = sum(1 for r in inconsistent if r["model_outcome"] == "correct")
    caught_code = sum(1 for r in inconsistent if r["code_outcome"] == "correct")

    return {
        "n": n,
        "routed_to_review": sum(1 for r in rows if r.get("routed_to_review")),
        "n_inconsistent_claims": len(inconsistent),
        "model_verdict": verdict_block("model_outcome"),
        "code_verdict": verdict_block("code_outcome"),
        # This is recall on the claims that do not add up, the ones that would
        # otherwise be paid wrong.
        "bad_claim_recall_model": wilson(caught_model, len(inconsistent)),
        "bad_claim_recall_code": wilson(caught_code, len(inconsistent)),
        "model_arithmetic_accuracy": wilson(
            sum(1 for r in live if r["model_arithmetic_correct"]), n),
        "line_item_count_accuracy": wilson(
            sum(1 for r in live if r["item_count_correct"]), n),
        "line_item_sum_accuracy": wilson(
            sum(1 for r in live if r["items_sum_matches_truth"]), n),
    }


# The paired comparison section starts here.

WRONG_EMISSION = (WRONG_VALUE, HALLUCINATED)   # A value went out and it was wrong.


def paired_difference(candidate: Sequence[dict], baseline: Sequence[dict],
                      resamples: int, seed: int) -> Dict[str, object]:
    """This compares two configurations scored on the same field-instances.

    Every configuration is scored on identical documents, so the difference
    between two of them is a paired quantity, and its interval is tighter than
    two overlapping one-sample intervals suggest. Two differences stay well
    defined when coverage differs: the wrong-emission rate (a wrong value left
    the system: wrong_value or hallucinated_field, the wrong-payout outcomes)
    and coverage itself.

    The bootstrap resamples documents, because the six field-instances on a
    page share one scan and are not independent. The exact test is the
    two-sided binomial on discordant instances (McNemar's exact test).
    """
    if len(candidate) != len(baseline):
        raise ValueError("paired comparison needs equal-length instance lists")
    for a, b in zip(candidate, baseline):
        if (a.get("doc_id"), a["field"]) != (b.get("doc_id"), b["field"]):
            raise ValueError("instances are not aligned on (doc_id, field)")
    n = len(candidate)
    wrong_c = [a["outcome"] in WRONG_EMISSION for a in candidate]
    wrong_b = [b["outcome"] in WRONG_EMISSION for b in baseline]
    cov_c = [not a["abstained"] for a in candidate]
    cov_b = [not b["abstained"] for b in baseline]
    only_c = sum(1 for x, y in zip(wrong_c, wrong_b) if x and not y)
    only_b = sum(1 for x, y in zip(wrong_c, wrong_b) if y and not x)

    by_doc: Dict[str, List[int]] = {}
    for i, a in enumerate(candidate):
        by_doc.setdefault(a.get("doc_id"), []).append(i)
    docs = list(by_doc)
    rng = random.Random(seed)
    d_wrong, d_cov = [], []
    for _ in range(resamples):
        idx = [i for d in (rng.choice(docs) for _ in docs) for i in by_doc[d]]
        m = len(idx)
        d_wrong.append((sum(wrong_c[i] for i in idx) - sum(wrong_b[i] for i in idx)) / m)
        d_cov.append((sum(cov_c[i] for i in idx) - sum(cov_b[i] for i in idx)) / m)

    return {
        "n_instances": n,
        "n_documents": len(docs),
        "wrong_emissions": {
            "candidate": sum(wrong_c), "baseline": sum(wrong_b),
            "candidate_only": only_c, "baseline_only": only_b,
            "difference_point": round((sum(wrong_c) - sum(wrong_b)) / n, 6),
            "difference_ci": _percentile_ci(d_wrong),
            "exact_p": round(_binomial_two_sided(min(only_c, only_b), only_c + only_b), 6),
        },
        "coverage": {
            "candidate": round(sum(cov_c) / n, 6), "baseline": round(sum(cov_b) / n, 6),
            "difference_point": round((sum(cov_c) - sum(cov_b)) / n, 6),
            "difference_ci": _percentile_ci(d_cov),
        },
        "resamples": resamples, "seed": seed,
        "unit": "field-instance; bootstrap resamples documents",
    }


def _percentile_ci(samples: List[float]) -> Dict[str, float]:
    s = sorted(samples)
    lo = s[int(0.025 * (len(s) - 1))]
    hi = s[int(math.ceil(0.975 * (len(s) - 1)))]
    return {"low": round(lo, 6), "high": round(hi, 6)}


def _binomial_two_sided(k: int, n: int) -> float:
    """This computes the two-sided exact binomial p-value at p = 0.5 for k of n
    discordant instances. It returns 1.0 when nothing is discordant."""
    if n == 0:
        return 1.0
    k = min(k, n - k)
    tail = sum(math.comb(n, i) for i in range(0, k + 1)) / 2 ** n
    return min(1.0, 2 * tail)
