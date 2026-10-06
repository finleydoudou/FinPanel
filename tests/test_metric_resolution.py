"""No scalar unless semantic, temporal, unit, and period contracts agree."""

from dataclasses import replace

import pytest
from test_asof import fact
from test_metric_candidates import report, revenue

from finpanel.errors import ValidationError
from finpanel.metrics import resolve_candidates
from finpanel.metrics.engine import from_inspections


def resolve(r, **kwargs):
    return resolve_candidates(r, fiscal_year=2021, period="FY", **kwargs)


@pytest.mark.parametrize(
    "policy,value,state",
    [
        ("first_reported", 100, "resolved"),
        ("latest_available", 110, "resolved"),
        ("all_available", None, "conflicted"),
    ],
)
def test_revision_policies(policy, value, state):
    a = revenue()
    b = revenue(
        n=2,
        value=110,
        filed="2023-02-01",
        accepted="2023-02-01T15:00:00Z",
        report="2022-12-31",
        fy=2022,
    )
    r = resolve(report(a, b), revision_policy=policy)
    assert (r.value, r.state) == (value, state)
    if value is not None:
        s = r.selected[0].observation
        assert s.fact.filing and s.fact.availability and s.fact.observation.provenance
        assert s.supporting_evidence and s.period.evidence
        assert r.represented_period.fiscal_year == 2021
    else:
        assert not r.selected


def test_all_available_agreement_retains_every_source():
    a, b = revenue(), revenue(n=2, accepted="2023-02-01T15:00:00Z")
    r = resolve(report(a, b), revision_policy="all_available")
    assert r.value == 100 and len(r.selected) == 2


@pytest.mark.parametrize("value", [100, 101])
def test_unordered_same_time_conflict_even_equal_values(value):
    r = resolve(report(revenue(), revenue(n=2, value=value)))
    assert r.state == "conflicted" and r.value is None
    assert "multiple_equally_ranked_or_unordered_candidates" in r.conflicts


@pytest.mark.parametrize("value", [100, 101])
def test_mapping_scope_conflict_even_equal_values(value):
    r = resolve(report(revenue(), fact(n=2, concept="SalesRevenueNet", value=value)))
    assert r.state == "conflicted" and r.value is None
    assert "multiple_supported_concept_scopes" in r.conflicts


def test_unknown_availability_peer_prevents_scalar():
    r = resolve(report(revenue(), revenue(n=2, filed=None, accepted=None)))
    assert r.state == "conflicted" and "unknown_availability" in r.conflicts


def test_currency_disagreement_preserved_without_conversion():
    r = resolve(report(revenue(), revenue(n=2, unit="EUR")))
    assert r.state == "conflicted" and "incompatible_unit" in r.conflicts
    assert resolve(report(revenue(unit="EUR"))).state == "unsupported"


def test_unsupported_and_unavailable():
    empty = from_inspections(1, "eps", as_of="2024-01-01T00:00:00Z", inspections=())
    assert resolve(empty).state == "unsupported"
    r = resolve(report(revenue(), cutoff="2021-01-01T00:00:00Z"))
    assert r.state == "unavailable" and r.value is None


def test_ambiguous_period_no_date_query_bypass():
    r = report(revenue(form="8-K"))
    assert resolve(r).state == "ambiguous_period"
    assert resolve_candidates(r, start="2021-01-01", end="2021-12-31").state == "ambiguous_period"


def test_instant_date_and_query_validation():
    r = report(fact(concept="Assets", start="absent"), metric="assets")
    assert resolve_candidates(r, end="2021-12-31").value == 100
    with pytest.raises(ValidationError, match="Instant"):
        resolve(r)
    with pytest.raises(ValidationError, match="YYYY-MM-DD"):
        resolve_candidates(r, end="bad")


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"fiscal_year": 2021, "period": "TTM"},
        {"start": "2021-01-01"},
        {"end": "2021-12-31"},
        {"fiscal_year": True, "period": "FY"},
    ],
)
def test_invalid_duration_query(kwargs):
    with pytest.raises(ValidationError):
        resolve_candidates(report(revenue()), **kwargs)


def test_no_derived_quarter():
    r = resolve_candidates(report(revenue()), fiscal_year=2021, period="Q4")
    assert r.state == "unavailable" and r.value is None


def test_future_mutation_cannot_change_past_result():
    a = revenue()
    baseline = resolve(report(a))
    for future in [
        revenue(n=2, value=999, accepted="2025-02-01T00:00:00Z"),
        revenue(n=3, unit="EUR", accepted="2025-02-01T00:00:00Z"),
        revenue(n=4, end="2021-12-30", accepted="2025-02-01T00:00:00Z"),
        fact(n=5, concept="SalesRevenueNet", accepted="2025-02-01T00:00:00Z"),
    ]:
        r = resolve(report(a, future))
        assert (r.state, r.value, r.selected) == (baseline.state, baseline.value, baseline.selected)


def test_retrospective_or_tampered_evidence_rejected():
    r = report(revenue())
    with pytest.raises(ValidationError, match="as-of"):
        resolve(replace(r, mode="retrospective"))
    c = r.records[0]
    tampered = replace(
        c,
        observation=replace(
            c.observation, period=replace(c.observation.period, mode="retrospective")
        ),
    )
    with pytest.raises(ValidationError, match="differs"):
        resolve(replace(r, records=(tampered,)))


def test_ambiguous_other_mapping_cannot_be_hidden_by_different_dates():
    other = fact(n=2, concept="SalesRevenueNet", form="8-K", end="2021-12-30")
    r = resolve(report(revenue(), other))
    assert r.state == "ambiguous_period" and r.value is None


def test_report_cannot_drop_candidates_or_rejections():
    r = report(revenue(), fact(n=2, concept="SalesRevenueNet"))
    with pytest.raises(ValidationError, match="omits"):
        resolve(replace(r, records=r.records[:1]))
    r = report(revenue(), revenue(n=2, unit="EUR"))
    with pytest.raises(ValidationError, match="Rejection audit"):
        resolve(replace(r, rejected=()))


def test_ambiguous_older_comparative_does_not_block_known_current_period():
    comparative = revenue(n=2, start="2020-01-01", end="2020-12-31", fy=2021, report="2021-12-31")
    r = resolve(report(revenue(), comparative))
    assert r.state == "resolved" and r.value == 100
