"""Literal goldens audited against frozen SEC bytes, with live HTTP forbidden."""

import runpy
from pathlib import Path

import pytest

from finpanel import metrics
from finpanel.models import RawResponse
from finpanel.sec.client import SECClient
from finpanel.serialization import dumps, loads

ROOT = Path(__file__).resolve().parents[1]
MODULE = runpy.run_path(str(ROOT / "examples" / "validate_canonical.py"))
CASES = loads((ROOT / "tests" / "golden" / "canonical.json").read_bytes())["cases"]


@pytest.fixture(scope="module")
def suite(tmp_path_factory):
    return MODULE["FrozenValidation"](tmp_path_factory.mktemp("canonical-golden"))


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_authentic_golden(suite, case):
    result = suite.run_case(case)
    assert suite.check(case, result) == []
    assert all(v.mode == "as_of" for v in result.candidates.evidence)
    if result.state == "resolved":
        assert all(c.observation.eligibility.eligible_as_of for c in result.selected)
        assert all(
            e.eligible_as_of and e.as_of == result.as_of
            for c in result.selected
            for e in c.observation.supporting_evidence
        )


def test_catalog_observed_in_authentic_sources(suite):
    for metric in metrics.REGISTRY.values():
        for mapping in metric.mappings:
            assert any(
                mapping.concept in suite.raw[f"{issuer}_companyfacts.json"]["facts"]["us-gaap"]
                for issuer in ("aapl", "msft", "wmt", "nvda")
            )


def test_authentic_future_snapshot_mutation_cannot_change_past_result(suite, tmp_path):
    from finpanel.cache import FileCache

    case = CASES[0]
    baseline = suite.run_case(case)
    data = loads(dumps(suite.raw["aapl_companyfacts.json"]))
    concept = "RevenueFromContractWithCustomerExcludingAssessedTax"
    records = data["facts"]["us-gaap"][concept]["units"]["USD"]
    changed = 0
    for row in records:
        if row["filed"] > "2024-11-15":
            row["val"] = -999999999999
            row["start"], row["end"] = "2023-10-01", "2024-09-27"
            changed += 1
    assert changed > 0
    cache = FileCache(tmp_path)
    meta = suite.manifest["aapl_companyfacts.json"]
    cache.put(RawResponse(meta["source_url"], dumps(data).encode(), meta["retrieved_at"]))
    with SECClient(cache=cache, offline=True) as client:
        altered = metrics.resolve(
            baseline.cik,
            "revenue",
            as_of=case["as_of"],
            **case["query"],
            client=client,
            filing_timeline=suite.timelines["aapl"],
        )
    assert (altered.state, altered.value, altered.unit, altered.represented_period) == (
        baseline.state,
        baseline.value,
        baseline.unit,
        baseline.represented_period,
    )
    assert [
        (c.mapping.concept, c.observation.fact.observation.accession_number)
        for c in altered.selected
    ] == [
        (c.mapping.concept, c.observation.fact.observation.accession_number)
        for c in baseline.selected
    ]
    assert altered.selected[0].observation.fact.observation.provenance.response_sha256 != (
        baseline.selected[0].observation.fact.observation.provenance.response_sha256
    )


def test_unmapped_inventory_has_raw_pointers(suite):
    r = suite.run_case(CASES[0]).candidates
    assert r.unmapped_concepts
    for item in r.unmapped_concepts:
        assert item.source.pointer.startswith("/facts/") and item.count > 0
        assert metrics.mapping_for("revenue", item.taxonomy, item.concept) is None
