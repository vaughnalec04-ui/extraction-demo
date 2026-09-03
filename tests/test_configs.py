"""resolve() turns two cached reader responses into one configuration's emitted
values, abstentions and cost. Each configuration's rule is asserted here."""
import pytest

from meridian.harness.configs import CONFIGS, PRIMARY, VERIFIER, resolve
from meridian.schema import FIELD_ORDER


def _rec(values, conf, cost=0.001, latency=1.0, error=None):
    resp = None if error else {f: {"value": v, "confidence": conf} for f, v in zip(FIELD_ORDER, values)}
    return {"response": resp, "cost_usd": cost, "latency_s": latency, "error": error}


P_VALUES = ["CLM-1", "MP-1", "Ada Lovelace", "2026-01-01", "Acme Clinic", "$1,696.42"]
V_SAME = ["CLM-1", "MP-1", "Ada Lovelace", "2026-01-01", "Acme Clinic", "1696.42"]   # same, differently formatted
V_DIFF = ["CLM-1", "MP-1", "Ada Lovelace", "2026-01-01", "Acme Clinic", "$2,120.53"]  # disagrees on the total


def test_every_config_is_resolvable():
    for cfg in CONFIGS:
        out, usage = resolve(cfg, _rec(P_VALUES, 1.0), _rec(V_SAME, 1.0), 0.0, 0.0)
        assert set(FIELD_ORDER) <= set(out)
        assert usage["n_calls"] >= 1


def test_unknown_config_is_rejected():
    with pytest.raises(ValueError):
        resolve("nope", _rec(P_VALUES, 1.0), _rec(V_SAME, 1.0), 0.0, 0.0)


def test_primary_solo_uses_primary_and_pays_for_one_call():
    out, usage = resolve("primary_solo", _rec(P_VALUES, 0.95, cost=0.001), _rec(V_DIFF, 1.0, cost=0.002), 0.5, 0.0)
    assert out["total_amount"]["value"] == "$1,696.42"
    assert out["total_amount"]["source"] == PRIMARY
    assert usage["n_calls"] == 1 and usage["cost_usd"] == pytest.approx(0.001)


def test_solo_abstains_below_threshold():
    out, _ = resolve("primary_solo", _rec(P_VALUES, 0.4), _rec(V_SAME, 1.0), tau_abstain=0.5, tau_escalate=0.0)
    assert all(out[f]["abstained"] for f in FIELD_ORDER)
    out, _ = resolve("primary_solo", _rec(P_VALUES, 0.6), _rec(V_SAME, 1.0), tau_abstain=0.5, tau_escalate=0.0)
    assert not any(out[f]["abstained"] for f in FIELD_ORDER)


def test_cascade_escalates_when_primary_unsure():
    out, usage = resolve("cascade", _rec(P_VALUES, 0.8, cost=0.001), _rec(V_DIFF, 1.0, cost=0.002),
                         tau_abstain=0.0, tau_escalate=0.9)
    assert out["_escalated"] is True
    assert out["total_amount"]["value"] == "$2,120.53"          # verifier's value
    assert out["total_amount"]["source"] == VERIFIER
    assert usage["n_calls"] == 2 and usage["cost_usd"] == pytest.approx(0.003)


def test_cascade_holds_when_primary_confident():
    out, usage = resolve("cascade", _rec(P_VALUES, 0.95, cost=0.001), _rec(V_DIFF, 1.0, cost=0.002),
                         tau_abstain=0.0, tau_escalate=0.9)
    assert out["_escalated"] is False
    assert out["total_amount"]["value"] == "$1,696.42"
    assert usage["n_calls"] == 1 and usage["cost_usd"] == pytest.approx(0.001)


def test_cascade_at_zero_threshold_equals_primary():
    # With a constant confidence signal the cascade never fires.
    solo, su = resolve("primary_solo", _rec(P_VALUES, 1.0), _rec(V_DIFF, 1.0), 0.0, 0.0)
    casc, cu = resolve("cascade", _rec(P_VALUES, 1.0), _rec(V_DIFF, 1.0), 0.0, 0.0)
    casc.pop("_escalated")
    assert {f: solo[f]["value"] for f in FIELD_ORDER} == {f: casc[f]["value"] for f in FIELD_ORDER}
    assert su["cost_usd"] == cu["cost_usd"]


def test_double_key_agrees_on_normalized_value():
    out, usage = resolve("double_key", _rec(P_VALUES, 1.0), _rec(V_SAME, 1.0), 0.0, 0.0)
    assert out["total_amount"]["agreed"] is True
    assert out["total_amount"]["abstained"] is False
    assert usage["n_calls"] == 2


def test_double_key_abstains_on_disagreement():
    out, _ = resolve("double_key", _rec(P_VALUES, 0.9), _rec(V_DIFF, 0.7), 0.0, 0.0)
    assert out["total_amount"]["abstained"] is True
    assert out["claim_id"]["abstained"] is False               # only the disputed field is flagged
    assert out["total_amount"]["confidence"] == pytest.approx(0.7)


def test_failed_call_gives_empty_cells():
    out, usage = resolve("primary_solo", _rec(P_VALUES, 1.0, error="429: quota"), _rec(V_SAME, 1.0), 0.5, 0.0)
    assert all(out[f]["value"] is None for f in FIELD_ORDER)
    assert all(out[f]["abstained"] for f in FIELD_ORDER)      # confidence 0.0 < 0.5
    assert usage["errors"] == ["429: quota"]
