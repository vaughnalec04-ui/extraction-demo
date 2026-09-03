"""The manifest of records flagged for manual label verification."""
from __future__ import annotations

import os
from typing import List

from meridian.schema import FIELD_ORDER
from meridian.settings import DATA, DOC_EXT


SPOT_CHECK_N = 10


def write_spot_check(records: List[dict]) -> List[str]:
    """Flag records for manual label verification, weighted toward hard cases.

    Not random. The labels most worth checking are where authoring could have
    gone wrong: ambiguous pairs, handwritten amounts, absent fields, and OOD
    pages where every label is null.
    """
    by_id = {r["doc_id"]: r for r in records}

    def pick(pred, n):
        # Interleave tune and test so both splits are covered. Checking labels
        # is not evaluation, so reading a test label leaks nothing.
        hits = [r for r in records if pred(r)]
        tune = [r["doc_id"] for r in hits if r["split"] == "tune"]
        test = [r["doc_id"] for r in hits if r["split"] == "test"]
        out = []
        for i in range(max(len(tune), len(test))):
            if i < len(tune):
                out.append(tune[i])
            if i < len(test):
                out.append(test[i])
        return out[:n]

    chosen = []
    chosen += pick(lambda r: r["render"].get("distractor_position") == "below", 2)
    chosen += pick(lambda r: r["render"].get("distractor_position") == "above", 1)
    chosen += pick(lambda r: r["stratum"] == "degraded"
                   and r["render"].get("handwritten_amount"), 2)
    chosen += pick(lambda r: r["stratum"] == "degraded"
                   and r["render"].get("stamp"), 1)
    chosen += pick(lambda r: r["stratum"] == "incomplete"
                   and r["render"]["absent_field"] == "total_amount", 1)
    chosen += pick(lambda r: r["stratum"] == "incomplete"
                   and r["render"]["absent_field"] != "total_amount", 1)
    chosen += pick(lambda r: r["stratum"] == "ood", 2)
    chosen += pick(lambda r: r["stratum"] == "clean", 1)
    seen, ordered = set(), []
    for c in chosen:
        if c not in seen:
            seen.add(c); ordered.append(c)
    ordered = ordered[:SPOT_CHECK_N]

    lines = [
        "# Spot-check manifest",
        "",
        "%d of %d records flagged for **manual label verification**. Open each"
        % (len(ordered), len(records)),
        "image next to its expected values below and confirm the label is what a",
        "careful human keyer would record. These were chosen for difficulty, not",
        "at random; they are where label authoring could have gone wrong.",
        "",
        "Labels were authored first, in `src/meridian/dataset/labels.py`,",
        "and each image was rendered from its record. No label is downstream of a",
        "model.",
        "",
        "| # | doc | image | stratum | split | what to check |",
        "|---|-----|-------|---------|-------|----------------|",
    ]
    notes = []
    for i, doc_id in enumerate(ordered, 1):
        r = by_id[doc_id]
        st, rr = r["stratum"], r["render"]
        if rr.get("distractor_total"):
            note = ("two totals on the page; confirm `TOTAL DUE` is the label and "
                    "`%s` (%s) is NOT" % (rr["distractor_label"], rr["distractor_total"]))
        elif rr.get("handwritten_amount"):
            note = "amount is handwriting-style; confirm every digit is legible and matches"
        elif st == "incomplete":
            note = "`%s` must be absent from the image, not merely faint" % rr["absent_field"]
        elif st == "ood":
            note = "wrong doc type; confirm none of the six fields truly appear"
        else:
            note = "baseline; confirm all six values transcribe exactly"
        lines.append("| %d | `%s` | [`data/docs/%s%s`](docs/%s%s) | %s | %s | %s |"
                     % (i, doc_id, doc_id, DOC_EXT, doc_id, DOC_EXT, st, r["split"], note))
        notes.append((doc_id, r))

    lines += ["", "## Expected values", ""]
    for doc_id, r in notes:
        lines.append("### `%s`: %s / %s" % (doc_id, r["stratum"], r["doc_type"]))
        for f in FIELD_ORDER:
            v = r["fields"][f]
            lines.append("- `%s` = %s" % (f, "**ABSENT (null)**" if v is None else "`%s`" % v))
        if r["render"].get("distractor_total"):
            lines.append("- _distractor on page:_ `%s` = `%s` (must NOT be extracted)"
                         % (r["render"]["distractor_label"], r["render"]["distractor_total"]))
        lines.append("")

    with open(os.path.join(DATA, "spot_check.md"), "w") as fh:
        fh.write("\n".join(lines) + "\n")
    return ordered
