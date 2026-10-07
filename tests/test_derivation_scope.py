"""Adversarial interval and exact accounting-scope checks."""

from dataclasses import replace

import pytest
from test_asof import fact
from test_metric_candidates import report

from finpanel.metrics.derivation import operand_eligibility
from finpanel.metrics.resolver import resolve_candidates


def annual_records(
    *,
    concept="Revenues",
    metric="revenue",
    year=2021,
    start="2021-01-01",
    q1="2021-03-31",
    q2="2021-06-30",
    q3="2021-09-30",
    end="2021-12-31",
    **kwargs,
):
    return tuple(
        fact(
            n=i,
            concept=concept,
            start=start,
            end=stop,
            fy=year,
            fp=label,
            form="10-K" if label == "FY" else "10-Q",
            value=value,
            **kwargs,
        )
        for i, (label, stop, value) in enumerate(
            [("Q1", q1, 100), ("Q2", q2, 250), ("Q3", q3, 420), ("FY", end, 600)], 1
        )
    )


def operands(
    records=None,
    quarter="Q2",
    year=2021,
    metric="revenue",
    cutoff="2024-01-01T00:00:00Z",
    policy="latest_available",
):
    from finpanel.metrics.derivation_models import FORMULAS

    r = report(
        *(records if records is not None else annual_records()), metric=metric, cutoff=cutoff
    )
    formula = FORMULAS[quarter]
    return tuple(
        resolve_candidates(r, fiscal_year=year, period=p, revision_policy=policy)
        for p in (formula.minuend_period, formula.subtrahend_period)
    )


@pytest.mark.parametrize(
    "quarter,start,end",
    [
        ("Q2", "2021-04-01", "2021-06-30"),
        ("Q3", "2021-07-01", "2021-09-30"),
        ("Q4", "2021-10-01", "2021-12-31"),
    ],
)
def test_exact_nested_geometry(quarter, start, end):
    a, b = operands(quarter=quarter)
    r = operand_eligibility(a, b, fiscal_year=2021, quarter=quarter)
    assert r.status == "eligible" and r.target_interval.start.isoformat() == start
    assert r.target_interval.end.isoformat() == end
    assert "original_instance_dimensions_not_proven_equal" in r.diagnostics[0]


@pytest.mark.parametrize(
    "dates,year",
    [
        (("2023-10-01", "2023-12-30", "2024-03-30", "2024-06-29", "2024-09-28"), 2024),
        (("2022-09-25", "2022-12-31", "2023-04-01", "2023-07-01", "2023-09-30"), 2023),
        (("2023-07-01", "2023-09-30", "2023-12-31", "2024-03-31", "2024-06-30"), 2024),
    ],
)
def test_52_53_week_and_leap_geometry(dates, year):
    start, q1, q2, q3, end = dates
    records = annual_records(start=start, q1=q1, q2=q2, q3=q3, end=end, year=year)
    for q in ("Q2", "Q3", "Q4"):
        a, b = operands(records, quarter=q, year=year)
        assert operand_eligibility(a, b, fiscal_year=year, quarter=q).status == "eligible"


def test_cross_concept_rejected_even_canonical_revenue():
    a, _ = operands()
    _, b = operands(annual_records(concept="SalesRevenueNet"))
    assert operand_eligibility(a, b, fiscal_year=2021, quarter="Q2").reasons == (
        "exact_concept_mismatch",
    )


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("unit", "EUR", "unit_mismatch"),
        ("metric", "assets", "unsupported_derived_metric"),
        ("cik", "0000000002", "cik_mismatch"),
        ("revision_policy", "first_reported", "revision_policy_mismatch"),
        ("source_type", "derived", "operands_must_be_reported"),
    ],
)
def test_scope_mutations_rejected(field, value, reason):
    a, b = operands()
    r = operand_eligibility(a, replace(b, **{field: value}), fiscal_year=2021, quarter="Q2")
    assert r.status == "ineligible" and reason in r.reasons


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"fiscal_year": 2020}, "fiscal_year_mismatch"),
        ({"label": "Q3"}, "operand_period_label_mismatch"),
        ({"start": None}, "incomplete_interval"),
    ],
)
def test_period_identity_mutations(change, reason):
    a, b = operands()
    b = replace(b, represented_period=replace(b.represented_period, **change))
    assert reason in operand_eligibility(a, b, fiscal_year=2021, quarter="Q2").reasons


def test_incompatible_start_and_overlap_rejected():
    a, b = operands()
    for change, reason in [
        ({"start": a.represented_period.end}, "fiscal_start_mismatch"),
        ({"end": a.represented_period.end}, "invalid_interval_order"),
    ]:
        mutated = replace(b, represented_period=replace(b.represented_period, **change))
        assert reason in operand_eligibility(a, mutated, fiscal_year=2021, quarter="Q2").reasons


def test_future_calendar_and_unresolved_operands():
    records = annual_records()
    a, b = operands(records, cutoff="2021-12-31T00:00:00Z")
    assert (
        operand_eligibility(a, b, fiscal_year=2021, quarter="Q2").status == "insufficient_evidence"
    )


def test_wrong_namespace_and_retrospective_period_rejected():
    a, b = operands()
    selection = tuple(
        replace(c, mapping=replace(c.mapping, taxonomy="extension")) for c in a.selected
    )
    x = replace(a, selected=selection)
    y = replace(
        b,
        selected=tuple(
            replace(c, mapping=replace(c.mapping, taxonomy="extension")) for c in b.selected
        ),
    )
    assert (
        "unsupported_taxonomy" in operand_eligibility(x, y, fiscal_year=2021, quarter="Q2").reasons
    )
    c = a.selected[0]
    c = replace(
        c,
        observation=replace(
            c.observation, period=replace(c.observation.period, mode="retrospective")
        ),
    )
    assert (
        "period_outside_asof_boundary"
        in operand_eligibility(replace(a, selected=(c,)), b, fiscal_year=2021, quarter="Q2").reasons
    )
