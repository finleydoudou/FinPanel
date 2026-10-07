"""Authentic bytes and manually transcribed goldens; all HTTP is forbidden."""

import runpy
from dataclasses import replace
from pathlib import Path

import pytest

from finpanel import metrics, xbrl
from finpanel.cache import FileCache
from finpanel.serialization import loads
from finpanel.xbrl.parser import parse_instance

ROOT = Path(__file__).resolve().parents[1]
MODULE = runpy.run_path(str(ROOT / "examples/validate_xbrl.py"))
CASES = loads((ROOT / "tests/golden/xbrl_evidence.json").read_bytes())["cases"]


@pytest.fixture(scope="module")
def suite(tmp_path_factory):
    s = MODULE["EvidenceValidation"](FileCache(tmp_path_factory.mktemp("xbrl")))
    yield s
    s.client.close()


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_authentic_golden(suite, case):
    v, errors = suite.run_case(case)
    assert errors == []
    assert all(d.fact.provenance.response_sha256 for d in v.matches)


def test_authentic_raw_hashes(suite):
    manifest = loads((ROOT / "tests/fixtures/xbrl/manifest.json").read_bytes())
    assert len(manifest["files"]) == 15
    for meta in manifest["files"].values():
        raw = suite.client.cache.get(meta["source_url"])
        assert raw.sha256 == meta["sha256"] and len(raw.body) == meta["bytes"]
        assert meta["raw_unmodified"] and meta["retrieved_at"]


def test_explicit_authentic_dimension(suite):
    instance = suite.instances["0000320193-24-000069"][0]
    c = next(c for c in instance.contexts if c.context_id == "c-44")
    assert c.dimension_state == "explicit"
    assert c.dimensions[0].axis == "{http://fasb.org/us-gaap/2023}StatementEquityComponentsAxis"
    assert c.dimensions[0].member == "{http://fasb.org/us-gaap/2023}RetainedEarningsMember"


@pytest.mark.parametrize("mutation", ["date", "concept", "unit", "dimension"])
def test_authentic_byte_mutations(suite, mutation):
    case = CASES[5]
    v, _ = suite.run_case(case)
    p = v.instances[0]
    raw = suite.client.cache.get(p.document.url)
    body = raw.body
    if mutation == "date":
        body = body.replace(b"2024-03-30", b"2024-03-29")
    if mutation == "concept":
        body = body.replace(b"NetCashProvidedByUsedInOperatingActivities", b"InventedConcept")
    if mutation == "unit":
        body = body.replace(b"iso4217:USD", b"iso4217:EUR")
    if mutation == "dimension":
        # Deliberate synthetic mutation of authentic bytes. Never saved as authentic.
        start = body.index(b'<context id="c-1">')
        end = body.index(b"</entity>", start)
        segment = (
            b'<segment><xbrldi:explicitMember dimension="us-gaap:StatementEquityComponentsAxis">'
            b"us-gaap:RetainedEarningsMember</xbrldi:explicitMember></segment>"
        )
        body = body[:end] + segment + body[end:]
    assert body != raw.body
    changed = replace(raw, body=body)
    altered = parse_instance(changed, replace(p.document, content_sha256=changed.sha256))
    result = xbrl.verify_fact(v.observation, instances=(altered,), as_of=MODULE["CUTOFF"])
    if mutation == "dimension":
        assert result.scope_state == "dimensioned"
    else:
        assert result.state == "source_mismatch"


def test_authentic_future_original_source_exclusion(suite):
    case = CASES[1]
    v, _ = suite.run_case(case)
    p = v.instances[0]
    p = replace(p, document=replace(p.document, retrieved_at="2099-01-01T00:00:00Z"))
    assert xbrl.verify_fact(
        v.observation, instances=(p,), as_of=MODULE["CUTOFF"]
    ) == xbrl.verify_fact(v.observation, as_of=MODULE["CUTOFF"])


def test_authentic_derived_operand_scopes(suite, tmp_path):
    legacy = runpy.run_path(str(ROOT / "examples/validate_canonical.py"))["FrozenValidation"](
        tmp_path
    )
    legacy.run_case(
        {
            "issuer": "aapl",
            "metric": "operating_cash_flow",
            "as_of": MODULE["CUTOFF"],
            "query": {"fiscal_year": 2024, "period": "FY"},
        }
    )
    report = legacy.reports[("aapl", "operating_cash_flow", MODULE["CUTOFF"])]
    d = metrics.derive_from_candidates(
        report, fiscal_year=2024, quarter="Q2", revision_policy="first_reported"
    )
    instances = tuple(p for values in suite.instances.values() for p in values)
    enriched = xbrl.verify_derivation(d, instances=instances, source_verification="required")
    assert d.value == 22690000000 and enriched.value == d.value
    assert enriched.scope_state == "same_scope_compatible" and enriched.state == "eligible"
    assert enriched.minuend.selected[0].matches[0].context.context_id == "c-1"
    assert enriched.subtrahend.selected[0].matches[0].context.context_id == "c-1"
