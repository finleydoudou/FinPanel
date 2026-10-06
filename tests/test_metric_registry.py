"""Semantic catalog contracts, independent of any resolver."""

import pytest

from finpanel.metrics import REGISTRY, mapping_for
from finpanel.metrics.registry import unit_status


def test_exact_six_immutable_definitions():
    assert set(REGISTRY) == {
        "revenue",
        "net_income",
        "assets",
        "liabilities",
        "cash_and_cash_equivalents",
        "operating_cash_flow",
    }
    with pytest.raises(TypeError):
        REGISTRY["extra"] = REGISTRY["assets"]


@pytest.mark.parametrize("metric", REGISTRY)
def test_explicit_testable_contracts(metric):
    d = REGISTRY[metric]
    assert d.status == "supported" and d.unit_family == "currency" and d.exclusions
    assert d.allowed_taxonomies == ("us-gaap",)
    assert d.period_kinds == (
        ("instant",) if d.context == "instant" else ("annual", "single_quarter", "year_to_date")
    )
    for m in d.mappings:
        assert m.metric == metric and m.context == d.context and m.priority == 100
        assert m.rationale and m.support_notes
        assert mapping_for(metric, m.taxonomy, m.concept) is m


@pytest.mark.parametrize(
    "taxonomy,concept",
    [
        ("company", "Revenues"),
        ("us-gaap", "Revenue"),
        ("us-gaap", "revenues"),
        ("us-gaap", "RevenuesExtra"),
        ("ifrs-full", "Revenue"),
        ("us-gaap", "RevenueFromContractWithCustomerIncludingAssessedTax"),
    ],
)
def test_no_fuzzy_mapping(taxonomy, concept):
    assert mapping_for("revenue", taxonomy, concept) is None


@pytest.mark.parametrize("unit", ["EUR", "JPY", "shares", "usd", "USD/shares", "ABC", ""])
def test_no_currency_guessing_or_conversion(unit):
    assert unit_status(unit) == "unsupported_unit_no_conversion"
    assert unit_status("USD") == "supported_usd"
