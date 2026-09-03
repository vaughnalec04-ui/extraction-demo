"""Field definitions, the response schema sent to the model, and normalization.

The six fields are mixed in type (identifier, name, date, money) so the
normalization layer gets exercised. Exact match alone would understate accuracy
on everything except the identifiers.
"""
from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation
from typing import Dict, Optional

# --- field registry -------------------------------------------------------

IDENTIFIER, NAME, DATE, MONEY = "identifier", "name", "date", "money"

FIELDS: Dict[str, str] = {
    "claim_id": IDENTIFIER,
    "policy_number": IDENTIFIER,
    "claimant_name": NAME,
    "date_of_service": DATE,
    "provider_name": NAME,
    "total_amount": MONEY,
}

FIELD_ORDER = list(FIELDS)

# An error here is a wrong payout rather than a rekey, so it gets its own line
# in every report.
PAYMENT_CRITICAL = "total_amount"

FIELD_DESCRIPTIONS = {
    "claim_id": "The claim identifier assigned by Meridian, e.g. CLM-40218.",
    "policy_number": "The insured party's policy number, e.g. MP-7741-XA.",
    "claimant_name": "Full name of the person making the claim.",
    "date_of_service": "Date the service or loss occurred, as printed.",
    "provider_name": "Name of the medical provider, repair shop, or vendor.",
    "total_amount": (
        "The single final amount payable. If the document shows several money "
        "figures (subtotal, billed, adjustment, patient responsibility), this "
        "is the final total due, not any intermediate line."
    ),
}


LINE_ITEM_SCHEMA = {
    "type": "ARRAY",
    "description": (
        "Every priced line item in the itemisation, in the order printed. "
        "Transcribe amounts exactly as printed. Empty array if the document "
        "has no itemisation."
    ),
    "items": {
        "type": "OBJECT",
        "properties": {
            "description": {"type": "STRING"},
            "amount": {"type": "STRING"},
        },
        "required": ["description", "amount"],
    },
}


def response_schema() -> dict:
    """Schema handed to the model.

    Each field is an object so the model must return a confidence with the
    value. `value` is nullable so "this field is absent" is a real answer and
    not a parse failure.
    """
    props = {}
    for field in FIELD_ORDER:
        props[field] = {
            "type": "OBJECT",
            "properties": {
                "value": {
                    "type": "STRING",
                    "nullable": True,
                    "description": (
                        FIELD_DESCRIPTIONS[field]
                        + " Transcribe exactly as printed. Use null if the "
                        "document does not contain this field."
                    ),
                },
                "confidence": {
                    "type": "NUMBER",
                    "description": (
                        "Probability from 0.0 to 1.0 that the value above is "
                        "exactly correct. Use the full range: be honest when "
                        "the document is unclear rather than defaulting high."
                    ),
                },
            },
            "required": ["value", "confidence"],
        }
    props["line_items"] = LINE_ITEM_SCHEMA

    # The model does the sum itself and the harness redoes it in Python over the
    # same line items. Comparing the two separates a misread number from a bad
    # addition, which need different fixes.
    props["line_items_sum"] = {
        "type": "STRING",
        "nullable": True,
        "description": ("The sum of every line item amount above, to two decimal "
                        "places. Null if there is no itemisation."),
    }
    props["reconciles"] = {
        "type": "BOOLEAN",
        "nullable": True,
        "description": ("True if the stated total equals the sum of the line "
                        "items. False if they differ by any amount. Null if the "
                        "document has no itemisation or no stated total."),
    }
    props["reconciliation_confidence"] = {
        "type": "NUMBER",
        "description": "Probability from 0.0 to 1.0 that the reconciles verdict is correct.",
    }

    required = FIELD_ORDER + ["line_items", "line_items_sum", "reconciles",
                              "reconciliation_confidence"]
    return {"type": "OBJECT", "properties": props, "required": required}


# --- normalization --------------------------------------------------------
# Normalizers never raise. An unparseable value falls back to a casefolded
# string so it can still be compared; it just will not match.

_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_WS = re.compile(r"\s+")

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}


def _norm_identifier(v: str) -> str:
    """Case- and separator-insensitive: CLM-40218 == clm 40218 == CLM40218."""
    return re.sub(r"[^A-Za-z0-9]", "", v).upper()


def _norm_name(v: str) -> str:
    """Fold case, accents, punctuation and whitespace runs.

    Token order is kept. "Ferraro, Dolores" and "Dolores Ferraro" stay distinct
    because on a payee that difference is worth seeing.
    """
    v = unicodedata.normalize("NFKD", v)
    v = "".join(c for c in v if not unicodedata.combining(c))
    return _WS.sub(" ", _PUNCT.sub(" ", v)).strip().lower()


def _norm_money(v: str) -> str:
    """Canonical decimal string with 2dp: $1,412.50 == 1412.5 == USD 1412.50.

    Accounting negatives are honoured: (12.50), 12.50 CR and -12.50 all give
    -12.50. US formats only; a European decimal comma is not handled, and the
    corpus does not render one.
    """
    s = v.strip()
    negative = ((s.startswith("(") and s.endswith(")"))
                or re.match(r"^[^\d]*-", s) is not None
                or re.search(r"\bCR\b", s, re.IGNORECASE) is not None)
    cleaned = re.sub(r"[^\d.]", "", s.replace(",", ""))
    if cleaned in ("", "."):
        return _norm_name(v)
    try:
        amount = Decimal(cleaned).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return _norm_name(v)
    return str(-amount if negative else amount)


def _norm_date(v: str) -> str:
    """Best-effort ISO YYYY-MM-DD across the formats the corpus renders.

    Numeric dates are read month-first (US convention; the corpus is US), so
    01/02/2026 is 2 January. A reading with an impossible month or day is
    returned unnormalized rather than turned into a date that could match a
    label by accident.
    """
    s = v.strip()
    m = re.search(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", s)
    if m:
        y, mo, d = m.groups()
    else:
        m = re.search(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})", s)
        if m:
            mo, d, y = m.groups()
            if len(y) == 2:
                y = "20" + y
        else:
            # "March 14, 2026" / "14 Mar 2026"
            mon = re.search(r"([A-Za-z]{3,9})", s)
            day = re.search(r"\b(\d{1,2})\b", s)
            yr = re.search(r"\b(\d{4})\b", s)
            if not (mon and day and yr):
                return _norm_name(v)
            key = mon.group(1)[:3].lower()
            if key not in _MONTHS:
                return _norm_name(v)
            mo, d, y = str(_MONTHS[key]), day.group(1), yr.group(1)
    try:
        y, mo, d = int(y), int(mo), int(d)
    except ValueError:
        return _norm_name(v)
    if not (1 <= mo <= 12 and 1 <= d <= 31):
        return _norm_name(v)
    return "%04d-%02d-%02d" % (y, mo, d)


_NORMALIZERS = {
    IDENTIFIER: _norm_identifier,
    NAME: _norm_name,
    DATE: _norm_date,
    MONEY: _norm_money,
}


def normalize(field: str, value: Optional[str]) -> Optional[str]:
    """Normalize one field value. None (absent) passes through as None."""
    if value is None:
        return None
    text = str(value).strip()
    if text == "" or text.lower() in ("null", "none", "n/a", "na", "-", "--"):
        return None
    return _NORMALIZERS[FIELDS[field]](text)
