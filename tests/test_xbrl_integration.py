"""Additive verification never reselects canonical winners or modifies source scalars."""

from dataclasses import replace

import pytest
from test_derivation_scope import annual_records
from test_metric_candidates import report
from test_xbrl_parser import CONTEXT, FACT, instance

from finpanel import metrics, xbrl
from finpanel.errors import ValidationError


def source_for(candidate, *, member=None):
    obs = candidate.observation.fact.observation
    period = (
        f"<xbrli:startDate>{obs.period_start}</xbrli:startDate>"
        f"<xbrli:endDate>{obs.period_end}</xbrli:endDate>"
    )
    segment = (
        ""
        if member is None
        else '<xbrli:segment><d:explicitMember dimension="us:Axis">us:'
        + member
        + "</d:explicitMember></xbrli:segment>"
    )
    fact = FACT.replace("NetIncomeLoss", obs.concept).replace(
        "123456789012345678901234567890", str(obs.value)
    )
    from test_xbrl_parser import PREFIX, UNIT

    text = (
        PREFIX
        + CONTEXT.format(segment=segment, scenario="", period=period).replace("0000320193", obs.cik)
        + UNIT
        + fact
        + "</xbrli:xbrl>"
    )
    p = instance(body=text)
    return replace(
        p,
        document=replace(
            p.document,
            cik=obs.cik,
            accession=obs.accession_number,
            filing_date=obs.filing_date,
            retrieved_at="2021-01-01T00:00:00Z",
        ),
    )


def derivation():
    return metrics.derive_from_candidates(report(*annual_records()), fiscal_year=2021, quarter="Q2")


def test_best_effort_keeps_default_and_required_rejects_missing():
    result = derivation()
    best = xbrl.verify_derivation(result)
    strict = xbrl.verify_derivation(result, source_verification="required")
    assert best.value == result.value == 150 and best.original is result
    assert best.scope_state == "original_context_unknown"
    assert strict.value is None and strict.state == "source_verification_rejected"
    metric = xbrl.verify_metric(result.minuend, source_verification="required")
    assert metric.value is None and metric.original.value == 250


def test_strict_verified_scope_and_provenance():
    d = derivation()
    sources = tuple(source_for(c) for r in (d.minuend, d.subtrahend) for c in r.selected)
    v = xbrl.verify_derivation(d, instances=sources, source_verification="required")
    assert v.state == "eligible" and v.value == 150 and v.scope_state == "same_scope_compatible"
    assert v.minuend.selected[0].matches[0].fact.provenance
    assert v.original.availability == d.availability


def test_dimension_mutation_breaks_strict_compatibility():
    d = derivation()
    sources = (
        source_for(d.minuend.selected[0]),
        source_for(d.subtrahend.selected[0], member="Geography"),
    )
    v = xbrl.verify_derivation(d, instances=sources, source_verification="required")
    assert v.state == "source_verification_rejected" and v.value is None
    assert v.scope_state == "scope_different"
    assert d.value == 150


def test_same_dimensioned_scope_is_not_companywide_arithmetic():
    d = derivation()
    sources = tuple(
        source_for(c, member="SameSegment") for r in (d.minuend, d.subtrahend) for c in r.selected
    )
    v = xbrl.verify_derivation(d, instances=sources, source_verification="required")
    assert v.value is None and "dimensioned_arithmetic_not_supported" in v.diagnostics


def test_revision_winners_unchanged():
    r = derivation().minuend
    enriched = xbrl.revision_evidence(r)
    assert enriched
    for e, g in zip(enriched, r.revision_groups, strict=True):
        assert e.selected_observation_ids == g.selected_observation_ids
        assert e.original_group is g and e.scope_state == "original_context_unknown"


def test_future_source_does_not_strengthen_metric():
    r = derivation().minuend
    p = source_for(r.selected[0])
    p = replace(p, document=replace(p.document, retrieved_at="2099-01-01T00:00:00Z"))
    assert xbrl.verify_metric(r, instances=(p,)) == xbrl.verify_metric(r)


def test_invalid_mode():
    with pytest.raises(ValidationError):
        xbrl.verify_derivation(derivation(), source_verification="assume")
