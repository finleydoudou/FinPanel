"""Synthetic parser adversaries, explicitly not authentic filing evidence."""

from dataclasses import replace
from decimal import Decimal

import pytest

from finpanel.errors import ValidationError
from finpanel.models import RawResponse
from finpanel.xbrl.discovery import SourceDocument
from finpanel.xbrl.parser import numeric_metadata, parse_instance

PREFIX = """<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"
 xmlns:us="http://fasb.org/us-gaap/2024" xmlns:iso="http://www.xbrl.org/2003/iso4217"
 xmlns:d="http://xbrl.org/2006/xbrldi" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
"""
CONTEXT = """<xbrli:context id="c"><xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0000320193</xbrli:identifier>{segment}</xbrli:entity><xbrli:period>{period}</xbrli:period>{scenario}</xbrli:context>"""
UNIT = '<xbrli:unit id="u"><xbrli:measure>iso:USD</xbrli:measure></xbrli:unit>'
FACT = (
    '<us:NetIncomeLoss contextRef="c" unitRef="u" decimals="-6">'
    "123456789012345678901234567890</us:NetIncomeLoss>"
)


def instance(
    *,
    segment="",
    scenario="",
    period="<xbrli:instant>2024-03-30</xbrli:instant>",
    facts=FACT,
    extra="",
    body=None,
):
    body = (
        body
        or PREFIX
        + CONTEXT.format(segment=segment, scenario=scenario, period=period)
        + UNIT
        + facts
        + extra
        + "</xbrli:xbrl>"
    )
    raw = RawResponse(
        "https://www.sec.gov/Archives/edgar/data/320193/000032019324000069/source.xml",
        body.encode(),
        "2024-05-04T00:00:00+00:00",
        raw_format="text",
    )
    doc = SourceDocument(
        "0000320193",
        "0000320193-24-000069",
        "10-Q",
        None,
        "source.xml",
        raw.url,
        "instance",
        None,
        None,
        None,
        (),
        raw.sha256,
        raw.retrieved_at,
    )
    return parse_instance(raw, doc)


def test_instant_unit_locator_exact_decimal():
    p = instance()
    c = p.contexts[0]
    f = p.facts[0]
    u = p.units[0]
    assert c.context_id == "c" and c.period_type == "instant"
    assert c.dimension_state == "undimensioned" and not c.dimensions
    assert f.value == Decimal("123456789012345678901234567890")
    assert f.numeric.rounding_quantum == Decimal("1000000")
    assert f.provenance.response_sha256 == p.document.content_sha256
    assert f.provenance.pointer == "/xbrli:xbrl/*[3]"
    assert u.numerator == ("{http://www.xbrl.org/2003/iso4217}USD",)


def test_duration():
    p = instance(
        period=(
            "<xbrli:startDate>2023-10-01</xbrli:startDate><xbrli:endDate>2024-03-30</xbrli:endDate>"
        )
    )
    assert p.contexts[0].period_type == "duration" and not p.contexts[0].diagnostics


def test_dimensions_change_identity():
    segment = (
        '<xbrli:segment><d:explicitMember dimension="us:Axis">us:Member</d:explicitMember>'
        "</xbrli:segment>"
    )
    a = instance(segment=segment).contexts[0]
    b = instance(segment=segment.replace("us:Member", "us:Other")).contexts[0]
    assert a.fingerprint != b.fingerprint and a.scope_fingerprint != b.scope_fingerprint
    assert a.dimension_state == "explicit" and a.segment_xml
    assert instance(segment=segment).contexts[0].fingerprint == a.fingerprint
    assert a.fingerprint != instance().contexts[0].fingerprint


def test_typed_and_other_scope_preserved():
    p = instance(
        scenario=(
            '<xbrli:scenario><d:typedMember dimension="us:Axis">'
            "<us:Domain>abc</us:Domain></d:typedMember><us:Other>keep</us:Other></xbrli:scenario>"
        )
    )
    c = p.contexts[0]
    assert c.dimension_state == "typed" and c.dimensions[0].typed_xml
    assert c.other_scope and c.scenario_xml and c.diagnostics


@pytest.mark.parametrize(
    "decimals,state,quantum",
    [
        ("0", "rounded", "1"),
        ("2", "rounded", "0.01"),
        ("-3", "rounded", "1000"),
        ("INF", "exact", "0"),
        (None, "unspecified", None),
        ("bad", "unsupported_decimals", None),
    ],
)
def test_numeric(decimals, state, quantum):
    p = numeric_metadata(decimals, None)
    assert p.state == state
    assert p.rounding_quantum == (Decimal(quantum) if quantum else None)


def test_precision_nil_unknown_attribute():
    f = instance(
        facts=FACT.replace('decimals="-6"', 'precision="3" xsi:nil="true" custom="preserved"')
    ).facts[0]
    assert f.nil and f.value is None and f.numeric.precision == "3"
    assert ("custom", "preserved") in f.attributes and f.diagnostics


def test_duplicate_id_and_dtd_rejected():
    with pytest.raises(ValidationError):
        instance(extra=UNIT)
    with pytest.raises(ValidationError):
        instance(body='<!DOCTYPE x [<!ENTITY foo "bar">]>' + PREFIX + "</xbrli:xbrl>")
    with pytest.raises(ValidationError):
        instance(body="<html/>")


def test_dates_unsupported_remain_unknown():
    assert instance(period="<xbrli:forever/>").contexts[0].diagnostics
    assert instance(period="<xbrli:instant>bad</xbrli:instant>").contexts[0].diagnostics


def test_unit_divide_and_unresolved_qname():
    p = instance(
        body=PREFIX
        + UNIT.replace(
            "<xbrli:measure>iso:USD</xbrli:measure>",
            (
                "<xbrli:divide><xbrli:unitNumerator><xbrli:measure>iso:USD</xbrli:measure>"
                "</xbrli:unitNumerator><xbrli:unitDenominator><xbrli:measure>xbrli:shares</xbrli:measure></xbrli:unitDenominator></xbrli:divide>"
            ),
        )
        + "</xbrli:xbrl>"
    )
    assert p.units[0].denominator == ("{http://www.xbrl.org/2003/instance}shares",)
    assert (
        instance(body=PREFIX + UNIT.replace("iso:USD", "missing:USD") + "</xbrli:xbrl>")
        .units[0]
        .diagnostics
    )


def test_hash_identity():
    raw = RawResponse("x", b"<x/>", "2026-01-01", raw_format="text")
    doc = replace(instance().document, url="x")
    with pytest.raises(ValidationError):
        parse_instance(raw, doc)


def test_context_id_is_separate_from_canonical_identity():
    from dataclasses import replace

    a = instance()
    # Build a different original context ID, while preserving entity/period/scope.
    from finpanel.models import RawResponse

    text = (
        PREFIX
        + CONTEXT.format(
            segment="", scenario="", period="<xbrli:instant>2024-03-30</xbrli:instant>"
        ).replace('id="c"', 'id="renamed"')
        + UNIT
        + "</xbrli:xbrl>"
    )
    raw = RawResponse(a.document.url, text.encode(), a.document.retrieved_at, raw_format="text")
    b = parse_instance(raw, replace(a.document, content_sha256=raw.sha256))
    assert a.contexts[0].context_id != b.contexts[0].context_id
    assert a.contexts[0].fingerprint == b.contexts[0].fingerprint


def test_duplicate_dimension_and_unknown_unit_attributes():
    segment = (
        "<xbrli:segment>"
        + 2 * '<d:explicitMember dimension="us:Axis">us:Member</d:explicitMember>'
        + "</xbrli:segment>"
    )
    assert "duplicate_dimension_axis" in instance(segment=segment).contexts[0].diagnostics
    p = instance(body=PREFIX + UNIT.replace('id="u"', 'id="u" extra="retained"') + "</xbrli:xbrl>")
    assert p.units[0].diagnostics and "extra=" in p.units[0].raw_xml


def test_exact_decimal_fraction_and_invalid_number():
    f = instance(
        facts=FACT.replace("123456789012345678901234567890", "0.12345678901234567890123456789")
    ).facts[0]
    assert str(f.value) == "0.12345678901234567890123456789"
    for value in ("NaN", "INF", "1e4", "bad"):
        f = instance(facts=FACT.replace("123456789012345678901234567890", value)).facts[0]
        assert f.value is None and f.diagnostics


@pytest.mark.parametrize(
    "precision,state",
    [
        ("3", "precision_preserved_not_interpreted"),
        ("INF", "precision_preserved_not_interpreted"),
        ("0", "unsupported_precision"),
        ("nonsense", "unsupported_precision"),
    ],
)
def test_precision_validation(precision, state):
    assert numeric_metadata(None, precision).state == state


def test_invalid_nil_is_not_silently_false():
    f = instance(facts=FACT.replace('decimals="-6"', 'xsi:nil="invalid"')).facts[0]
    assert "unsupported_nil_attribute" in f.diagnostics
