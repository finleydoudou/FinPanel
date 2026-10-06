"""Metric contracts operate only after the historical evidence boundary."""

from dataclasses import replace

import pytest
from test_asof import fact, inspection

from finpanel.errors import ValidationError
from finpanel.metrics.engine import from_inspections
from finpanel.metrics.registry import REGISTRY
from finpanel.models.timeline import Availability


def report(*records, metric="revenue", cutoff="2024-01-01T00:00:00Z"):
    names = {m.concept for m in REGISTRY[metric].mappings}
    names |= {r.observation.concept for r in records}
    inspections = tuple(
        replace(inspection(*(r for r in records if r.observation.concept == n)), concept=n)
        for n in sorted(names)
    )
    return from_inspections(1, metric, as_of=cutoff, inspections=inspections)


def revenue(**kwargs):
    return fact(concept="Revenues", **kwargs)


def test_all_candidates_retained_with_provenance_and_revisions():
    a, b = revenue(), revenue(n=2, value=101, accepted="2023-02-01T15:00:00Z")
    r = report(a, b)
    assert len(r.records) == 2 and len(r.revision_groups) == 1
    assert r.revision_groups[0].status == "conflicted"
    for c in r.records:
        assert c.observation.period.mode == "as_of"
        assert c.observation.supporting_evidence and c.observation.fact.observation.provenance
        assert c.observation.eligibility.eligible_as_of


@pytest.mark.parametrize(
    "kwargs,reason",
    [
        ({"start": "absent"}, "wrong_context_type"),
        ({"unit": "shares"}, "incompatible_unit"),
        ({"unit": "EUR"}, "incompatible_unit"),
        ({"taxonomy": "my-company"}, "wrong_taxonomy"),
        ({"concept": "MyRevenue"}, "unsupported_concept"),
        ({"form": "8-K"}, "ambiguous_period"),
        ({"end": "2021-01-20"}, "unsupported_period"),
        ({"accepted": "2025-01-01T00:00:00Z"}, "unavailable_as_of"),
        ({"accepted": None, "filed": None}, "unknown_availability"),
    ],
)
def test_explicit_rejections(kwargs, reason):
    args = {"concept": "Revenues", **kwargs}
    r = report(fact(**args))
    assert not r.records and reason in r.rejected[0].reasons
    assert r.rejected[0].fact.observation.provenance


def test_assets_require_instant():
    assert report(fact(concept="Assets", start="absent"), metric="assets").records
    assert not report(fact(concept="Assets"), metric="assets").records


def test_future_annual_anchor_never_repairs_earlier_quarter():
    q = revenue(end="2021-03-31", fp="Q1", form="10-Q", accepted="2021-05-01T12:00:00Z")
    annual = revenue(n=2)
    a = report(q, cutoff="2021-06-01T00:00:00Z")
    b = report(q, annual, cutoff="2021-06-01T00:00:00Z")
    assert not a.records and not b.records
    assert a.evidence[0].calendar == b.evidence[0].calendar
    assert any("ambiguous_period" in r.reasons for r in b.rejected)


def test_fact_availability_cannot_inherit_filing_availability():
    a = replace(revenue(), availability=Availability("unknown"))
    assert "unknown_availability" in report(a).rejected[0].reasons


def test_incomplete_concept_coverage_rejected():
    with pytest.raises(ValidationError, match="every mapped concept"):
        from_inspections(1, "revenue", as_of="2024-01-01T00:00:00Z", inspections=())


def test_wrong_issuer_and_concept_rejected():
    i = replace(inspection(revenue()), cik="0000000002", concept="Assets")
    with pytest.raises(ValidationError, match="mismatch"):
        from_inspections(1, "assets", as_of="2024-01-01T00:00:00Z", inspections=(i,))


def test_unsupported_extension_cannot_supply_calendar_anchor():
    q = revenue(end="2021-03-31", fp="Q1", form="10-Q")
    extension = revenue(n=2, taxonomy="custom")
    r = report(q, extension)
    assert not r.records
    assert any("ambiguous_period" in x.reasons for x in r.rejected)
