"""Cutoff-before-derivation tests and exact-concept temporal revision contracts."""

from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from finpanel import asof, facts, filings, periods, revisions
from finpanel.errors import ValidationError
from finpanel.models import RawResponse
from finpanel.models.timeline import Availability, FilingTimeline
from finpanel.sec.client import SECClient
from finpanel.sec.companyfacts import parse_companyfacts
from finpanel.sec.submissions import parse_submissions
from finpanel.serialization import dumps, loads

FIXTURES = Path(__file__).parent / "fixtures"
CONCEPT = "RevenueFromContractWithCustomerExcludingAssessedTax"


def fact(
    *,
    n=1,
    start="2021-01-01",
    end="2021-12-31",
    fy=2021,
    fp="FY",
    filed="2022-02-01",
    accepted="2022-02-01T15:00:00Z",
    report=None,
    value=100,
    form="10-K",
    unit="USD",
    taxonomy="us-gaap",
    concept="Revenue",
):
    accession = f"0000000001-22-{n:06d}"
    row = {
        "start": start,
        "end": end,
        "fy": fy,
        "fp": fp,
        "filed": filed,
        "accn": accession,
        "val": value,
        "form": form,
    }
    if start == "absent":
        del row["start"]
    source = RawResponse(
        "https://fixture.invalid/facts",
        dumps(
            {
                "cik": 1,
                "entityName": "Current name",
                "facts": {taxonomy: {concept: {"units": {unit: [row]}}}},
            }
        ).encode(),
        "2026-10-06",
    )
    obs = parse_companyfacts(source).records[0]
    parent = RawResponse(
        "https://fixture.invalid/submissions",
        dumps(
            {
                "cik": 1,
                "name": "Current name",
                "fiscalYearEnd": "1231",
                "filings": {
                    "recent": {
                        "accessionNumber": [accession],
                        "filingDate": [filed],
                        "form": [form],
                        "reportDate": [report or end],
                        "acceptanceDateTime": [accepted],
                    }
                },
            }
        ).encode(),
        "2026-10-06",
    )
    event = filings._merge(obs.cik, list(parse_submissions(parent).records), [])[0]
    return facts.LinkedFact(obs, obs.observation_id, obs.context, event, event.availability, ())


def inspection(*records):
    return facts.FactInspection("0000000001", "Revenue", tuple(records), (), (), (), (), ())


def bounded(*records, cutoff="2024-01-01T00:00:00Z"):
    return asof.from_inspection(inspection(*records), cutoff)


def selected_values(group):
    return [
        c.observation.fact.observation.value
        for c in group.candidates
        if c.observation.fact.observation_id in group.selected_observation_ids
    ]


@pytest.mark.parametrize(
    "cutoff,eligible",
    [
        ("2022-02-01T14:59:59Z", False),
        ("2022-02-01T15:00:00Z", True),
        ("2022-02-01T10:00:00-05:00", True),
        ("2022-02-01T15:00:01Z", True),
    ],
)
def test_exact_inclusive_cutoff(cutoff, eligible):
    view = bounded(fact(), cutoff=cutoff)
    assert bool(view.filings) == bool(view.records) == eligible
    assert all(e.eligible_as_of for e in view.admitted_evidence)
    assert not any(e.eligible_as_of for e in view.excluded_evidence)
    if not eligible:
        assert "future_acceptance" in view.excluded_observations[0].eligibility.reason


@pytest.mark.parametrize(
    "filed,cutoff,eligible",
    [
        ("2022-02-01", "2022-02-01T20:00:00Z", False),
        ("2022-02-01", "2022-02-02T04:59:59Z", False),
        ("2022-02-01", "2022-02-02T05:00:00Z", True),
        ("2022-06-01", "2022-06-02T03:59:59Z", False),
        ("2022-06-01", "2022-06-02T04:00:00Z", True),
        ("2022-06-01", "2022-05-31T20:00:00Z", False),
    ],
)
def test_date_only_never_upgraded(filed, cutoff, eligible):
    view = bounded(fact(filed=filed, accepted=None), cutoff=cutoff)
    assert bool(view.records) == eligible
    decision = (view.records[0] if eligible else view.excluded_observations[0]).eligibility
    assert decision.source_availability.precision == "date_only"
    assert decision.source_availability.timestamp is None
    if not eligible and filed == "2022-02-01":
        assert "date_only_same_day_excluded" in decision.reason


def test_unknown_availability_and_missing_link_excluded():
    a = fact(accepted=None, filed=None)
    b = replace(fact(n=2), filing=None)
    view = bounded(a, b)
    assert not view.records and not view.filings
    assert any("unknown_availability" in e.eligibility.reason for e in view.excluded_observations)
    assert any(
        e.eligibility.reason == "missing_or_invalid_filing_link" for e in view.excluded_observations
    )
    assert revisions.analyze(view).groups == ()


def test_fact_availability_conflict_cannot_inherit_usable_filing():
    a = replace(fact(), availability=Availability("unknown", reason="Fact metadata conflict"))
    view = bounded(a)
    assert len(view.filings) == 1 and not view.records
    assert view.excluded_observations[0].eligibility.reason == "unknown_availability"


def quarter_facts():
    return (
        fact(
            n=1,
            end="2021-03-31",
            fp="Q1",
            form="10-Q",
            filed="2021-04-30",
            accepted="2021-04-30T15:00:00Z",
        ),
        fact(
            n=2,
            end="2021-06-30",
            fp="Q2",
            form="10-Q",
            filed="2021-07-30",
            accepted="2021-07-30T15:00:00Z",
        ),
        fact(
            n=3,
            end="2021-09-30",
            fp="Q3",
            form="10-Q",
            filed="2021-10-30",
            accepted="2021-10-30T15:00:00Z",
        ),
        fact(
            n=4,
            start="2021-07-01",
            end="2021-09-30",
            fp="Q3",
            form="10-Q",
            filed="2021-10-30",
            accepted="2021-10-30T15:00:00Z",
        ),
        fact(n=5),
    )


def test_future_calendar_removed_before_derivation():
    rows = quarter_facts()
    retrospect = periods.interpret(inspection(*rows))
    early = bounded(*rows, cutoff="2021-11-01T00:00:00Z")
    assert retrospect.mode == "retrospective"
    assert retrospect.records[3].period.kind == "single_quarter"
    assert retrospect.records[3].period.mode == "retrospective"
    assert not early.calendar.years and not early.calendar.quarters
    assert all(r.period.kind == "ambiguous" for r in early.records)
    assert all(r.period.mode == "as_of" and r.period.as_of == early.as_of for r in early.records)
    assert rows[-1].observation_id in {e.fact.observation_id for e in early.excluded_observations}
    late = bounded(*rows)
    assert late.records[3].period.kind == "single_quarter"
    assert late.records[0].period.is_year_to_date and late.records[0].period.is_single_quarter


def test_future_mutations_cannot_change_admitted_interpretation_or_candidates():
    known = fact()
    future = fact(n=2, fy=2021, filed="2025-01-01", accepted="2025-01-01T15:00:00Z", value=98)
    base = bounded(known)
    added = bounded(known, future)
    poisoned = bounded(
        known,
        replace(
            future,
            observation=replace(
                future.observation,
                period_start=date(2020, 12, 20),
                value=999999,
                fiscal_period="Q3",
            ),
        ),
    )
    assert dumps(base.records) == dumps(added.records) == dumps(poisoned.records)
    assert dumps(base.calendar) == dumps(added.calendar) == dumps(poisoned.calendar)
    assert dumps(base.admitted_evidence) == dumps(added.admitted_evidence)
    for policy in revisions.POLICIES:
        assert dumps(revisions.analyze(base, policy=policy).groups) == dumps(
            revisions.analyze(added, policy=policy).groups
        )
        assert dumps(revisions.analyze(base, policy=policy).groups) == dumps(
            revisions.analyze(poisoned, policy=policy).groups
        )


def test_all_derived_evidence_has_an_eligible_provenance_chain():
    view = bounded(*quarter_facts())
    admitted = {d.source for d in view.admitted_evidence}
    for row in view.records:
        assert row.eligibility.source_accession == row.fact.filing.accession_number
        assert row.eligibility.observation_id == row.fact.observation_id
        assert (
            {e.source for e in row.period.evidence}
            <= {e.source for e in row.supporting_evidence}
            <= admitted
        )
        assert all(e.eligible_as_of and e.as_of == view.as_of for e in row.supporting_evidence)
    for anchor in (*view.calendar.years, *view.calendar.quarters):
        assert {e.source for e in anchor.evidence} <= admitted


def test_current_issuer_attributes_withheld_and_originals_preserved():
    original = fact()
    before = dumps(original)
    view = bounded(original)
    assert dumps(original) == before
    assert original.observation.entity_name == "Current name"
    assert view.records[0].fact.observation.entity_name is None
    assert view.records[0].fact.filing.source_records[0].entity_name is None
    assert not view.calendar.current_year_end_hints
    assert not view.calendar.evidence
    assert {e.source.pointer for e in view.excluded_evidence if e.role == "issuer_metadata"} == {
        "/entityName",
        "/name",
        "/fiscalYearEnd",
    }
    assert view.records[0].fact.observation.raw == original.observation.raw


@pytest.mark.parametrize("policy,expected", [("first_reported", 100), ("latest_available", 98)])
def test_ordered_revision_contract_and_history(policy, expected):
    a = fact()
    b = fact(n=2, value=98, form="10-K/A", filed="2022-06-01", accepted="2022-06-01T15:00:00Z")
    (group,) = revisions.analyze(bounded(a, b), policy=policy).groups
    assert group.status == "resolved" and selected_values(group) == [expected]
    assert len(group.candidates) == 2
    assert any(c.is_amendment for c in group.candidates)
    assert {c.observation.fact.observation.value for c in group.candidates} == {100, 98}


def test_latest_means_by_cutoff_not_today():
    a = fact()
    b = fact(
        n=2,
        value=98,
        filed="2023-02-01",
        accepted="2023-02-01T15:00:00Z",
        report="2022-12-31",
        fy=2022,
    )
    early = revisions.analyze(
        bounded(a, b, cutoff="2022-03-01T00:00:00Z"), policy="latest_available"
    )
    late = revisions.analyze(bounded(a, b), policy="latest_available")
    assert selected_values(early.groups[0]) == [100]
    assert selected_values(late.groups[0]) == [98]
    assert any(c.is_comparative for c in late.groups[0].candidates)
    assert late.groups[0].normalized_period.fiscal_year == 2021


@pytest.mark.parametrize("value,status", [(100, "resolved"), (98, "conflicted")])
def test_all_available_preserves_value_disagreement(value, status):
    a, b = fact(), fact(n=2, value=value, filed="2023-02-01", accepted="2023-02-01T15:00:00Z")
    (group,) = revisions.analyze(bounded(a, b)).groups
    assert len(group.candidates) == 2 and group.status == status
    if status == "conflicted":
        assert (
            "incompatible_candidate_values" in group.conflicts
            and not group.selected_observation_ids
        )
    else:
        assert len(group.selected_observation_ids) == 2


@pytest.mark.parametrize("policy", ["first_reported", "latest_available"])
@pytest.mark.parametrize("value", [98, 100])
def test_equal_time_never_uses_accession_as_tiebreak(policy, value):
    (group,) = revisions.analyze(bounded(fact(), fact(n=2, value=value)), policy=policy).groups
    assert group.status == "conflicted" and not group.selected_observation_ids
    assert "multiple_equally_ranked_or_unordered_candidates" in group.conflicts
    if value != 100:
        assert "incompatible_candidate_values" in group.conflicts


@pytest.mark.parametrize("policy", ["first_reported", "latest_available"])
def test_date_only_and_exact_same_day_are_partially_ordered(policy):
    (group,) = revisions.analyze(bounded(fact(accepted=None), fact(n=2)), policy=policy).groups
    assert group.status == "conflicted" and not group.selected_observation_ids


def test_date_only_distinct_days_and_next_day_boundary():
    first = fact(accepted=None)
    second = fact(n=2, filed="2022-02-02", accepted="2022-02-02T05:00:00Z", value=98)
    view = bounded(first, second)
    assert selected_values(revisions.analyze(view, policy="first_reported").groups[0]) == [100]
    assert selected_values(revisions.analyze(view, policy="latest_available").groups[0]) == [98]


@pytest.mark.parametrize("policy", sorted(revisions.POLICIES))
def test_unknown_peer_availability_remains_conflict(policy):
    view = bounded(fact(), fact(n=2, accepted=None, filed=None, value=98))
    (group,) = revisions.analyze(view, policy=policy).groups
    assert "unknown_availability" in group.conflicts and not group.selected_observation_ids
    assert len(group.unknown_availability_observations) == 1 and len(group.candidates) == 1


def test_ambiguous_period_group_no_winner():
    q = quarter_facts()[0]
    (group,) = revisions.analyze(bounded(q), policy="latest_available").groups
    assert "insufficient_period_evidence" in group.conflicts
    assert group.normalized_period is None and not group.selected_observation_ids


def test_period_disagreement_not_silently_split():
    a = fact()
    b = fact(n=2, fp="Q3", form="10-Q", value=98)
    (group,) = revisions.analyze(bounded(a, b)).groups
    assert {"insufficient_period_evidence", "period_classification_disagreement"} <= set(
        group.conflicts
    )


@pytest.mark.parametrize(
    "extra",
    [
        {"unit": "EUR"},
        {"taxonomy": "other"},
        {"concept": "OtherConcept"},
        {"start": "absent"},
        {"start": "2020-01-01", "end": "2020-12-31", "fy": 2020},
    ],
)
def test_grouping_never_uses_value_alone(extra):
    result = revisions.analyze(bounded(fact(), fact(n=2, **extra)))
    assert len(result.groups) == 2


def test_unknown_contexts_not_merged():
    result = revisions.analyze(bounded(fact(start=None), fact(n=2, start=None)))
    assert len(result.groups) == 2 and all(g.status == "conflicted" for g in result.groups)


def test_fixed_input_determinism():
    data = inspection(fact(), fact(n=2, filed="2023-02-01", accepted="2023-02-01T15:00:00Z"))
    a = asof.from_inspection(data, "2024-01-01T00:00:00Z")
    b = asof.from_inspection(data, "2024-01-01T00:00:00Z")
    assert dumps(a) == dumps(b)
    for policy in revisions.POLICIES:
        assert dumps(revisions.analyze(a, policy=policy)) == dumps(
            revisions.analyze(b, policy=policy)
        )


@pytest.mark.parametrize("cutoff", [None, "2022-01-01", "2022-01-01T00:00:00", "bad", 123])
def test_invalid_cutoff_rejected_before_client(cutoff):
    with pytest.raises(ValidationError):
        asof.view(1, cutoff)


def test_invalid_policy_rejected_before_client():
    with pytest.raises(ValidationError):
        asof.revisions(1, "Revenue", "2022-01-01T00:00:00Z", policy="correct_revenue")


def test_wrong_issuer_and_filtered_timeline_rejected():
    row = fact()
    timeline = FilingTimeline("0000000001", (row.filing,), (), (), (), ())
    for data in (
        replace(timeline, cik="0000000002"),
        replace(timeline, as_of=datetime(2024, 1, 1, tzinfo=UTC)),
    ):
        with pytest.raises(ValidationError):
            asof.from_inspection(inspection(row), "2024-01-01T00:00:00Z", filing_timeline=data)


@pytest.fixture
def apple_cache(historical_cache):
    folder = FIXTURES / "sec"
    meta = loads((folder / "manifest.json").read_bytes())["files"]["aapl_companyfacts.json"]
    source = RawResponse(
        meta["source_url"], (folder / "aapl_companyfacts.json").read_bytes(), meta["retrieved_at"]
    )
    assert source.sha256 == meta["sha256"]
    historical_cache.put(source)
    return historical_cache


def test_authentic_apple_future_filing_fact_and_calendar_exclusion(apple_cache):
    with SECClient(cache=apple_cache, offline=True) as client:
        inspected = facts.for_concept(320193, CONCEPT, client=client)
    early = asof.from_inspection(inspected, "2024-08-02T20:00:00Z")
    retrospect = periods.interpret(inspected)
    q3id = next(
        r.fact.observation_id
        for r in retrospect.records
        if r.fact.observation.accession_number == "0000320193-24-000081"
        and r.period.start == date(2024, 3, 31)
        and r.period.end == date(2024, 6, 29)
    )
    assert (
        next(r.period.kind for r in retrospect.records if r.fact.observation_id == q3id)
        == "single_quarter"
    )
    before = next(r for r in early.records if r.fact.observation_id == q3id)
    assert before.period.kind == "ambiguous"
    assert not any(w.fiscal_year == 2024 for w in early.calendar.years)
    annual = "0000320193-24-000123"
    assert annual not in {r.fact.observation.accession_number for r in early.records}
    assert annual in {r.fact.observation.accession_number for r in early.excluded_observations}
    assert all(e.source_accession != annual for e in before.supporting_evidence)
    after = asof.from_inspection(inspected, "2024-11-01T10:01:36Z")
    assert (
        next(r.period.kind for r in after.records if r.fact.observation_id == q3id)
        == "single_quarter"
    )


def test_authentic_comparative_enters_only_at_later_filing(apple_cache):
    with SECClient(cache=apple_cache, offline=True) as client:
        earlier = asof.revisions(
            320193, CONCEPT, "2023-11-03T20:00:00Z", policy="latest_available", client=client
        )
        later = asof.revisions(
            320193, CONCEPT, "2024-11-02T00:00:00Z", policy="latest_available", client=client
        )

    def annual_group(history):
        return next(
            g
            for g in history.groups
            if g.identity["start"] == date(2022, 9, 25) and g.identity["end"] == date(2023, 9, 30)
        )

    a, b = annual_group(earlier), annual_group(later)
    assert len(a.candidates) < len(b.candidates)
    assert all(
        c.observation.fact.observation.accession_number != "0000320193-24-000123"
        for c in a.candidates
    )
    assert any(
        c.observation.fact.observation.accession_number == "0000320193-24-000123"
        and c.is_comparative
        for c in b.candidates
    )
    assert a.normalized_period.fiscal_year == b.normalized_period.fiscal_year == 2023


def test_offline_cli_both_commands_and_exports(apple_cache, tmp_path, capsys):
    from finpanel.cli import main

    target = tmp_path / "evidence.json"
    base = ["--offline", "--cache-dir", str(apple_cache.root), "--limit", "1"]
    args = [
        "asof",
        "evidence",
        "320193",
        "2024-08-02T20:00:00Z",
        "--concept",
        CONCEPT,
        "--output",
        str(target),
        *base,
    ]
    assert main(args) == 0
    first = capsys.readouterr().out
    raw = target.read_bytes()
    assert main(args) == 0 and capsys.readouterr().out == first and target.read_bytes() == raw
    assert loads(raw)["mode"] == "as_of" and loads(raw)["excluded_evidence"]
    args = [
        "facts",
        "revisions",
        "320193",
        CONCEPT,
        "--as-of",
        "2024-01-01T00:00:00Z",
        "--policy",
        "first_reported",
        *base,
    ]
    assert main(args) == 0
    assert loads(capsys.readouterr().out)["revision_policy"] == "first_reported"
    assert main(args + ["--strict"]) == 1
    capsys.readouterr()
    assert main(["asof", "evidence", "320193", "2024-01-01T00:00:00Z", *base]) == 0
    assert loads(capsys.readouterr().out)["eligible_observations"] == 0


def test_cli_cache_miss_and_invalid_cutoff(tmp_path, capsys):
    from finpanel.cli import main

    base = [
        "asof",
        "evidence",
        "1",
        "2024-01-01T00:00:00Z",
        "--offline",
        "--cache-dir",
        str(tmp_path),
    ]
    assert main(base) == 2 and "Offline cache miss" in capsys.readouterr().err
    base[3] = "2024-01-01"
    assert main(base) == 2 and "timezone" in capsys.readouterr().err


def test_retroactive_classification_cannot_be_injected_into_revision_view():
    rows = quarter_facts()
    view = bounded(*rows, cutoff="2021-11-01T00:00:00Z")
    retro = periods.interpret(inspection(*rows))
    injected = replace(view.records[3], period=retro.records[3].period)
    with pytest.raises(ValidationError, match="eligible at the view cutoff"):
        revisions.analyze(replace(view, records=(injected,)))
    # Relabeling the mode still cannot admit unsupported future evidence.
    injected = replace(injected, period=replace(injected.period, mode="as_of", as_of=view.as_of))
    with pytest.raises(ValidationError, match="outside the cutoff boundary"):
        revisions.analyze(replace(view, records=(injected,)))


def test_future_availability_cannot_be_marked_eligible_by_flag_only():
    view = bounded(fact())
    record = view.records[0]
    future = Availability("acceptance_datetime", timestamp=datetime(2025, 1, 1, tzinfo=UTC))
    forged = replace(record, fact=replace(record.fact, availability=future))
    with pytest.raises(ValidationError):
        revisions.analyze(replace(view, records=(forged,)))


def test_empty_revision_status_is_explicit():
    history = revisions.analyze(bounded(fact(), cutoff="2020-01-01T00:00:00Z"))
    assert history.status == "no_eligible_candidates"
    assert history.evidence.excluded_observations


def test_eligibility_ignores_stray_timestamp_on_unknown_precision():
    source = fact().observation.provenance
    unknown = Availability("unknown", timestamp=datetime(2020, 1, 1, tzinfo=UTC))
    assert not asof.eligibility(source, None, unknown, "2024-01-01T00:00:00Z").eligible_as_of


def test_naive_availability_cannot_become_eligible():
    source = fact().observation.provenance
    naive = Availability("acceptance_datetime", timestamp=datetime(2020, 1, 1))
    assert (
        asof.eligibility(source, None, naive, "2024-01-01T00:00:00Z").reason
        == "unknown_availability"
    )


def test_date_only_ordering_respects_dst_day_boundary():
    a = fact(accepted=None, filed="2022-03-13")
    b = fact(n=2, value=98, filed="2022-03-14", accepted="2022-03-14T04:00:00Z")
    view = bounded(a, b)
    assert selected_values(revisions.analyze(view, policy="latest_available").groups[0]) == [98]
    assert selected_values(revisions.analyze(view, policy="first_reported").groups[0]) == [100]


def test_future_conflicting_calendar_cannot_poison_past_year():
    original = fact()
    conflicting = fact(n=2, start="2020-12-20", filed="2025-02-01", accepted="2025-02-01T15:00:00Z")
    retro = periods.interpret(inspection(original, conflicting))
    assert retro.calendar.ambiguous_years == (2021,)
    past = bounded(original, conflicting)
    assert not past.calendar.ambiguous_years
    assert past.records[0].period.kind == "annual"
    assert revisions.analyze(past, policy="latest_available").groups[0].status == "resolved"


def test_retrospective_cli_identifies_its_mode(apple_cache, capsys):
    from finpanel.cli import main

    assert (
        main(
            [
                "facts",
                "periods",
                "320193",
                CONCEPT,
                "--offline",
                "--cache-dir",
                str(apple_cache.root),
                "--limit",
                "0",
            ]
        )
        == 0
    )
    assert loads(capsys.readouterr().out)["mode"] == "retrospective"
