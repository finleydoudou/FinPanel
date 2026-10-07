"""Synthetic exact matching and temporal mutation acceptance tests."""

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest
from test_xbrl_parser import CONTEXT, FACT, instance

from finpanel.models import FactObservation, Provenance
from finpanel.xbrl import context_for_fact, verify_fact


def observation(**overrides):
    f = FactObservation(
        "0000320193",
        "Apple",
        "us-gaap",
        "NetIncomeLoss",
        None,
        None,
        "USD",
        Decimal("123456789012345678901234567890"),
        "0000320193-24-000069",
        "10-Q",
        date(2024, 5, 3),
        None,
        2024,
        "Q2",
        None,
        date(2024, 3, 30),
        None,
        Provenance("synthetic", "a" * 64, "/observation"),
        {},
    )
    return replace(f, **overrides)


def evidence(**kwargs):
    p = instance(**kwargs)
    return replace(p, document=replace(p.document, filing_date=date(2024, 5, 3)))


def verify(p=None, obs=None, cutoff="2024-05-05T00:00:00Z"):
    return verify_fact(obs or observation(), instances=(p or evidence(),), as_of=cutoff)


def test_unique_and_source_locator():
    v = verify()
    assert v.state == "verified_unique" and v.scope_state == "verified_undimensioned"
    assert v.period_state == "consistent" and context_for_fact(v)[0].context_id == "c"
    assert v.matches[0].fact.numeric.decimals == "-6"


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("concept", "Assets", None),
        ("taxonomy", "invented", "taxonomy_mismatch"),
        ("unit", "EUR", "unit_mismatch"),
        ("period_end", date(2024, 3, 31), "period_mismatch"),
        ("value", Decimal(1), "value_mismatch"),
    ],
)
def test_mismatch_not_value_only(field, value, reason):
    v = verify(obs=observation(**{field: value}))
    assert v.state == "source_mismatch"
    if reason:
        assert reason in v.decisions[0].reasons


def test_duplicate_equivalent_retains_all():
    v = verify(evidence(facts=FACT + FACT))
    assert v.state == "verified_multiple_equivalent" and len(v.matches) == 2
    assert len({d.fact.provenance.pointer for d in v.matches}) == 2


def test_equal_values_different_contexts_do_not_collapse():
    context = CONTEXT.format(
        segment=(
            '<xbrli:segment><d:explicitMember dimension="us:Axis">us:Member</d:explicitMember>'
            "</xbrli:segment>"
        ),
        scenario="",
        period="<xbrli:instant>2024-03-30</xbrli:instant>",
    ).replace('id="c"', 'id="other"')
    v = verify(
        evidence(facts=FACT + FACT.replace('contextRef="c"', 'contextRef="other"'), extra=context)
    )
    assert v.state == "ambiguous_match" and v.scope_state == "scope_conflict"
    assert len(context_for_fact(v)) == 2


def test_dimensioned_is_not_company_wide():
    v = verify(
        evidence(
            segment=(
                '<xbrli:segment><d:explicitMember dimension="us:Axis">us:Member</d:explicitMember>'
                "</xbrli:segment>"
            )
        )
    )
    assert v.state == "verified_unique" and v.scope_state == "dimensioned"


def test_precision_never_changes_scalar_or_equivalence():
    v = verify(evidence(facts=FACT + FACT.replace('decimals="-6"', 'decimals="0"')))
    assert v.state == "ambiguous_match"
    assert all(d.fact.value == observation().value for d in v.matches)


def test_future_filing_and_source_excluded():
    old = verify(cutoff="2024-05-01T00:00:00Z")
    assert old.state == "instance_unavailable"
    p = evidence()
    future = replace(p, document=replace(p.document, retrieved_at="2025-01-01T00:00:00Z"))
    absent = verify_fact(observation(), as_of="2024-06-01T00:00:00Z")
    assert verify(future, cutoff="2024-06-01T00:00:00Z") == absent
    mutated = replace(future, facts=())
    assert verify(mutated, cutoff="2024-06-01T00:00:00Z") == absent


def test_unrelated_later_filing_cannot_change_result():
    p = evidence()
    later = replace(p, document=replace(p.document, accession="0000320193-25-000001"))
    assert verify_fact(observation(), instances=(p, later), as_of="2024-05-05T00:00:00Z") == verify(
        p
    )


def test_no_instance_and_nil():
    assert verify_fact(observation(), as_of="2024-05-05T00:00:00Z").state == "instance_unavailable"
    assert (
        verify(evidence(facts=FACT.replace('decimals="-6"', 'xsi:nil="true"'))).state
        == "source_mismatch"
    )


def test_unsupported_alternative_blocks_unique_success():
    v = verify(evidence(facts=FACT + FACT.replace('decimals="-6"', 'decimals="broken"')))
    assert v.state == "ambiguous_match"
    assert len(v.decisions) == 2 and len(v.matches) == 1


def test_future_companyfacts_filing_is_not_verified():
    v = verify(obs=observation(filing_date=date(2099, 1, 1)))
    assert v.state == "instance_unavailable"


def test_contradicting_filing_identity_rejected():
    v = verify(obs=observation(form="10-K"))
    assert v.state == "source_mismatch"
    assert "filing_form_mismatch" in v.decisions[0].reasons


def test_future_discovery_metadata_cannot_strengthen_verification():
    p = evidence()
    p = replace(p, document=replace(p.document, discovery_retrieved_at=("2099-01-01T00:00:00Z",)))
    assert verify(p) == verify_fact(observation(), as_of="2024-05-05T00:00:00Z")
