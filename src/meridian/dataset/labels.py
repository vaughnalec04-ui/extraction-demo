"""Author the ground truth.

Every record is produced from a fixed seed before any document exists. Nothing
here reads a document or calls a model.
"""
from __future__ import annotations

import random
from typing import Dict, List, Optional

from meridian.schema import FIELD_ORDER
from meridian.settings import CORPUS_VERSION, SEED


# Stratum -> (n_tune, n_test). Each stratum is large enough for its own Wilson
# interval; the harder strata get more weight.
STRATA = {
    "clean":      (12, 12),
    "ambiguous":  (8, 8),
    "degraded":   (8, 8),
    "incomplete": (8, 8),
    "ood":        (4, 4),
}


FIRST = ["Dolores", "Marcus", "Priya", "Ingrid", "Tomas", "Aisha", "Reuben",
         "Yolanda", "Dimitri", "Fenella", "Oscar", "Nadia", "Hugo", "Beatriz",
         "Curtis", "Lourdes", "Anton", "Simone", "Rafael", "Delphine"]


LAST = ["Ferraro", "Okonkwo", "Vandersteen", "Bhattacharya", "Quintero",
        "Lindqvist", "Achebe", "Marchetti", "Novotny", "Delacroix", "Osei",
        "Hargreaves", "Yamamoto", "Kowalczyk", "Boateng", "Sandoval",
        "Thibodeaux", "Mwangi", "Castellanos", "Rasmussen"]


PROVIDERS = [
    "Northgate Orthopedic Associates", "Cedar Vale Family Practice",
    "Harbor Point Imaging Center", "*Riverside Emergency Physicians*",
    "Blackwell Auto Body & Frame", "Summit Ridge Collision Repair",
    "Meadowlark Physical Therapy", "Anders & Pike Diagnostic Labs",
    "Fairhaven Urgent Care", "Trellis Road Chiropractic",
    "Kingsbury Motor Works", "Pinehurst Radiology Group",
]


# Line items are part of the label so the arithmetic on the page has ground
# truth. Reading the total is easy for these models; checking it against the
# itemisation is the part a claims processor is paid for, and where errors
# appear.
LINE_ITEMS = {
    "medical": ["Professional services", "Diagnostic imaging", "Laboratory panel",
                "Facility fee", "Materials / supplies", "Anaesthesia",
                "Physical therapy unit", "Durable medical equipment"],
    "repair": ["Parts - body panel", "Parts - trim", "Labour - bodywork",
               "Labour - refinish", "Paint materials", "Sublet - glass",
               "Towing / recovery", "Hazardous waste disposal"],
}


# Ways an inconsistent claim goes wrong. Each is a real failure mode in claims
# intake, so the model is tested on the kind of error a keyer would catch.
DISCREPANCY_MODES = [
    "omitted_line",      # a line item is priced but left out of the total
    "double_counted",    # one line counted twice
    "transposed_digit",  # total transposes two digits of the true sum
    "unlisted_surcharge" # total exceeds the itemisation by an unitemised amount
]


DOC_TYPES = ["claim_form", "medical_invoice", "adjuster_narrative", "repair_estimate"]


OOD_TYPES = ["vehicle_registration", "utility_bill", "employee_timesheet", "safety_datasheet"]


def author_labels() -> List[dict]:
    """Author the ground truth. Reads no document and calls no model."""
    rng = random.Random(SEED)
    records: List[dict] = []
    idx = 0

    for stratum, (n_tune, n_test) in STRATA.items():
        total = n_tune + n_test
        for i in range(total):
            idx += 1
            doc_id = "%s-%03d" % (stratum[:4], i + 1)
            split = "tune" if i < n_tune else "test"

            if stratum == "ood":
                # Wrong document type. None of the six fields exist and the
                # right answer is null for all of them.
                rec = {
                    "corpus_version": CORPUS_VERSION,
                    "doc_id": doc_id,
                    "stratum": stratum,
                    "split": split,
                    "doc_type": OOD_TYPES[i % len(OOD_TYPES)],
                    "fields": {f: None for f in FIELD_ORDER},
                    "reconciliation": {"line_items": [], "line_items_sum": None,
                                       "stated_total": None, "reconciles": None,
                                       "discrepancy": None, "discrepancy_mode": None},
                    "render": {"kind": "ood", "seed": SEED + idx,
                               "noise": rng.randint(4, 9),
                               "jpeg_quality": rng.randint(74, 90)},
                }
                records.append(rec)
                continue

            name = "%s %s" % (rng.choice(FIRST), rng.choice(LAST))
            fields: Dict[str, Optional[str]] = {
                "claim_id": "CLM-%05d" % rng.randint(10000, 99999),
                "policy_number": "MP-%04d-%s%s" % (
                    rng.randint(1000, 9999),
                    rng.choice("ABCDEFGHJKLMNPQRSTVWXYZ"),
                    rng.choice("ABCDEFGHJKLMNPQRSTVWXYZ")),
                "claimant_name": name,
                # Months 1-8 so no date of service falls after the engagement
                # date.
                "date_of_service": "2026-%02d-%02d" % (rng.randint(1, 8), rng.randint(1, 28)),
                "provider_name": rng.choice(PROVIDERS).strip("*"),
                "total_amount": None,          # derived from line items below
            }

            # --- itemisation, then the total derived from it ---------------
            kind = "repair" if i % 4 == 3 else "medical"
            n_items = rng.randint(3, 5)
            descriptions = rng.sample(LINE_ITEMS[kind], n_items)
            line_items = [{"description": desc,
                           "amount": "%.2f" % (rng.randint(1500, 240000) / 100.0)}
                          for desc in descriptions]
            item_sum = round(sum(float(li["amount"]) for li in line_items), 2)

            # About 38% of non-OOD claims are inconsistent. Reading the total
            # correctly is not the same as adjudicating the claim correctly.
            inconsistent = (i % 10) < 3
            if inconsistent:
                mode = DISCREPANCY_MODES[i % len(DISCREPANCY_MODES)]
                if mode == "omitted_line":
                    stated = round(item_sum - float(line_items[-1]["amount"]), 2)
                elif mode == "double_counted":
                    stated = round(item_sum + float(line_items[0]["amount"]), 2)
                elif mode == "transposed_digit":
                    stated = round(item_sum + rng.choice([90.0, 900.0, -90.0, -900.0]), 2)
                else:
                    stated = round(item_sum + rng.randint(2500, 18000) / 100.0, 2)
                if stated <= 0:
                    stated = round(item_sum + 137.50, 2)
            else:
                mode, stated = None, item_sum

            fields["total_amount"] = "%.2f" % stated
            reconciliation = {
                "line_items": line_items,
                "line_items_sum": "%.2f" % item_sum,
                "stated_total": "%.2f" % stated,
                "reconciles": not inconsistent,
                "discrepancy": "%.2f" % round(stated - item_sum, 2),
                "discrepancy_mode": mode,
            }

            render: Dict[str, object] = {
                "kind": stratum,
                "seed": SEED + idx,
                # Every page is a scan, so every stratum gets mild scanner
                # artefacts. Only the degraded stratum gets the heavy treatment.
                "noise": rng.randint(4, 9),
                "jpeg_quality": rng.randint(74, 90),
                # Format variety applies to every stratum so it is not confounded
                # with difficulty.
                "date_format": rng.choice(["iso", "us_slash", "long", "abbrev"]),
                "money_format": rng.choice(["dollar_comma", "dollar_plain", "usd_suffix"]),
                "font": rng.choice(["mono", "sans"]),
            }

            if stratum == "ambiguous":
                # Three ways a page can carry two plausible totals. A careful
                # keyer can resolve each one; a positional or largest-number
                # heuristic cannot.
                true_v = float(fields["total_amount"])
                mode = ["dual_label", "correction", "near_transposition"][i % 3]
                render["ambiguity_mode"] = mode

                if mode == "near_transposition":
                    # Off by one transposed digit, so a misread and a wrong
                    # pick look the same downstream.
                    distractor = round(true_v + rng.choice([-90.0, -9.0, 9.0, 90.0]), 2)
                    render["distractor_label"] = "SUBTOTAL"
                elif mode == "correction":
                    # Printed total struck through and corrected by hand. A keyer
                    # takes the correction. Hardest case in the corpus.
                    distractor = round(true_v * rng.choice([1.15, 1.22, 0.88]), 2)
                    render["distractor_label"] = "TOTAL DUE"
                    render["struck_through"] = True
                    render["handwritten_amount"] = True
                else:
                    distractor = round(true_v * (1 + rng.choice([0.12, 0.18, 0.25, 0.34])), 2)
                    render["distractor_label"] = rng.choice(
                        ["TOTAL CHARGES", "AMOUNT BILLED", "GROSS BILLED",
                         "SUBMITTED CHARGES", "TOTAL (BEFORE ADJUSTMENT)", "TOTAL BILLED"])

                render["distractor_total"] = "%.2f" % distractor
                # Position varies so "last figure on the page" does not work.
                render["distractor_position"] = ("above" if mode == "correction"
                                                 else rng.choice(["above", "below"]))

            if stratum == "degraded":
                # Set to match a bad fax-then-scan, fixed before scoring and not
                # tuned against any accuracy figure. The ceiling is legibility:
                # a keyer has to be able to recover every labelled value, or the
                # item has no derivable ground truth. Bounds were chosen by
                # looking at rendered pages, not at model scores.
                render["rotation"] = round(rng.uniform(-4.0, 4.0), 2)
                render["noise"] = rng.randint(16, 36)
                render["blur"] = round(rng.uniform(0.5, 1.1), 2)
                render["jpeg_quality"] = rng.randint(18, 34)
                render["fade"] = round(rng.uniform(0.62, 0.86), 2)
                render["speckle"] = round(rng.uniform(0.0015, 0.005), 4)
                render["handwritten_amount"] = rng.random() < 0.75
                render["stamp"] = rng.random() < 0.60
                render["form_rules"] = rng.random() < 0.50

            if stratum == "incomplete":
                # A required field is missing from the document. claim_id is
                # excluded because a claim with no claim id is not realistic.
                absent = rng.choice([f for f in FIELD_ORDER if f != "claim_id"])
                fields[absent] = None
                render["absent_field"] = absent
                # Two ways a field goes missing. A printed label above an empty
                # rule invites a guess more than a row that is not there.
                render["absence_mode"] = ["row_omitted", "blank_value"][i % 2]
                if absent == "total_amount":
                    # No stated total, so nothing to reconcile against. The
                    # verdict is undefined, not False.
                    reconciliation["reconciles"] = None
                    reconciliation["stated_total"] = None
                    reconciliation["discrepancy"] = None
                    reconciliation["discrepancy_mode"] = None

            records.append({
                "corpus_version": CORPUS_VERSION,
                "reconciliation": reconciliation,
                "doc_id": doc_id,
                "stratum": stratum,
                "split": split,
                "doc_type": DOC_TYPES[i % len(DOC_TYPES)],
                "fields": fields,
                "render": render,
            })
    return records
