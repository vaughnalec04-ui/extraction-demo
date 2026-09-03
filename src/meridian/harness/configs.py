"""The configurations compared on the cost/accuracy frontier.

The design copies a control Meridian already runs. Claims processors catch
keying errors by double-keying: two operators key the same document and
disagreements go to a supervisor. `double_key` is the automated version, with
two independent model readers and disagreements routed to the exception queue.

  primary_solo   one call to the primary reader. Uncertainty signal is
                 self-reported confidence.
  verifier_solo  one call to the second reader. Same signal.
  cascade        primary reads; the document goes to the verifier when the
                 primary's own confidence is low. Only works if self-reported
                 confidence carries information.
  double_key     both readers on every document; abstain where they disagree.
                 Costs more than either solo run. Needs no self-assessment.

cascade and double_key make opposite bets about self-reported confidence, so
both are measured.

Both readers are lite-class. The original design escalated to a Flash-tier
model, but free-tier quota on every Flash model runs out after roughly twenty
requests a day (FRICTION.md F-010), which cannot fund a scored evaluation. For
a disagreement signal, independence between readers matters more than relative
capability, so the design changed rather than the evaluation.
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

from meridian.schema import FIELD_ORDER, normalize
from meridian.settings import PRIMARY, VERIFIER

CONFIGS = ("primary_solo", "verifier_solo", "cascade", "double_key")


def _cells(rec: Optional[dict]) -> Dict[str, dict]:
    """Field cells from a cache record. A failed call gives empty cells, which
    score as missed fields."""
    resp = (rec or {}).get("response") or {}
    return {f: (resp.get(f) or {"value": None, "confidence": 0.0}) for f in FIELD_ORDER}


def resolve(config: str, primary_rec: dict, verifier_rec: dict,
            tau_abstain: float, tau_escalate: float) -> Tuple[Dict[str, dict], dict]:
    """Emitted value and abstention decision per field, plus the cost and
    latency this configuration incurred on the document.

    Returns ({field: {value, confidence, abstained, source}}, usage_block).
    """
    primary, verifier = _cells(primary_rec), _cells(verifier_rec)
    out: Dict[str, dict] = {}

    if config == "primary_solo":
        used = [primary_rec]
        for f in FIELD_ORDER:
            c = primary[f]
            out[f] = {"value": c["value"], "confidence": c["confidence"],
                      "abstained": c["confidence"] < tau_abstain, "source": PRIMARY}

    elif config == "verifier_solo":
        used = [verifier_rec]
        for f in FIELD_ORDER:
            c = verifier[f]
            out[f] = {"value": c["value"], "confidence": c["confidence"],
                      "abstained": c["confidence"] < tau_abstain, "source": VERIFIER}

    elif config == "cascade":
        # Escalation is per document. One weak field sends the whole page to
        # the verifier, since the API cannot re-read one field more cheaply
        # than the page.
        min_conf = min(primary[f]["confidence"] for f in FIELD_ORDER)
        escalated = min_conf < tau_escalate
        used = [primary_rec, verifier_rec] if escalated else [primary_rec]
        src = verifier if escalated else primary
        for f in FIELD_ORDER:
            c = src[f]
            out[f] = {"value": c["value"], "confidence": c["confidence"],
                      "abstained": c["confidence"] < tau_abstain,
                      "source": VERIFIER if escalated else PRIMARY}
        out["_escalated"] = escalated

    elif config == "double_key":
        # Both readers always. Disagreement is judged on the normalized value,
        # so "$1,696.42" against "1696.42" is agreement.
        used = [primary_rec, verifier_rec]
        for f in FIELD_ORDER:
            cv, sv = primary[f]["value"], verifier[f]["value"]
            agree = normalize(f, cv) == normalize(f, sv)
            out[f] = {"value": cv, "confidence": min(primary[f]["confidence"],
                                                     verifier[f]["confidence"]),
                      "abstained": not agree, "source": "both",
                      "agreed": agree}
    else:
        raise ValueError("unknown config: %s" % config)

    usage = {
        "cost_usd": sum(r.get("cost_usd", 0.0) for r in used if r),
        # Serial latency, as measured. double_key's two calls are independent
        # and could run concurrently; that is not measured here.
        "latency_s": sum(r.get("latency_s", 0.0) for r in used if r),
        "n_calls": len([r for r in used if r]),
        "errors": [r.get("error") for r in used if r and r.get("error")],
    }
    return out, usage
