"""Explicit source policy, reported preference and diagnostic comparisons."""

import pytest
from test_asof import fact
from test_derivation_scope import annual_records
from test_metric_candidates import report

from finpanel import metrics
from finpanel.errors import ValidationError


def reported_q2(value=150, n=21):
    return fact(
        n=n,
        concept="Revenues",
        start="2021-04-01",
        end="2021-06-30",
        fy=2021,
        fp="Q2",
        form="10-Q",
        value=value,
    )


def test_reported_only_default_and_explicit_fallback():
    r = report(*annual_records())
    old = metrics.resolve_candidates(r, fiscal_year=2021, period="Q2")
    default = metrics.resolve_quarter_candidates(r, fiscal_year=2021, quarter="Q2")
    fallback = metrics.resolve_quarter_candidates(
        r, fiscal_year=2021, quarter="Q2", source_policy="reported_then_derived"
    )
    assert old.state == default.state == "unavailable" and default.derivation is None
    assert fallback.value == 150 and fallback.source_type == "derived"


@pytest.mark.parametrize("value,status,difference", [(150, "equal", 0), (151, "different", 1)])
def test_reported_preferred_and_comparison_diagnostic(value, status, difference):
    r = report(*annual_records(), reported_q2(value))
    result = metrics.resolve_quarter_candidates(
        r, fiscal_year=2021, quarter="Q2", source_policy="reported_then_derived"
    )
    assert result.source_type == "reported" and result.value == value and result.derivation is None
    comparison = metrics.compare_quarter_candidates(r, fiscal_year=2021, quarter="Q2")
    assert comparison.status == status and comparison.difference == difference
    assert comparison.reported.value == value and comparison.derived.value == 150
    assert comparison.reported.selected and comparison.derived.minuend.selected


def test_reported_conflict_is_never_repaired():
    r = report(*annual_records(), reported_q2(150, 21), reported_q2(151, 22))
    result = metrics.resolve_quarter_candidates(
        r, fiscal_year=2021, quarter="Q2", source_policy="reported_then_derived"
    )
    assert result.state == "conflicted" and result.value is None and result.derivation is None
    comparison = metrics.compare_quarter_candidates(r, fiscal_year=2021, quarter="Q2")
    assert comparison.status == "not_comparable" and comparison.difference is None
    assert comparison.derived.value == 150  # Inspection never changes ordinary conflict state.


def test_q1_remains_direct_reported():
    r = report(*annual_records())
    result = metrics.resolve_quarter_candidates(
        r, fiscal_year=2021, quarter="Q1", source_policy="reported_then_derived"
    )
    assert result.source_type == "reported" and result.value == 100
    assert metrics.derive_from_candidates(r, fiscal_year=2021, quarter="Q1").status == "ineligible"


@pytest.mark.parametrize("quarter", ["Q2", "Q3", "Q4"])
def test_explicit_derivation_only(quarter):
    r = report(*annual_records())
    assert metrics.resolve_candidates(r, fiscal_year=2021, period=quarter).value is None
    assert metrics.derive_from_candidates(r, fiscal_year=2021, quarter=quarter).value is not None


def test_invalid_policy_rejected():
    with pytest.raises(ValidationError, match="source_policy"):
        metrics.resolve_quarter_candidates(
            report(*annual_records()), fiscal_year=2021, quarter="Q2", source_policy="guess"
        )


def test_unsupported_derive_api_never_requires_network():
    r = metrics.derive_quarter(
        1, "assets", fiscal_year=2021, quarter="Q4", as_of="2024-01-01T00:00:00Z"
    )
    assert r.value is None and r.status == "ineligible"
