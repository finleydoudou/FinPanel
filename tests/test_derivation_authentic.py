"""Literal authentic source evidence, exact identities, and explicit synthetic guard goldens."""

import runpy
from dataclasses import replace
from pathlib import Path

import pytest
from test_asof import fact
from test_derivation_revisions import derive
from test_derivation_scope import annual_records

from finpanel import metrics
from finpanel.cache import FileCache
from finpanel.models import RawResponse
from finpanel.sec.client import SECClient
from finpanel.serialization import dumps, loads

ROOT = Path(__file__).resolve().parents[1]
MODULE = runpy.run_path(str(ROOT / "examples" / "validate_derived_quarters.py"))
GOLDEN = loads((ROOT / "tests" / "golden" / "derived_quarters.json").read_bytes())


@pytest.fixture(scope="module")
def suite(tmp_path_factory):
    return MODULE["DerivedValidation"](tmp_path_factory.mktemp("derived-golden"))


@pytest.mark.parametrize("case", GOLDEN["authentic_cases"], ids=lambda c: c["id"])
def test_authentic_derivation_golden(suite, case):
    result, report = suite.run_derived(case)
    assert suite.check_derived(case, result, report) == []
    if result.value is not None:
        assert result.minuend.as_of == result.subtrahend.as_of == result.as_of
        assert (
            result.minuend.revision_policy
            == result.subtrahend.revision_policy
            == result.revision_policy
        )
        assert result.availability.selected_evidence_ready_at <= result.as_of
        assert all(
            e.eligible_as_of and e.as_of == result.as_of for e in result.availability.evidence
        )


@pytest.mark.parametrize("case", GOLDEN["synthetic_guards"], ids=lambda c: c["id"])
def test_separately_labeled_synthetic_guard_golden(case):
    result = MODULE["synthetic_guard"](case["id"])
    assert result.status == case["expected_status"] and case["expected_reason"] in result.reasons
    assert result.value is None


def test_authentic_future_values_and_filings_cannot_change_earlier_derivation(suite, tmp_path):
    case = GOLDEN["authentic_cases"][2]  # Apple FY2024 Q4 residual.
    baseline, _ = suite.run_derived(case)
    data = loads(dumps(suite.raw["aapl_companyfacts.json"]))
    concept = "RevenueFromContractWithCustomerExcludingAssessedTax"
    rows = data["facts"]["us-gaap"][concept]["units"]["USD"]
    changed = 0
    for row in rows:
        if row["filed"] > "2024-11-15":
            row["val"] = -999999999999
            row["start"], row["end"] = "2023-10-02", "2024-09-28"
            changed += 1
    assert changed
    # Also duplicate a future annual filing and attach a conflicting future anchor.
    timeline = suite.timelines["aapl"]
    future = next(f for f in timeline if f.form == "10-K" and f.filing_date.year == 2025)
    future = replace(future, accession_number="0000320193-25-999999")
    timeline = replace(timeline, records=(*timeline.records, future))
    row = dict(
        rows[-1],
        accn=future.accession_number,
        filed=future.filing_date.isoformat(),
        start="2023-10-02",
        end="2024-09-28",
        val=123,
        fy=2024,
        fp="FY",
        form="10-K",
    )
    rows.append(row)
    cache = FileCache(tmp_path)
    meta = suite.manifest["aapl_companyfacts.json"]
    cache.put(RawResponse(meta["source_url"], dumps(data).encode(), meta["retrieved_at"]))
    with SECClient(cache=cache, offline=True) as client:
        altered = metrics.derive_quarter(
            baseline.cik,
            "revenue",
            fiscal_year=2024,
            quarter="Q4",
            as_of=case["as_of"],
            client=client,
            filing_timeline=timeline,
        )
    assert (altered.status, altered.value, altered.target_interval) == (
        baseline.status,
        baseline.value,
        baseline.target_interval,
    )
    assert (
        altered.availability.selected_evidence_ready_at
        == baseline.availability.selected_evidence_ready_at
    )


@pytest.mark.parametrize("mutation", ["unit", "interval"])
def test_actual_source_observation_mutation_rejects_derivation(mutation):
    records = list(annual_records())
    extra = {"unit": "EUR"} if mutation == "unit" else {"start": "2021-01-02"}
    records[1] = fact(
        n=2, concept="Revenues", end="2021-06-30", fy=2021, fp="Q2", form="10-Q", value=250, **extra
    )
    result = derive(tuple(records))
    assert result.status != "eligible" and result.value is None


def test_readiness_waits_for_later_calendar_anchor():
    quarters = tuple(
        fact(
            n=i,
            concept="Revenues",
            end=end,
            fp=fp,
            form="10-Q",
            value=value,
            filed="2021-11-01",
            accepted="2021-11-01T15:00:00Z",
        )
        for i, (end, fp, value) in enumerate(
            [("2021-03-31", "Q1", 100), ("2021-06-30", "Q2", 250), ("2021-09-30", "Q3", 420)], 1
        )
    )
    annual = annual_records()[-1]
    assert derive((*quarters, annual), cutoff="2021-12-01T00:00:00Z").value is None
    result = derive((*quarters, annual), cutoff="2022-02-01T15:00:00Z")
    assert result.value == 150
    assert result.availability.selected_evidence_ready_at == result.as_of
    assert result.minuend.selected[0].observation.fact.availability.timestamp < result.as_of
