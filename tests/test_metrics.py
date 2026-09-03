"""The scoring primitives. Every headline number in results.json passes through
these functions, so each documented contract is asserted here."""
import pytest

from meridian.harness import metrics as m


# --- wilson ---------------------------------------------------------------

def test_wilson_zero_n_is_undefined_not_perfect():
    w = m.wilson(0, 0)
    assert w["point"] is None and w["low"] is None and w["high"] is None
    assert w["n"] == 0


def test_wilson_all_correct_lower_bound_below_one():
    # 240/240 must not report [1.0, 1.0].
    w = m.wilson(240, 240)
    assert w["point"] == 1.0
    assert 0.98 < w["low"] < 1.0
    assert w["high"] == 1.0


def test_wilson_is_bounded_and_monotone_in_n():
    w10, w100 = m.wilson(9, 10), m.wilson(90, 100)
    for w in (w10, w100):
        assert 0.0 <= w["low"] <= w["point"] <= w["high"] <= 1.0
    assert (w100["high"] - w100["low"]) < (w10["high"] - w10["low"])


# --- classify -------------------------------------------------------------

@pytest.mark.parametrize("gt,pred,expected", [
    ("100.00", "$100.00", m.CORRECT),
    ("100.00", "$200.00", m.WRONG_VALUE),
    (None, "$100.00", m.HALLUCINATED),
    ("100.00", None, m.MISSED_FIELD),
    (None, None, m.CORRECT_REJECT),
])
def test_classify_five_outcomes(gt, pred, expected):
    r = m.classify("total_amount", gt, pred, abstained=False)
    assert r["outcome"] == expected
    assert r["would_be_outcome"] == expected
    assert r["would_be_correct"] is (expected in (m.CORRECT, m.CORRECT_REJECT))


def test_classify_abstention_keeps_would_be_outcome():
    # Abstention precision depends on this.
    r = m.classify("total_amount", "100.00", "$200.00", abstained=True)
    assert r["outcome"] == m.ABSTAINED
    assert r["would_be_outcome"] == m.WRONG_VALUE
    assert r["would_be_correct"] is False


def test_classify_exact_match_requires_correctness():
    r = m.classify("total_amount", "100.00", "$100.00", abstained=False)
    assert r["normalized_match"] is True and r["exact_match"] is False
    r = m.classify("claim_id", "CLM-1", "CLM-1", abstained=False)
    assert r["exact_match"] is True


# --- summarize ------------------------------------------------------------

def _inst(gt, pred, abstained=False):
    return m.classify("total_amount", gt, pred, abstained)


def test_summarize_coverage_and_abstention():
    instances = [
        _inst("1.00", "1.00"), _inst("2.00", "2.00"), _inst("3.00", "3.00"),   # 3 correct, covered
        _inst("4.00", "9.00"),                                                  # 1 wrong, covered
        _inst("5.00", "9.00", abstained=True),                                  # wrong, flagged (caught)
        _inst("6.00", "6.00", abstained=True),                                  # right, flagged (wasted)
    ]
    s = m.summarize(instances)
    assert s["n_instances"] == 6
    assert s["coverage"]["point"] == pytest.approx(4 / 6)
    assert s["normalized_match_on_covered"]["point"] == pytest.approx(3 / 4)
    assert s["errors"] == {m.WRONG_VALUE: 1, m.MISSED_FIELD: 0, m.HALLUCINATED: 0}
    assert s["would_be_wrong_total"] == 2
    assert s["abstention_precision"]["point"] == pytest.approx(1 / 2)
    assert s["abstention_recall"]["point"] == pytest.approx(1 / 2)


def test_abstention_precision_undefined_when_nothing_flagged():
    s = m.summarize([_inst("1.00", "1.00"), _inst("2.00", "9.00")])
    assert s["abstention_precision"]["point"] is None     # 0/0
    assert s["abstention_recall"]["point"] == 0.0         # 1 wrong, 0 caught


def test_error_kinds_are_never_pooled():
    s = m.summarize([_inst("1.00", "2.00"), _inst("1.00", None), _inst(None, "1.00")])
    assert s["errors"] == {m.WRONG_VALUE: 1, m.MISSED_FIELD: 1, m.HALLUCINATED: 1}
    assert s["error_rate_on_covered"]["point"] == 1.0


# --- calibration ----------------------------------------------------------

def test_calibration_single_bucket_is_flagged_degenerate():
    inst = [{"would_be_correct": True}] * 9 + [{"would_be_correct": False}]
    c = m.calibration(inst, [1.0] * 10)
    assert c["occupied_buckets"] == 1
    assert c["degenerate"] is True
    # ECE is |1.0 - 0.9| = 0.1. It measures the gap, not the constancy.
    assert c["ece"] == pytest.approx(0.1)


def test_calibration_ece_is_count_weighted_gap():
    inst = [{"would_be_correct": v} for v in (True, False, True, False)]
    c = m.calibration(inst, [1.0, 1.0, 0.5, 0.5])
    # bucket 0.9-1.0: n=2, conf 1.0, acc 0.5, gap 0.5, weight 0.5 -> 0.25
    # bucket 0.4-0.5: n=2, conf 0.5, acc 0.5, gap 0.0            -> 0.00
    assert c["ece"] == pytest.approx(0.25)
    assert c["occupied_buckets"] == 2
    assert c["degenerate"] is False


def test_calibration_requires_aligned_inputs():
    with pytest.raises(AssertionError):
        m.calibration([{"would_be_correct": True}], [1.0, 1.0])


# --- reconciliation -------------------------------------------------------

def _gt(reconciles, items, total):
    return {"reconciliation": {
        "reconciles": reconciles,
        "line_items": [{"description": "x", "amount": a} for a in items],
        "line_items_sum": "%.2f" % sum(float(a) for a in items),
        "stated_total": total}}


def _pred(items, total, model_sum, model_verdict, conf=0.9):
    return {"total_amount": {"value": total, "confidence": conf},
            "line_items": [{"description": "x", "amount": a} for a in items],
            "reconciliation": {"line_items_sum": model_sum, "reconciles": model_verdict,
                               "confidence": conf}}


def test_reconciliation_not_applicable_without_verdict():
    assert m.score_reconciliation({"reconciliation": {"reconciles": None}}, _pred([], None, None, None)) \
        == {"applicable": False}


def test_reconciliation_false_pass_is_the_wrong_payout():
    # Items and sum read correctly; the model still says it reconciles.
    gt = _gt(False, ["100.00", "50.00"], "175.00")
    r = m.score_reconciliation(gt, _pred(["$100.00", "$50.00"], "$175.00", "150.00", True))
    assert r["model_outcome"] == "false_pass"
    assert r["code_outcome"] == "correct"             # Python: 150 != 175 -> does not reconcile
    assert r["model_arithmetic_correct"] is True      # 150 == 150
    assert r["items_sum_matches_truth"] is True


def test_reconciliation_false_flag_is_the_review_cost():
    gt = _gt(True, ["100.00", "50.00"], "150.00")
    r = m.score_reconciliation(gt, _pred(["$100.00", "$50.00"], "$150.00", "150.00", False))
    assert r["model_outcome"] == "false_flag"
    assert r["code_outcome"] == "correct"


def test_reconciliation_separates_misread_from_arithmetic():
    # Model misreads 50.00 as 58.00 and adds its own numbers correctly.
    # Both verdict paths fail the same way; arithmetic is still correct.
    gt = _gt(True, ["100.00", "50.00"], "150.00")
    r = m.score_reconciliation(gt, _pred(["$100.00", "$58.00"], "$150.00", "158.00", False))
    assert r["model_outcome"] == "false_flag"
    assert r["code_outcome"] == "false_flag"
    assert r["model_arithmetic_correct"] is True
    assert r["items_sum_matches_truth"] is False      # the error is the misread


def test_reconciliation_penny_tolerance_only():
    gt = _gt(False, ["100.00"], "100.01")
    r = m.score_reconciliation(gt, _pred(["$100.00"], "$100.01", "100.00", False))
    assert r["code_verdict"] is False and r["code_outcome"] == "correct"


def test_summarize_reconciliation_counts_and_recall():
    rows = [
        m.score_reconciliation(_gt(False, ["1.00"], "2.00"), _pred(["1.00"], "2.00", "1.00", False)),  # caught
        m.score_reconciliation(_gt(False, ["1.00"], "2.00"), _pred(["1.00"], "2.00", "1.00", True)),   # false pass
        m.score_reconciliation(_gt(True, ["1.00"], "1.00"), _pred(["1.00"], "1.00", "1.00", True)),    # correct
        {"applicable": False},
    ]
    s = m.summarize_reconciliation(rows)
    assert s["n"] == 3 and s["n_inconsistent_claims"] == 2
    assert s["model_verdict"]["false_pass"] == 1
    assert s["bad_claim_recall_model"]["point"] == pytest.approx(0.5)
    assert s["bad_claim_recall_code"]["point"] == 1.0
    assert s["model_arithmetic_accuracy"]["point"] == 1.0


def test_summarize_reconciliation_empty_is_not_applicable():
    assert m.summarize_reconciliation([{"applicable": False}]) == {"n": 0, "applicable": False}


# --- paired comparison ------------------------------------------------------

def _pinst(doc, field, outcome, abstained=False):
    return {"doc_id": doc, "field": field, "outcome": outcome, "abstained": abstained}


def test_paired_difference_of_a_list_with_itself_is_zero():
    from meridian.harness import metrics as m
    a = [_pinst("d1", "f1", "correct"), _pinst("d1", "f2", "wrong_value"), _pinst("d2", "f1", "correct")]
    p = m.paired_difference(a, list(a), resamples=200, seed=1)
    w = p["wrong_emissions"]
    assert (w["candidate_only"], w["baseline_only"], w["exact_p"]) == (0, 0, 1.0)
    assert w["difference_point"] == 0 and p["coverage"]["difference_point"] == 0
    assert w["difference_ci"] == {"low": 0.0, "high": 0.0}


def test_paired_difference_counts_discordant_instances_and_exact_p():
    from meridian.harness import metrics as m
    base = [_pinst("d%d" % i, "f", "wrong_value") for i in range(3)] + [_pinst("d9", "f", "correct")]
    cand = [_pinst("d%d" % i, "f", "correct") for i in range(3)] + [_pinst("d9", "f", "correct")]
    w = m.paired_difference(cand, base, resamples=200, seed=1)["wrong_emissions"]
    assert (w["candidate_only"], w["baseline_only"]) == (0, 3)
    assert w["exact_p"] == 0.25          # two-sided, 2 * 0.5 ** 3
    assert w["difference_point"] == -0.75


def test_paired_difference_hallucination_is_a_wrong_emission_and_abstention_is_not():
    from meridian.harness import metrics as m
    base = [_pinst("d1", "f", "hallucinated_field"), _pinst("d2", "f", "missed_field")]
    cand = [_pinst("d1", "f", "abstained", abstained=True), _pinst("d2", "f", "missed_field")]
    p = m.paired_difference(cand, base, resamples=50, seed=1)
    assert (p["wrong_emissions"]["candidate_only"], p["wrong_emissions"]["baseline_only"]) == (0, 1)
    assert p["coverage"]["difference_point"] == -0.5


def test_paired_difference_is_deterministic_for_a_seed():
    from meridian.harness import metrics as m
    base = [_pinst("d%d" % (i // 2), "f%d" % (i % 2), "wrong_value" if i % 5 == 0 else "correct") for i in range(20)]
    cand = [_pinst("d%d" % (i // 2), "f%d" % (i % 2), "correct") for i in range(20)]
    assert m.paired_difference(cand, base, 300, 7) == m.paired_difference(cand, base, 300, 7)
    assert m.paired_difference(cand, base, 300, 7) != m.paired_difference(cand, base, 300, 8)


def test_paired_difference_rejects_misaligned_instances():
    import pytest
    from meridian.harness import metrics as m
    with pytest.raises(ValueError):
        m.paired_difference([_pinst("d1", "f1", "correct")], [_pinst("d1", "f2", "correct")], 10, 1)
    with pytest.raises(ValueError):
        m.paired_difference([_pinst("d1", "f1", "correct")], [], 10, 1)


def test_binomial_two_sided_matches_hand_values():
    from meridian.harness import metrics as m
    assert m._binomial_two_sided(0, 0) == 1.0
    assert m._binomial_two_sided(0, 1) == 1.0
    assert abs(m._binomial_two_sided(0, 2) - 0.5) < 1e-12
    assert abs(m._binomial_two_sided(1, 10) - 2 * 11 / 1024) < 1e-12


def test_calibration_with_no_instances_is_degenerate_not_an_error():
    from meridian.harness import metrics as m
    cal = m.calibration([], [])
    assert cal["degenerate"] is True
