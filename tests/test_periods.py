"""Conservative period rules, immutable observations, and authentic offline reproduction."""

from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from finpanel import facts, filings, periods
from finpanel.errors import ValidationError
from finpanel.models import RawResponse
from finpanel.models.period import FiscalCalendar
from finpanel.sec.client import SECClient
from finpanel.sec.companyfacts import parse_companyfacts
from finpanel.sec.submissions import parse_submissions
from finpanel.serialization import dumps, loads

START = "2023-10-01"
END = "2024-09-28"
ENDS = {"Q1": "2023-12-30", "Q2": "2024-03-30", "Q3": "2024-06-29", "FY": END}
FIXTURES = Path(__file__).parent / "fixtures"


def linked(start=START, end=END, fp="FY", fy=2024, form=None, report=None, number=1, **extra):
    form = form or ("10-K" if fp == "FY" else "10-Q")
    report = report or end
    accession = f"0000000001-24-{number:06d}"
    row = {
        "start": start,
        "end": end,
        "fy": fy,
        "fp": fp,
        "form": form,
        "accn": accession,
        "filed": "2024-11-01",
        "val": 100,
        **extra,
    }
    if start == "absent":
        del row["start"]
    source = RawResponse(
        "https://fixture.invalid/facts",
        dumps({"cik": 1, "facts": {"us-gaap": {"Revenue": {"units": {"USD": [row]}}}}}).encode(),
        "2026-10-06",
    )
    obs = parse_companyfacts(source).records[0]
    raw = RawResponse(
        "https://fixture.invalid/submissions",
        dumps(
            {
                "cik": 1,
                "fiscalYearEnd": "0930",
                "filings": {
                    "recent": {
                        "accessionNumber": [accession],
                        "reportDate": [report],
                        "form": [form],
                        "filingDate": ["2024-11-01"],
                        "acceptanceDateTime": ["2024-11-01T10:00:00Z"],
                    }
                },
            }
        ).encode(),
        "2026-10-06",
    )
    event = filings._merge(obs.cik, list(parse_submissions(raw).records), [])[0]
    return facts.LinkedFact(obs, obs.observation_id, obs.context, event, event.availability, ())


@pytest.fixture
def anchors():
    return tuple(linked(end=end, fp=fp, number=i) for i, (fp, end) in enumerate(ENDS.items(), 1))


@pytest.fixture
def calendar(anchors):
    return periods.build_calendar(1, anchors)


def codes(result):
    return {d.code for d in result.diagnostics}


@pytest.mark.parametrize(
    "start,end,fp,kind,label,single,ytd",
    [
        (START, END, "FY", "annual", "FY", False, None),
        (START, ENDS["Q1"], "Q1", "single_quarter", "Q1", True, True),
        (START, ENDS["Q2"], "Q2", "year_to_date", "YTD-Q2", False, True),
        (START, ENDS["Q3"], "Q3", "year_to_date", "YTD-Q3", False, True),
        ("2023-12-31", ENDS["Q2"], "Q2", "single_quarter", "Q2", True, False),
        ("2024-03-31", ENDS["Q3"], "Q3", "single_quarter", "Q3", True, False),
        ("2024-06-30", END, "FY", "single_quarter", "Q4", True, False),
    ],
)
def test_exact_windows_and_q1_dual_meaning(calendar, start, end, fp, kind, label, single, ytd):
    r = periods.classify_period(linked(start, end, fp), calendar=calendar)
    assert (r.kind, r.identity.label, r.is_single_quarter, r.is_year_to_date) == (
        kind,
        label,
        single,
        ytd,
    )
    assert r.identity.fiscal_year == 2024 and r.status == "rule_supported"
    assert r.evidence and r.policy == "reported-context-periods-v1"


@pytest.mark.parametrize(
    "start,end,days",
    [
        ("2023-01-01", "2023-12-31", 365),
        ("2024-01-01", "2024-12-31", 366),
        (START, END, 364),
        ("2022-09-25", "2023-09-30", 371),
        ("2023-07-01", "2024-06-30", 366),
        ("2023-02-01", "2024-01-31", 365),
    ],
)
def test_annual_calendar_variants(start, end, days):
    fact = linked(start, end)
    result = periods.classify_period(fact)
    assert result.kind == "annual" and result.duration_days == days
    assert "unusual_duration" not in codes(result)


def test_14_week_first_quarter():
    annual = linked("2022-09-25", "2023-09-30", fy=2023)
    q1 = linked("2022-09-25", "2022-12-31", fp="Q1", fy=2023)
    calendar = periods.build_calendar(1, (annual, q1))
    result = periods.classify_period(q1, calendar=calendar)
    assert result.duration_days == 98 and result.is_single_quarter and result.is_year_to_date


@pytest.mark.parametrize(
    "start,end,kind,code",
    [
        ("absent", END, "instant", None),
        (None, END, "unknown", "unusable_period_dates"),
        ("bad", END, "unknown", "unusable_period_dates"),
        (START, None, "unknown", "unusable_period_dates"),
        (START, "bad", "unknown", "unusable_period_dates"),
        ("2024-10-01", END, "unknown", "reversed_period"),
    ],
)
def test_missing_and_invalid_periods(start, end, kind, code):
    result = periods.classify_period(linked(start, end))
    assert result.kind == kind and result.identity.label is None
    if code:
        assert code in codes(result)
    else:
        assert result.end == date(2024, 9, 28) and result.duration_days is None


def test_fp_alone_never_establishes_quarter():
    obs = linked("2024-03-31", ENDS["Q3"], "Q3").observation
    result = periods.classify_period(obs)
    assert result.kind == "ambiguous" and result.identity.label is None
    assert "missing_fiscal_boundary" in codes(result)


def test_current_mmdd_does_not_backfill_historical_year(anchors):
    quarterly = anchors[:3]
    calendar = periods.build_calendar(1, quarterly)
    assert calendar.current_year_end_hints == ("0930",) and not calendar.years
    assert periods.classify_period(quarterly[0], calendar=calendar).kind == "ambiguous"
    assert all(e.source.pointer == "/fiscalYearEnd" for e in calendar.evidence)


def test_comparative_fy_and_frame_not_reassigned(calendar):
    current = linked()
    later = linked(fy=2025, report="2025-09-27", number=99, frame="CY2024")
    a = periods.classify_period(current, calendar=calendar)
    b = periods.classify_period(later, calendar=calendar)
    assert a.identity == b.identity and b.identity.fiscal_year == 2024
    assert later.observation.fiscal_year == 2025
    assert later.observation.observation_id != current.observation.observation_id
    assert "comparative_context" in codes(b)


def test_annual_form_does_not_make_short_comparative_annual(calendar):
    result = periods.classify_period(
        linked("2024-03-31", ENDS["Q3"], "FY", report=END), calendar=calendar
    )
    assert result.kind == "single_quarter" and result.identity.label == "Q3"
    assert "annual_form_short_context" in codes(result)


def test_quarter_metadata_annual_context_conflict(calendar):
    result = periods.classify_period(linked(fp="Q3"), calendar=calendar)
    assert result.kind == "ambiguous" and result.identity.label is None
    assert {"fp_duration_conflict", "quarter_metadata_annual_duration"} <= codes(result)


def test_current_fiscal_year_conflict(calendar):
    result = periods.classify_period(linked(fy=2025), calendar=calendar)
    assert result.kind == "ambiguous" and "fiscal_year_conflict" in codes(result)


def test_wrong_fp_at_known_boundary(calendar):
    result = periods.classify_period(linked(end=ENDS["Q2"], fp="Q3"), calendar=calendar)
    assert result.kind == "ambiguous" and "fp_duration_conflict" in codes(result)


def test_conflicting_annual_anchors_and_quarter_anchors(anchors):
    for extra in (linked(start="2023-09-24"), linked(end="2024-03-23", fp="Q2")):
        calendar = periods.build_calendar(1, (*anchors, extra))
        assert calendar.ambiguous_years == (2024,)
        assert "fiscal_calendar_conflict" in codes(calendar)
        assert periods.classify_period(anchors[1], calendar=calendar).kind == "ambiguous"


def test_missing_previous_boundary_never_guesses_quarter(anchors):
    calendar = periods.build_calendar(1, (anchors[2], anchors[3]))
    result = periods.classify_period(linked("2024-03-31", ENDS["Q3"], "Q3"), calendar=calendar)
    assert result.kind == "ambiguous" and "missing_quarter_boundary" in codes(result)
    assert periods.classify_period(anchors[2], calendar=calendar).kind == "year_to_date"


@pytest.mark.parametrize("start,end", [("2024-01-01", "2024-01-07"), ("2022-01-01", END)])
def test_nonstandard_duration_not_discarded(start, end, calendar):
    fact = linked(start, end)
    result = periods.classify_period(fact, calendar=calendar)
    assert result.kind == "other_duration" and result.identity.label is None
    assert "unusual_duration" in codes(result)
    assert fact.observation.value == 100


def test_form_and_filing_relationship_conflict(calendar):
    fact = linked()
    result = periods.classify_period(
        replace(fact, filing=replace(fact.filing, form="10-Q")), calendar=calendar
    )
    assert result.kind == "ambiguous" and "period_filing_mismatch" in codes(result)


def test_context_after_report_end(calendar):
    result = periods.classify_period(linked(report="2024-09-20"), calendar=calendar)
    assert result.kind == "ambiguous" and "context_after_report_date" in codes(result)


def test_calendar_and_classification_determinism(anchors):
    a = periods.build_calendar(1, anchors)
    b = periods.build_calendar(1, tuple(reversed(anchors)))
    assert dumps(a) == dumps(b)
    assert dumps(periods.classify_period(anchors[0], calendar=a)) == dumps(
        periods.classify_period(anchors[0], calendar=b)
    )
    assert a == periods.build_calendar(1, anchors + anchors)


def test_cross_issuer_rejected(calendar, anchors):
    with pytest.raises(ValidationError):
        periods.classify_period(anchors[0], calendar=FiscalCalendar("0000000002"))
    with pytest.raises(ValidationError):
        periods.build_calendar(2, anchors)


def inspection(records):
    return facts.FactInspection("0000000001", "Revenue", records, (), (), (), (), ())


def test_overlapping_contexts_and_duplicate_preservation(anchors):
    quarter = linked("2024-03-31", ENDS["Q3"], "Q3", number=3)
    original = inspection((*anchors, quarter, quarter))
    result = periods.interpret(original)
    assert len(result.records) == len(original.records)
    assert result.provenance is original
    assert "overlapping_contexts" in codes(result.records[-1].period)
    assert [r.fact.observation.value for r in result.records] == [
        r.observation.value for r in original.records
    ]
    assert result.records[-1].period == result.records[-2].period


def authentic(ticker, concept):
    manifest = loads((FIXTURES / "sec/manifest.json").read_bytes())["files"]
    sources = []
    for endpoint in ("companyfacts", "submissions"):
        filename = f"{ticker}_{endpoint}.json"
        meta = manifest[filename]
        source = RawResponse(
            meta["source_url"], (FIXTURES / "sec" / filename).read_bytes(), meta["retrieved_at"]
        )
        assert source.sha256 == meta["sha256"]
        sources.append(source)
    parsed = parse_companyfacts(sources[0])
    cik = parsed.records[0].cik
    events = {
        e.accession_number: e
        for e in filings._merge(cik, list(parse_submissions(sources[1]).records), [])
    }
    from finpanel.models.timeline import Availability

    records = []
    for obs in parsed.records:
        if obs.taxonomy == "us-gaap" and obs.concept == concept:
            event = events.get(obs.accession_number)
            records.append(
                facts.LinkedFact(
                    obs,
                    obs.observation_id,
                    obs.context,
                    event,
                    event.availability if event else Availability("unknown"),
                    (),
                )
            )
    return periods.interpret(
        facts.FactInspection(
            cik, concept, tuple(records), (), (), (), (), tuple(s.provenance("") for s in sources)
        )
    )


def test_authentic_apple_q3_and_comparative_53_week_year():
    result = authentic("aapl", "RevenueFromContractWithCustomerExcludingAssessedTax")
    rows = [
        r
        for r in result.records
        if r.fact.observation.accession_number == "0000320193-24-000081"
        and r.period.end == date(2024, 6, 29)
    ]
    assert {(r.period.kind, r.period.duration_days, r.period.identity.label) for r in rows} == {
        ("single_quarter", 91, "Q3"),
        ("year_to_date", 273, "YTD-Q3"),
    }
    prior = [
        r
        for r in result.records
        if r.fact.observation.fiscal_year == 2024 and r.period.end == date(2023, 9, 30)
    ]
    assert prior and all(
        r.period.kind == "annual"
        and r.period.duration_days == 371
        and r.period.identity.fiscal_year == 2023
        for r in prior
    )
    assert len(result.records) == 117
    assert dumps(result) == dumps(
        authentic("aapl", "RevenueFromContractWithCustomerExcludingAssessedTax")
    )


@pytest.mark.parametrize(
    "ticker,concept",
    [
        ("aapl", "Assets"),
        ("msft", "CashAndCashEquivalentsAtCarryingValue"),
        ("wmt", "LiabilitiesCurrent"),
        ("aapl", "Liabilities"),
    ],
)
def test_authentic_instant_facts(ticker, concept):
    result = authentic(ticker, concept)
    assert result.records and all(r.period.kind == "instant" for r in result.records)
    assert all(r.period.identity.label is None for r in result.records)


@pytest.mark.parametrize(
    "ticker,concept",
    [
        ("msft", "RevenueFromContractWithCustomerExcludingAssessedTax"),
        ("wmt", "RevenueFromContractWithCustomerExcludingAssessedTax"),
        ("nvda", "Revenues"),
    ],
)
def test_existing_other_issuer_calendars(ticker, concept):
    result = authentic(ticker, concept)
    assert result.calendar.years and result.calendar.quarters
    assert {"annual", "single_quarter", "year_to_date"} <= {r.period.kind for r in result.records}
    assert any(w.end.month != 12 for w in result.calendar.years)


def test_offline_period_api_cli_and_exports(historical_cache, tmp_path, capsys):
    from finpanel.cli import main

    folder = FIXTURES / "sec"
    meta = loads((folder / "manifest.json").read_bytes())["files"]["aapl_companyfacts.json"]
    historical_cache.put(
        RawResponse(
            meta["source_url"],
            (folder / "aapl_companyfacts.json").read_bytes(),
            meta["retrieved_at"],
        )
    )
    with SECClient(cache=historical_cache, offline=True) as client:
        result = periods.for_concept(
            320193, "RevenueFromContractWithCustomerExcludingAssessedTax", client=client
        )
    assert len(result.records) == 117
    out = tmp_path / "periods.json"
    args = [
        "facts",
        "periods",
        "320193",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "--offline",
        "--cache-dir",
        str(historical_cache.root),
        "--limit",
        "2",
        "--output",
        str(out),
    ]
    assert main(args) == 0
    first = capsys.readouterr().out
    serialized = out.read_bytes()
    assert main(args) == 0 and capsys.readouterr().out == first and out.read_bytes() == serialized
    assert loads(first)["shown"] == 2 and len(loads(serialized)["records"]) == 117
    assert main(args + ["--strict"]) == 1  # Existing history range issue is retained.
    assert "history_range_mismatch" in capsys.readouterr().out


def test_offline_cache_miss_and_refresh_fail(tmp_path, capsys):
    from finpanel.cli import main

    args = ["facts", "periods", "1", "Revenue", "--offline", "--cache-dir", str(tmp_path)]
    assert main(args) == 2 and "Offline cache miss" in capsys.readouterr().err
    assert main(args + ["--refresh"]) == 2


def test_missing_fy_never_invents_fiscal_year():
    result = periods.classify_period(linked(fy=None))
    assert result.kind == "ambiguous" and result.identity.fiscal_year is None


@pytest.mark.parametrize("form", ["8-K", "20-F", "6-K"])
def test_unsupported_form_cannot_establish_annual_calendar(form):
    result = periods.classify_period(linked(form=form))
    assert result.kind == "ambiguous"


def test_missing_reporting_date_cannot_establish_boundary():
    fact = linked()
    fact = replace(fact, filing=replace(fact.filing, report_date=None))
    assert periods.classify_period(fact).kind == "ambiguous"


def test_amendment_is_retained_as_its_own_observation(calendar):
    original = linked()
    amendment = linked(form="10-K/A", number=9)
    a = periods.classify_period(original, calendar=calendar)
    b = periods.classify_period(amendment, calendar=calendar)
    assert a.identity == b.identity
    assert original.observation_id != amendment.observation_id
    assert amendment.filing.is_amendment


def test_only_fy_is_not_enough_for_annual():
    fact = linked("2024-01-01", "2024-02-01")
    result = periods.classify_period(fact)
    assert result.kind == "other_duration" and result.identity.label is None
    assert "annual_form_short_context" in codes(result)


def test_conflicting_fp_duration_diagnostic_without_calendar():
    result = periods.classify_period(linked(end=ENDS["Q2"], fp="Q1").observation)
    assert "fp_duration_guardrail" in codes(result)
    assert result.kind == "ambiguous"


def test_frame_never_overrides_observed_fiscal_quarter(calendar):
    fact = linked("2024-03-31", ENDS["Q3"], "Q3", frame="CY2024Q2")
    result = periods.classify_period(fact, calendar=calendar)
    assert result.identity.label == "Q3"
    assert any(e.field == "frame" and e.raw_value == "CY2024Q2" for e in result.evidence)


def test_calendar_conflict_evidence_retains_both_quarter_ends(anchors):
    conflicting = linked(end="2024-03-23", fp="Q2", number=88)
    calendar = periods.build_calendar(1, (*anchors, conflicting))
    result = periods.classify_period(anchors[1], calendar=calendar)
    values = {e.raw_value for e in result.evidence if e.field == "end"}
    assert {"2024-03-23", "2024-03-30"} <= values


def test_near_quarter_without_exact_start_remains_ambiguous(calendar):
    result = periods.classify_period(linked("2024-04-01", ENDS["Q3"], "Q3"), calendar=calendar)
    assert result.duration_days == 90 and result.kind == "ambiguous"
    assert result.identity.label is None


def test_empty_inspection_and_values_untouched():
    result = periods.interpret(inspection(()))
    assert result.records == () and result.calendar.years == ()
