"""Filter and resolve before arithmetic; a numeric difference cannot repair uncertainty."""

from dataclasses import replace
from datetime import datetime

import pytest
from test_asof import fact
from test_derivation_scope import annual_records, operands
from test_metric_candidates import report

from finpanel.metrics.derivation import derive_from_candidates, derive_operands
from finpanel.serialization import dumps, loads


def derive(records=None, *, quarter="Q2", cutoff="2024-01-01T00:00:00Z", policy="latest_available"):
    return derive_from_candidates(
        report(*(records or annual_records()), cutoff=cutoff),
        fiscal_year=2021,
        quarter=quarter,
        revision_policy=policy,
    )


@pytest.mark.parametrize("quarter,value", [("Q2", 150), ("Q3", 170), ("Q4", 180)])
def test_formulas_and_complete_operands(quarter, value):
    r = derive(quarter=quarter)
    assert r.status == "eligible" and r.value == value and r.source_type == "derived"
    assert r.minuend.source_type == r.subtrahend.source_type == "reported"
    assert r.minuend.selected and r.subtrahend.selected and r.availability.evidence
    assert r.value + r.subtrahend.value == r.minuend.value
    assert loads(dumps(r))["source_type"] == "derived"


def test_negative_quarter_is_not_a_conflict():
    records = list(annual_records())
    records[1] = fact(
        n=2, concept="Revenues", end="2021-06-30", fy=2021, fp="Q2", form="10-Q", value=-10
    )
    assert derive(tuple(records)).value == -110


def test_readiness_includes_annual_calendar_evidence_and_inclusive_cutoff():
    records = annual_records()
    before = derive(records, cutoff="2022-02-01T14:59:59Z")
    at = derive(records, cutoff="2022-02-01T15:00:00Z")
    assert before.value is None and at.value == 150
    assert at.availability.selected_evidence_ready_at == datetime.fromisoformat(
        "2022-02-01T15:00:00+00:00"
    )
    assert at.availability.derivable_as_of == at.as_of
    assert "not SEC publication" in at.availability.meaning


def test_date_only_ready_bound_is_next_sec_local_day():
    records = annual_records(accepted=None)
    assert derive(records, cutoff="2022-02-02T04:59:59Z").value is None
    r = derive(records, cutoff="2022-02-02T05:00:00Z")
    assert r.value == 150 and r.availability.precision == "includes_date_only"
    assert r.availability.selected_evidence_ready_at == r.as_of


def changed_component(n=11, value=300, **kwargs):
    return fact(
        n=n,
        concept="Revenues",
        end="2021-06-30",
        fy=2021,
        fp="Q2",
        form="10-Q",
        accepted="2023-02-01T15:00:00Z",
        filed="2023-02-01",
        value=value,
        **kwargs,
    )


def test_future_revision_no_effect_and_unpaired_later_revision_conflicts():
    records = annual_records()
    original = derive(records, cutoff="2022-03-01T00:00:00Z")
    future = derive((*records, changed_component()), cutoff="2022-03-01T00:00:00Z")
    assert (future.value, future.target_interval, future.status) == (
        original.value,
        original.target_interval,
        original.status,
    )
    late = derive((*records, changed_component()))
    assert late.value is None and "unpaired_value_revision" in late.reasons
    first = derive((*records, changed_component()), policy="first_reported")
    assert first.value == 150
    all_ = derive((*records, changed_component()), policy="all_available")
    assert all_.status == "conflicted" and all_.value is None


def test_jointly_reported_revision_pair_can_change_later_result():
    records = annual_records()
    a = changed_component()
    # Same filing discloses both cumulative components; Q1 is a comparative context.
    b = fact(
        n=11,
        concept="Revenues",
        end="2021-03-31",
        report="2021-06-30",
        fy=2021,
        fp="Q2",
        form="10-Q",
        accepted="2023-02-01T15:00:00Z",
        filed="2023-02-01",
        value=120,
    )
    # Helper raw envelopes differ; use the same actual filing record for both observations.
    b = replace(b, filing=a.filing, availability=a.availability)
    r = derive((*records, a, b))
    assert r.value == 180 and r.status == "eligible"
    assert "shared_filing_operands" in r.diagnostics
    assert derive((*records, a, b), policy="first_reported").value == 150


def test_all_available_agreement_does_not_build_cartesian_product():
    records = annual_records()
    repeat = changed_component(value=250)
    r = derive((*records, repeat), policy="all_available")
    assert r.value == 150 and len(r.minuend.selected) == 2 and len(r.subtrahend.selected) == 1


def test_equal_rank_conflict_removes_scalar():
    records = annual_records()
    tie = fact(n=21, concept="Revenues", end="2021-06-30", fp="Q2", form="10-Q", value=999)
    r = derive((*records, tie))
    assert r.value is None and r.status == "conflicted"


def test_date_only_ordering_uncertainty_removes_scalar():
    records = annual_records()
    tie = fact(
        n=21, concept="Revenues", end="2021-06-30", fp="Q2", form="10-Q", accepted=None, value=250
    )
    r = derive((*records, tie))
    assert r.status == "conflicted" and r.value is None


def test_mismatched_cutoff_and_policy_rejected():
    a, b = operands()
    other = replace(b, as_of=datetime.fromisoformat("2025-01-01T00:00:00+00:00"))
    assert "as_of_mismatch" in derive_operands(a, other, fiscal_year=2021, quarter="Q2").reasons


def test_future_calendar_and_unsupported_alternative_mutations():
    base = annual_records()
    earlier = derive(base)
    future = fact(
        n=30,
        concept="Revenues",
        start="2021-01-02",
        end="2021-12-30",
        accepted="2025-01-01T00:00:00Z",
        value=999,
    )
    extension = fact(n=31, concept="FakeRevenue", taxonomy="company", value=999)
    for changed in [
        (*base, future),
        (*base, replace(future, observation=replace(future.observation, value=-1))),
        (*base, extension),
    ]:
        r = derive(changed)
        assert (r.status, r.value, r.target_interval) == (
            earlier.status,
            earlier.value,
            earlier.target_interval,
        )


def test_instant_and_q1_never_derived():
    assert derive(quarter="Q1").value is None
    for metric in ("assets", "liabilities", "cash_and_cash_equivalents"):
        r = report(
            fact(
                concept={
                    "assets": "Assets",
                    "liabilities": "Liabilities",
                    "cash_and_cash_equivalents": "CashAndCashEquivalentsAtCarryingValue",
                }[metric],
                start="absent",
            ),
            metric=metric,
        )
        assert derive_from_candidates(r, fiscal_year=2021, quarter="Q2").status == "ineligible"


def test_unpaired_amendment_is_not_safe_even_when_first_loaded():
    records = list(annual_records())
    records[1] = fact(
        n=2, concept="Revenues", end="2021-06-30", fy=2021, fp="Q2", form="10-Q/A", value=250
    )
    for policy in ("first_reported", "latest_available", "all_available"):
        r = derive(tuple(records), policy=policy)
        assert r.value is None and "unpaired_amendment" in r.reasons
