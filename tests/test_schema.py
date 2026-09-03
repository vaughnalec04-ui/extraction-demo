"""normalize() defines what 'normalized match' means. Each field type has a
canonical form; these tests pin down what is and is not forgiven."""
import pytest

from meridian.schema import FIELD_ORDER, normalize, response_schema


@pytest.mark.parametrize("raw", ["CLM-40218", "clm 40218", "CLM40218", " clm-40218 "])
def test_identifier_ignores_case_and_separators(raw):
    assert normalize("claim_id", raw) == "CLM40218"


@pytest.mark.parametrize("raw", ["$1,412.50", "1412.5", "USD 1412.50", "1412.50 USD", " $1412.50 "])
def test_money_canonicalises_to_two_decimals(raw):
    assert normalize("total_amount", raw) == "1412.50"


def test_money_distinguishes_a_penny():
    assert normalize("total_amount", "1412.50") != normalize("total_amount", "1412.51")


@pytest.mark.parametrize("raw", ["2026-03-14", "2026-3-14", "03/14/2026", "3/14/26",
                                 "March 14, 2026", "14 Mar 2026", "14 March 2026"])
def test_date_formats_collapse_to_iso(raw):
    assert normalize("date_of_service", raw) == "2026-03-14"


def test_name_folds_case_accents_punctuation_whitespace():
    assert normalize("claimant_name", "  Dolores   FERRARO. ") == "dolores ferraro"
    assert normalize("provider_name", "Émile Zola") == "emile zola"


def test_name_does_not_reorder_tokens():
    # A payee written surname-first is a real difference, not formatting.
    assert normalize("claimant_name", "Ferraro, Dolores") != normalize("claimant_name", "Dolores Ferraro")


@pytest.mark.parametrize("raw", [None, "", "   ", "null", "None", "N/A", "na", "-", "--"])
def test_absent_markers_normalise_to_none(raw):
    assert normalize("total_amount", raw) is None


def test_normalizers_are_total_and_never_raise():
    # Garbage in must degrade to a non-match, never to an exception mid-run.
    for field in FIELD_ORDER:
        assert isinstance(normalize(field, "!!! ??? ..."), (str, type(None)))
        assert isinstance(normalize(field, "12/99/9999"), (str, type(None)))


def test_schema_requires_fields_and_reconciliation():
    s = response_schema()
    for f in FIELD_ORDER:
        assert f in s["required"]
        assert s["properties"][f]["properties"]["value"]["nullable"] is True
        assert "confidence" in s["properties"][f]["required"]
    for k in ("line_items", "line_items_sum", "reconciles", "reconciliation_confidence"):
        assert k in s["required"]
    assert s["properties"]["reconciles"]["nullable"] is True
