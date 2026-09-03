"""This module generates the dataset. Labels are authored first, and the
documents are then rendered from the labels.

The meridian-generate command runs it.
"""
from __future__ import annotations

import json
import os

from meridian.dataset.degrade import degrade
from meridian.dataset.labels import author_labels
from meridian.dataset.render import render
from meridian.dataset.spotcheck import write_spot_check
from meridian.settings import DATA, DOC_EXT, DOCS, SEED


def main() -> None:
    os.makedirs(DOCS, exist_ok=True)
    records = author_labels()

    # Labels are written before any document exists, so nothing downstream can
    # influence ground truth.
    with open(os.path.join(DATA, "labels.jsonl"), "w") as fh:
        for rec in records:
            fh.write(json.dumps(rec, sort_keys=True) + "\n")

    splits = {"seed": SEED,
              "tune": sorted(r["doc_id"] for r in records if r["split"] == "tune"),
              "test": sorted(r["doc_id"] for r in records if r["split"] == "test")}
    with open(os.path.join(DATA, "splits.json"), "w") as fh:
        json.dump(splits, fh, indent=2)

    for rec in records:
        # Every record goes through degrade(). All carry mild noise and JPEG
        # loss; the degraded stratum adds rotation, blur, fade, speckle and a
        # stamp.
        img = degrade(render(rec), rec["render"])
        img.convert("L").save(os.path.join(DOCS, rec["doc_id"] + DOC_EXT),
                              format="JPEG", quality=rec["render"]["jpeg_quality"],
                              optimize=True)

    spot = write_spot_check(records)
    print("spot-check flagged (%d): %s" % (len(spot), ", ".join(spot)))
    print("labels: %d  tune: %d  test: %d" % (
        len(records), len(splits["tune"]), len(splits["test"])))
    print("docs written to %s" % DOCS)


if __name__ == "__main__":
    main()
