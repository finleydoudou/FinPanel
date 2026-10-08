"""Independent frozen SEC edge cases; no live access and no generated expectations."""

from datetime import date
from pathlib import Path

import pytest

from finpanel.serialization import loads
from finpanel.snapshots import EvidenceStore
from finpanel.validation.fixtures import import_fixtures
from finpanel.validation.historical import bounded_view, calendar_diagnostics

ROOT = Path(__file__).parent
CASES = loads((ROOT / "golden/release-calendar.json").read_bytes())["cases"]


@pytest.fixture(scope="module")
def historical(tmp_path_factory):
    result = {}
    for name in ("release", "broad"):
        store = EvidenceStore(tmp_path_factory.mktemp(name))
        snapshot = import_fixtures(ROOT / "fixtures" / name, store)
        result[name] = store, snapshot
    return result


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_calendar_golden(historical, case):
    store, snapshot = historical[case["fixture"]]
    artifact = next(
        a for a in snapshot.manifest["artifacts"] if a["sha256"] == case["source_sha256"]
    )
    raw = store.raw(store._artifact(artifact)).json()
    for part in case["pointer"].split("/")[1:]:
        raw = raw[int(part)] if isinstance(raw, list) else raw[part]
    assert raw == case["literal"]
    view = bounded_view(store, snapshot.snapshot_id, case["cik"], case["concept"], case["cutoff"])
    rows = [r for r in view.records if r.fact.observation.provenance.pointer == case["pointer"]]
    expected = case["expected"]
    if expected.get("absent"):
        assert not rows
        assert any(
            r.fact.observation.provenance.pointer == case["pointer"]
            for r in view.excluded_observations
        )
        return
    assert len(rows) == 1
    period = rows[0].period
    assert (date.fromisoformat(raw["end"]) - date.fromisoformat(raw["start"])).days + 1 == expected[
        "days"
    ]
    assert period.duration_days == expected["days"]
    assert period.kind == expected["kind"]
    assert period.identity.fiscal_year == expected["year"]
    assert period.identity.label == expected["label"]
    assert view.calendar.current_year_end_hints == ()
    assert all(e.eligible_as_of and e.as_of == view.as_of for e in rows[0].supporting_evidence)


def test_transition_diagnostics_do_not_assign_year(historical):
    store, snapshot = historical["release"]
    view = bounded_view(
        store, snapshot.snapshot_id, "12659", "NetIncomeLoss", "2022-08-17T12:00:00Z"
    )
    findings = calendar_diagnostics(view)
    transitions = [f for f in findings if "explicit_transition_filing" in f["codes"]]
    assert transitions
    short = [f for f in transitions if f["duration_days"] == 61]
    assert short and all(f["fiscal_label"] is None for f in short)
    assert all("shortened_transition_period" in f["codes"] for f in short)
    assert any("observed_fiscal_boundary_movement" in f["codes"] for f in findings)


def test_current_metadata_is_a_separate_retrospective_annotation(historical):
    from finpanel.serialization import dumps
    from finpanel.validation.historical import current_fye_comparison

    store, snapshot = historical["release"]
    view = bounded_view(
        store, snapshot.snapshot_id, "12659", "NetIncomeLoss", "2021-06-16T12:00:00Z"
    )
    before = dumps(view)
    source = next(
        a
        for a in snapshot.manifest["artifacts"]
        if a["cik"] == "0000012659" and a["source_family"] == "submissions"
    )
    report = current_fye_comparison(
        view,
        "0630",
        dict(
            source_url=source["source_url"],
            response_sha256=source["sha256"],
            pointer="/fiscalYearEnd",
        ),
    )
    assert not report["eligible_historical_anchor"]
    assert any(w["end"].isoformat() == "2021-04-30" for w in report["mismatched_observed_windows"])
    current_fye_comparison(view, "1231", report["source"])
    assert dumps(view) == before


def test_authentic_future_calendar_mutation_cannot_strengthen_history(historical):
    from dataclasses import replace

    from finpanel import asof, facts
    from finpanel.sec.client import SECClient
    from finpanel.serialization import dumps
    from finpanel.snapshots.pipeline import _PinnedCache

    store, snapshot = historical["release"]
    with SECClient(cache=_PinnedCache(store, snapshot), offline=True) as client:
        inspection = facts.for_concept("12659", "NetIncomeLoss", taxonomy="us-gaap", client=client)
    cutoff = "2021-11-05T12:00:00Z"
    original = asof.from_inspection(inspection, cutoff)
    # Mutated data is explicitly synthetic, never saved as authentic SEC evidence.
    poisoned = replace(
        inspection,
        records=tuple(
            replace(r, observation=replace(r.observation, value=999999999, fiscal_year=1900))
            if r.observation.filing_date and r.observation.filing_date.year >= 2022
            else r
            for r in inspection.records
        ),
    )
    altered = asof.from_inspection(poisoned, cutoff)
    assert dumps(original.records) == dumps(altered.records)
    assert dumps(original.calendar) == dumps(altered.calendar)


REVISION_CASES = loads((ROOT / "golden/release-revisions.json").read_bytes())["cases"]


@pytest.mark.parametrize("case", REVISION_CASES, ids=lambda c: c["id"])
def test_revision_golden(historical, case):
    from finpanel import revisions

    store, snapshot = historical["release"]
    artifact = next(a for a in snapshot.manifest["artifacts"] if a["sha256"] == case["sha256"])
    raw = store.raw(store._artifact(artifact)).json()
    for source in case["sources"]:
        value = raw
        for part in source["pointer"].split("/")[1:]:
            value = value[int(part)] if isinstance(value, list) else value[part]
        assert value == source["literal"]
    view = bounded_view(store, snapshot.snapshot_id, case["cik"], case["concept"], case["as_of"])
    result = revisions.analyze(view, policy=case["policy"])
    group = next(
        g
        for g in result.groups
        if g.identity["start"].isoformat() == case["start"]
        and g.identity["end"].isoformat() == case["end"]
    )
    assert group.status == case["expected_status"], group.conflicts
    selected = [
        c.observation.fact.observation.value
        for c in group.candidates
        if c.observation.fact.observation_id in group.selected_observation_ids
    ]
    if case["expected_value"] is None:
        assert selected == []
        assert "incompatible_candidate_values" in group.conflicts
    else:
        assert selected == [case["expected_value"]]
    assert all(c.observation.eligibility.eligible_as_of for c in group.candidates)


def test_original_narratives_support_only_the_declared_claims(historical):
    from html.parser import HTMLParser

    class Text(HTMLParser):
        def __init__(self):
            super().__init__()
            self.parts = []

        def handle_data(self, data):
            self.parts.append(data)

    store, snapshot = historical["release"]
    claims = {
        "0000012659": (
            "1edcd3bade4414af942ad3f233b78d1e8077ddddfb84d1dd999e8143666957e6",
            "For the transition period from May 1, 2021 to June 30, 2021",
        ),
        "0000063276": (
            "39effbac53b74031dfc3ba7a1f51aa824731f999c08930b35dc4190fc895fdc0",
            "The purpose of this Amendment is to restate",
        ),
    }
    for cik, (sha, excerpt) in claims.items():
        artifact = next(a for a in snapshot.manifest["artifacts"] if a["sha256"] == sha)
        assert artifact["cik"] == cik and artifact["authenticity"] == "authentic"
        parser = Text()
        parser.feed(store.raw(store._artifact(artifact)).body.decode())
        assert excerpt in " ".join(" ".join(parser.parts).split())


def test_revision_vocabulary_does_not_claim_accounting_causality(historical):
    from finpanel.validation.historical import revision_observations

    store, snapshot = historical["release"]
    view = bounded_view(
        store, snapshot.snapshot_id, "1637459", "NetIncomeLoss", "2019-06-08T12:00:00Z"
    )
    findings = revision_observations(view)
    categories = {c for f in findings for c in f["categories"]}
    assert {
        "amendment_filing",
        "later_comparative_revision",
        "repeated_unchanged_observation",
    } <= categories
    assert all(f["causal_claim"] == "none" for f in findings)
    assert all(c["source"] and c["availability"] for f in findings for c in f["candidates"])


@pytest.mark.parametrize(
    "cutoff,policy,value,status",
    [
        ("2019-11-11", "latest_available", -281283000, "eligible"),
        ("2019-11-13", "latest_available", -175293000, "eligible"),
        ("2019-11-13", "first_reported", -281283000, "eligible"),
        ("2019-11-13", "all_available", None, "conflicted"),
    ],
)
def test_authentic_amended_annual_residual(historical, cutoff, policy, value, status):
    from finpanel import metrics
    from finpanel.sec.client import SECClient
    from finpanel.snapshots.pipeline import _PinnedCache

    # Original annual - nine months: -1,053,836,000 - (-772,553,000).
    # Amended same-filing pair: -1,054,579,000 - (-879,286,000).
    # Those literals and accessions are independently anchored in the SEC ledger.
    store, snapshot = historical["release"]
    with SECClient(cache=_PinnedCache(store, snapshot), offline=True) as client:
        result = metrics.derive_quarter(
            "63276",
            "net_income",
            fiscal_year=2017,
            quarter="Q4",
            as_of=cutoff + "T12:00:00Z",
            revision_policy=policy,
            client=client,
        )
    assert (result.status, result.value) == (status, value)
    if value is not None:
        assert result.minuend.value - result.subtrahend.value == value
        assert all(e.eligible_as_of for e in result.availability.evidence)
        if policy == "latest_available" and cutoff == "2019-11-13":
            assert "shared_filing_operands" in result.diagnostics


def test_future_revision_values_do_not_change_prior_selection(historical):
    from dataclasses import replace

    from finpanel import asof, facts, revisions
    from finpanel.sec.client import SECClient
    from finpanel.serialization import dumps
    from finpanel.snapshots.pipeline import _PinnedCache

    store, snapshot = historical["release"]
    with SECClient(cache=_PinnedCache(store, snapshot), offline=True) as client:
        original = facts.for_concept("63276", "NetIncomeLoss", taxonomy="us-gaap", client=client)
    cutoff = "2019-11-11T12:00:00Z"
    altered = replace(
        original,
        records=tuple(
            replace(r, observation=replace(r.observation, value=999999))
            if r.observation.filing_date and r.observation.filing_date >= date(2019, 11, 12)
            else r
            for r in original.records
        ),
    )
    histories = [
        revisions.analyze(asof.from_inspection(i, cutoff), policy="latest_available")
        for i in (original, altered)
    ]
    assert dumps(histories[0].groups) == dumps(histories[1].groups)


@pytest.mark.parametrize(
    "cutoff,policy,value,status",
    [
        ("2019-11-11", "latest_available", 14913000, "eligible"),
        ("2019-11-13", "latest_available", None, "conflicted"),
        ("2019-11-13", "first_reported", 14913000, "eligible"),
    ],
)
def test_authentic_separately_revised_operands_do_not_mix(
    historical, cutoff, policy, value, status
):
    from finpanel import metrics
    from finpanel.sec.client import SECClient
    from finpanel.snapshots.pipeline import _PinnedCache

    store, snapshot = historical["release"]
    artifact = next(
        a
        for a in snapshot.manifest["artifacts"]
        if a["cik"] == "0000063276" and a["source_family"] == "companyfacts"
    )
    facts = store.raw(store._artifact(artifact)).json()["facts"]["us-gaap"]["NetIncomeLoss"][
        "units"
    ]["USD"]
    # The annual revision and cumulative revision occur in different accessions.
    assert facts[221]["val"] == -530993000 and facts[214]["val"] == -545906000
    assert facts[222]["val"] == -533299000 and facts[215]["val"] == -542938000
    assert facts[222]["accn"] == "0001628280-19-013975"
    assert facts[215]["accn"] == "0001628280-19-013987"
    with SECClient(cache=_PinnedCache(store, snapshot), offline=True) as client:
        result = metrics.derive_quarter(
            "63276",
            "net_income",
            fiscal_year=2018,
            quarter="Q4",
            as_of=cutoff + "T12:00:00Z",
            revision_policy=policy,
            client=client,
        )
    assert (result.status, result.value) == (status, value)
    if status == "conflicted":
        assert "unpaired_value_revision" in result.reasons
