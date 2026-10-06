"""Offline Phase 0C evidence, context, transport, and authentic acceptance checks."""

from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest

from finpanel import facts, filings
from finpanel.availability import validate
from finpanel.cache import FileCache
from finpanel.errors import CacheError, CacheMissError, SECRequestError, ValidationError
from finpanel.models import RawResponse
from finpanel.sec.client import SECClient
from finpanel.sec.companyfacts import parse_companyfacts
from finpanel.sec.headers import parse_filing_header
from finpanel.sec.submissions import parse_submissions
from finpanel.serialization import dumps, loads

ACCESSION = "0000000001-24-000001"
SECOND = "0000000001-24-000002"
THIRD = "0000000001-25-000003"
APPLE = "0000320193-24-000123"
FIXTURES = Path(__file__).parent / "fixtures"


def header(**overrides):
    fields = {
        "ACCESSION-NUMBER": ACCESSION,
        "CIK": "1",
        "TYPE": "10-K",
        "FILING-DATE": "20241101",
        "PERIOD": "20240928",
        "ACCEPTANCE-DATETIME": "20241101060136",
        "PUBLIC-DOCUMENT-COUNT": "2",
        **overrides,
    }
    body = (
        "<SEC-HEADER>test\n"
        + "\n".join(f"<{k}>{v}" for k, v in fields.items() if v is not None)
        + "\n</SEC-HEADER>\n"
    )
    return RawResponse(
        "https://fixture.invalid/header", body.encode(), "2026-10-06", raw_format="text"
    )


def submission(**overrides):
    return {
        "accessionNumber": ACCESSION,
        "form": "10-K",
        "filingDate": "2024-11-01",
        "reportDate": "2024-09-28",
        "acceptanceDateTime": "2024-11-01T10:01:36Z",
        **overrides,
    }


def parent(rows):
    columns = {k: [r.get(k) for r in rows] for k in sorted({k for r in rows for k in r})}
    return RawResponse(
        "https://data.sec.gov/submissions/CIK0000000001.json",
        dumps({"cik": 1, "filings": {"recent": columns, "files": []}}).encode(),
        "2026-10-06",
    )


def event(**overrides):
    parsed = parse_submissions(parent([submission(**overrides)]))
    return filings._merge("0000000001", list(parsed.records), [])[0]


def observation(**overrides):
    return {
        "val": 100,
        "start": "2023-09-30",
        "end": "2024-09-28",
        "accn": ACCESSION,
        "form": "10-K",
        "filed": "2024-11-01",
        "fy": 2024,
        "fp": "FY",
        **overrides,
    }


def company(rows):
    return RawResponse(
        "https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json",
        dumps({"cik": 1, "facts": {"us-gaap": {"Revenue": {"units": {"USD": rows}}}}}).encode(),
        "2026-10-06",
    )


def codes(result):
    return {d.code for d in result.diagnostics}


def test_header_fields_and_line_provenance():
    source = header()
    result = parse_filing_header(source)
    assert result.acceptance_datetime == datetime(2024, 11, 1, 10, 1, 36, tzinfo=UTC)
    assert result.acceptance_raw == "20241101060136"
    assert result.timezone_policy == "America/New_York"
    assert result.accession_number == ACCESSION and result.ciks == ("0000000001",)
    assert result.form == "10-K" and result.report_date == date(2024, 9, 28)
    assert result.public_document_count == 2 and not result.diagnostics
    for evidence in result.evidence:
        line = int(evidence.source.pointer.removeprefix("line:"))
        assert evidence.raw_value in source.text().splitlines()[line - 1]
        assert evidence.source.response_sha256 == source.sha256


def test_header_readable_labels_and_document_body_ignored():
    source = header()
    body = source.body.replace(b"<ACCESSION-NUMBER>", b"ACCESSION NUMBER: ")
    body = body.replace(b"<CIK>", b"CENTRAL INDEX KEY: ")
    body += b"<DOCUMENT>\n<TYPE>EX-99\n"
    parsed = parse_filing_header(replace(source, body=body))
    assert parsed.form == "10-K" and parsed.accession_number == ACCESSION
    assert parsed.ciks == ("0000000001",)


@pytest.mark.parametrize(
    "stamp,code",
    [
        (None, "missing_header_acceptance"),
        ("bad", "malformed_header_acceptance"),
        ("20241301060136", "malformed_header_acceptance"),
        ("20241103013000", "ambiguous_header_time"),
        ("20240310023000", "ambiguous_header_time"),
    ],
)
def test_header_unusable_timestamps(stamp, code):
    parsed = parse_filing_header(header(**{"ACCEPTANCE-DATETIME": stamp}))
    assert parsed.acceptance_datetime is None and code in codes(parsed)


def test_header_timezone_required_and_winter_offset():
    source = header(**{"ACCEPTANCE-DATETIME": "20240101060136"})
    assert parse_filing_header(source).acceptance_datetime.hour == 11
    unspecified = parse_filing_header(source, timezone=None)
    assert unspecified.acceptance_datetime is None
    assert "naive_header_acceptance" in codes(unspecified)


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("FILING-DATE", "20240230", "malformed_header_date"),
        ("ACCESSION-NUMBER", "bad", "invalid_header_accession"),
        ("CIK", "bad", "invalid_header_cik"),
        ("PUBLIC-DOCUMENT-COUNT", "-1", "invalid_document_count"),
    ],
)
def test_header_malformed_fields(field, value, code):
    assert code in codes(parse_filing_header(header(**{field: value})))


def test_duplicate_header_fields_retain_conflicts():
    source = header()
    source = replace(
        source, body=source.body.replace(b"</SEC-HEADER>", b"<TYPE>10-K/A\n</SEC-HEADER>")
    )
    parsed = parse_filing_header(source)
    assert parsed.form is None and parsed.raw_fields["TYPE"] == ("10-K", "10-K/A")
    checked = validate(event(), (parsed,))
    assert checked.availability.precision == "unknown" and "header_field_conflict" in codes(checked)


@pytest.mark.parametrize("body", [b"<html>denied</html>", b"<SEC-HEADER>truncated", b"\xff"])
def test_header_rejects_invalid_envelope(body):
    with pytest.raises(ValidationError):
        parse_filing_header(replace(header(), body=body))


def test_corroboration_keeps_proxy_and_all_sources():
    result = validate(
        event(acceptanceDateTime="2024-11-01T06:01:36-04:00"), (parse_filing_header(header()),)
    )
    assert result.comparison_status == "acceptance_corroborated"
    assert result.availability.method == "sec_acceptance_datetime"
    assert result.availability.timestamp == datetime(2024, 11, 1, 10, 1, 36, tzinfo=UTC)
    assert not result.diagnostics
    evidence = result.availability.evidence
    assert {e.source.source_url for e in evidence} == {header().url, parent([]).url}
    acceptance = next(e for e in evidence if e.field == "acceptanceDateTime")
    assert acceptance.source.pointer == "/filings/recent/acceptanceDateTime/0"


@pytest.mark.parametrize(
    "field,value",
    [
        ("ACCEPTANCE-DATETIME", "20241101060137"),
        ("TYPE", "10-K/A"),
        ("FILING-DATE", "20241102"),
        ("PERIOD", "20240929"),
        ("ACCESSION-NUMBER", SECOND),
        ("CIK", "2"),
    ],
)
def test_conflicting_sources_never_choose_winner(field, value):
    parsed = parse_filing_header(header(**{field: value}))
    result = validate(event(), (parsed,))
    assert result.comparison_status == "conflict"
    assert result.availability.precision == "unknown" and result.availability.timestamp is None
    assert result.availability.evidence
    assert any(d.category == "verified_inconsistency" for d in result.diagnostics)
    assert result == validate(event(), (parsed,))


def test_header_fills_missing_acceptance_but_does_not_remove_missing_diagnostic():
    result = validate(event(acceptanceDateTime=None), (parse_filing_header(header()),))
    assert result.availability.method == "filing_header_acceptance"
    assert result.comparison_status == "header_only" and "missing_acceptance" in codes(result)


@pytest.mark.parametrize(
    "stamp,code",
    [
        (None, "missing_acceptance"),
        ("bad", "malformed_acceptance"),
        ("2024-11-01T10:01:36", "naive_acceptance"),
        ("2024-11-01T04:00:00Z", "midnight_acceptance"),
    ],
)
def test_date_only_fallback_preserves_diagnostic(stamp, code):
    result = validate(event(acceptanceDateTime=stamp))
    assert result.availability.method == "filing_date_fallback"
    assert result.availability.precision == "date_only"
    assert result.availability.timestamp is None and code in codes(result)
    assert "limited_availability_precision" in codes(result)


def test_unknown_and_header_date_only_fallback():
    missing = event(acceptanceDateTime=None, filingDate=None)
    assert validate(missing).availability.precision == "unknown"
    result = validate(missing, (parse_filing_header(header(**{"ACCEPTANCE-DATETIME": None})),))
    assert result.availability.date == date(2024, 11, 1)
    assert result.availability.method == "filing_date_fallback"


def test_suspicious_ordering_is_heuristic_not_verified_error():
    result = validate(event(reportDate="2024-11-02", filingDate="2024-10-31"))
    assert {"acceptance_before_report_end", "acceptance_after_filing_day"} <= codes(result)
    assert not any(d.category == "verified_inconsistency" for d in result.diagnostics)


def test_multiple_headers_conflict_and_order_determinism():
    a = parse_filing_header(header())
    b = parse_filing_header(header(**{"ACCEPTANCE-DATETIME": "20241101060137"}))
    assert validate(event(), (a, b)) == validate(event(), (b, a))
    assert "acceptance_mismatch" in codes(validate(event(), (a, b)))


def test_header_client_cache_refresh_and_offline(tmp_path, limiter, clock):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, content=header().body)

    cache = FileCache(tmp_path)
    with SECClient(
        "test", cache=cache, limiter=limiter, transport=httpx.MockTransport(handler)
    ) as client:
        first = client.filing_header(1, ACCESSION)
        assert client.filing_header(1, ACCESSION).from_cache
        client.filing_header(1, ACCESSION, refresh=True)
    assert len(calls) == 2 and clock.sleeps == [1.0]
    assert (
        str(calls[0].url)
        == f"https://www.sec.gov/Archives/edgar/data/1/{ACCESSION.replace('-', '')}/"
        f"{ACCESSION}.hdr.sgml"
    )
    assert calls[0].headers["Accept"] == "text/plain" and first.raw_format == "text"
    with SECClient(cache=cache, offline=True) as client:
        assert client.filing_header(1, ACCESSION).body == header().body
        with pytest.raises(CacheMissError):
            client.filing_header(1, SECOND)
        with pytest.raises(ValidationError):
            client.filing_header(1, ACCESSION, refresh=True)
    with pytest.raises(ValidationError):
        first.json()
    assert len(list(tmp_path.glob("raw/requests/*/versions/*.json"))) == 2


@pytest.mark.parametrize("status,retries", [(403, 0), (429, 1), (503, 1)])
def test_header_reuses_transport_policy(tmp_path, limiter, status, retries):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status if len(calls) == 1 else 200, content=header().body)

    with SECClient(
        "test", cache_dir=tmp_path, limiter=limiter, transport=httpx.MockTransport(handler)
    ) as client:
        if retries:
            client.filing_header(1, ACCESSION)
        else:
            with pytest.raises(SECRequestError):
                client.filing_header(1, ACCESSION)
    assert len(calls) == 1 + retries


def test_header_bad_response_not_cached(tmp_path, limiter):
    with SECClient(
        "test",
        cache_dir=tmp_path,
        limiter=limiter,
        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"<html>bad</html>")),
    ) as client:
        with pytest.raises(ValidationError):
            client.filing_header(1, ACCESSION)
    assert not list(tmp_path.rglob("latest.json"))


def test_text_cache_integrity_and_legacy_json(tmp_path):
    cache = FileCache(tmp_path)
    source = parent([])
    cache.put(source)
    latest = next(tmp_path.rglob("latest.json"))
    meta = loads(latest.read_bytes())
    del meta["raw_format"]
    latest.write_text(dumps(meta))
    assert cache.get(source.url).json() == source.json()
    cache.put(header())
    next(tmp_path.rglob("*.txt")).write_bytes(b"corrupted")
    with pytest.raises(CacheError, match="hash mismatch"):
        cache.get(header().url)


@pytest.mark.parametrize(
    "fields,kind,days",
    [
        ({"start": "2024-01-01", "end": "2024-12-31"}, "duration", 366),
        ({"start": "2024-02-29", "end": "2024-02-29"}, "duration", 1),
        ({"start": "2024-03-01", "end": "2024-02-29"}, "unknown", None),
        ({"start": None}, "unknown", None),
        ({"start": "bad"}, "unknown", None),
        ({"end": None}, "unknown", None),
    ],
)
def test_context_classification(fields, kind, days):
    item = parse_companyfacts(company([observation(**fields)])).records[0]
    assert item.context.kind == kind and item.context.duration_days == days
    assert item.context.instance_context_id is None
    assert item.raw == observation(**fields)


def test_instant_context_does_not_invent_start():
    row = observation()
    del row["start"]
    item = parse_companyfacts(company([row])).records[0]
    assert item.context.kind == "instant" and item.context.start is None
    assert item.context.duration_days is None


def test_duplicate_amendment_and_later_comparative_are_distinct(tmp_path):
    cache = FileCache(tmp_path)
    cache.put(
        parent(
            [
                submission(),
                submission(accessionNumber=SECOND, form="10-K/A"),
                submission(
                    accessionNumber=THIRD,
                    filingDate="2025-11-01",
                    acceptanceDateTime="2025-11-01T10:00:00Z",
                ),
            ]
        )
    )
    rows = [
        observation(),
        observation(),
        observation(accn=SECOND, form="10-K/A", val=101),
        observation(accn=THIRD, filed="2025-11-01", fy=2025),
    ]
    source = company(rows)
    cache.put(source)
    with SECClient(cache=cache, offline=True) as client:
        result = facts.for_concept(1, "Revenue", client=client)
        assert dumps(result) == dumps(facts.for_concept(1, "Revenue", client=client))
    assert len(result.records) == 4 and len({r.observation_id for r in result.records}) == 4
    assert [r.observation.value for r in result.records] == [100, 100, 101, 100]
    assert result.records[2].filing.is_amendment
    assert result.records[3].availability.timestamp.year == 2025
    assert all(r.context.end == date(2024, 9, 28) for r in result.records)
    (group,) = result.repeated_periods
    assert group.accessions == (ACCESSION, SECOND, THIRD) and group.values_differ
    assert len(group.observation_ids) == 4
    assert "same_period_multiple_filings" in codes(result)
    for r in result.records:
        assert r.observation.provenance.response_sha256 == source.sha256
        assert r.filing.accession_number == r.observation.accession_number


def test_missing_link_and_conflicting_fact_metadata(tmp_path):
    cache = FileCache(tmp_path)
    cache.put(parent([submission()]))
    cache.put(company([observation(accn=SECOND), observation(form="10-K/A")]))
    with SECClient(cache=cache, offline=True) as client:
        result = facts.for_concept(1, "Revenue", client=client)
        assert not facts.for_concept(1, "NoSuchConcept", client=client).records
        with pytest.raises(ValidationError, match="Header accessions"):
            facts.for_concept(1, "Revenue", client=client, header_accessions=(SECOND,))
    missing, conflict = result.records
    assert missing.filing is None and missing.availability.precision == "unknown"
    assert "filing_not_found" in codes(missing)
    assert conflict.filing is not None and conflict.availability.precision == "unknown"
    assert "fact_filing_metadata_mismatch" in codes(conflict)


@pytest.fixture
def authentic_cache(historical_cache):
    for folder in (FIXTURES / "sec", FIXTURES / "headers"):
        for filename, meta in loads((folder / "manifest.json").read_bytes())["files"].items():
            if meta["cik"] != "0000320193":
                continue
            source = RawResponse(
                meta["source_url"],
                (folder / filename).read_bytes(),
                meta["retrieved_at"],
                raw_format=meta.get("raw_format", "json"),
            )
            assert source.sha256 == meta["sha256"]
            historical_cache.put(source)
    return historical_cache


def test_authentic_header_and_companyfacts_reproducibility(authentic_cache):
    with SECClient(cache=authentic_cache, offline=True) as client:
        checked = filings.validate_availability(320193, APPLE, client=client)
        revenue = facts.for_concept(
            320193,
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            client=client,
            header_accessions=(APPLE,),
        )
        assets = facts.for_concept(320193, "Assets", client=client)
    assert checked.comparison_status == "acceptance_corroborated" and not checked.diagnostics
    assert checked.headers[0].acceptance_raw == "20241101060136"
    assert checked.availability.timestamp == datetime(2024, 11, 1, 10, 1, 36, tzinfo=UTC)
    assert revenue.records and revenue.repeated_periods and assets.records
    assert all(r.context.kind == "duration" for r in revenue.records)
    assert all(r.context.kind == "instant" for r in assets.records)
    linked = [r for r in revenue.records if r.observation.accession_number == APPLE]
    assert linked and all(r.filing and "header_not_checked" not in codes(r) for r in linked)
    # Older date-derived values are in filing history, not necessarily this concept.
    with SECClient(cache=authentic_cache, offline=True) as client:
        history = filings.timeline(320193, client=client)
    assert any(r.availability.precision == "date_only" for r in history)
    assert {i.code for i in revenue.timeline_issues} == {"history_range_mismatch"}


def test_offline_cli_provenance_and_deterministic_export(authentic_cache, tmp_path, capsys):
    from finpanel.cli import main

    target = tmp_path / "facts.json"
    args = [
        "facts",
        "inspect",
        "320193",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "--offline",
        "--cache-dir",
        str(authentic_cache.root),
        "--header-accession",
        APPLE,
        "--output",
        str(target),
        "--limit",
        "2",
    ]
    assert main(args) == 0
    first = capsys.readouterr().out
    full = target.read_bytes()
    assert main(args) == 0 and capsys.readouterr().out == first
    assert target.read_bytes() == full
    assert len(loads(full)["records"]) > 2
    assert (
        main(
            [
                "filings",
                "validate-availability",
                "320193",
                APPLE,
                "--offline",
                "--cache-dir",
                str(authentic_cache.root),
                "--strict",
            ]
        )
        == 0
    )
    assert loads(capsys.readouterr().out)["comparison_status"] == "acceptance_corroborated"


def test_invalid_timezone_policy_is_explicit():
    with pytest.raises(ValidationError, match="timezone policy"):
        parse_filing_header(header(), timezone="Not/AZone")


def test_submissions_conflict_retains_all_evidence():
    parsed = parse_submissions(
        parent([submission(), submission(acceptanceDateTime="2024-11-01T10:02:36Z")])
    )
    filing = filings._merge("0000000001", list(parsed.records), [])[0]
    checked = validate(filing)
    assert checked.comparison_status == "conflict"
    assert checked.availability.method == "unknown"
    assert len([e for e in checked.availability.evidence if e.field == "acceptanceDateTime"]) == 2
    assert "submissions_conflict" in codes(checked)


def test_repetition_never_mixes_units_or_namespaces(tmp_path):
    cache = FileCache(tmp_path)
    cache.put(parent([submission(), submission(accessionNumber=SECOND)]))
    source = company([observation()])
    payload = source.json()
    payload["facts"]["us-gaap"]["Revenue"]["units"]["EUR"] = [observation(accn=SECOND)]
    payload["facts"]["other"] = {"Revenue": {"units": {"USD": [observation(accn=SECOND)]}}}
    cache.put(replace(source, body=dumps(payload).encode()))
    with SECClient(cache=cache, offline=True) as client:
        result = facts.for_concept(1, "Revenue", client=client)
        filtered = facts.for_concept(1, "Revenue", taxonomy="other", client=client)
    assert len(result.records) == 3 and not result.repeated_periods
    assert len(filtered.records) == 1 and filtered.records[0].observation.taxonomy == "other"


def test_unknown_concept_does_not_require_timeline(tmp_path):
    cache = FileCache(tmp_path)
    cache.put(company([observation()]))
    with SECClient(cache=cache, offline=True) as client:
        result = facts.for_concept(1, "Absent", client=client)
    assert result.records == () and "concept_not_found" in codes(result)


def test_filtered_or_other_issuer_timeline_rejected(tmp_path):
    cache = FileCache(tmp_path)
    cache.put(parent([submission()]))
    cache.put(company([observation()]))
    with SECClient(cache=cache, offline=True) as client:
        data = filings.timeline(1, client=client)
        for unusable in (
            replace(data, cik="0000000002"),
            filings.available_as_of(data, "2025-01-01T00:00:00Z"),
        ):
            with pytest.raises(ValidationError, match="unfiltered timeline"):
                facts.for_concept(1, "Revenue", client=client, filing_timeline=unusable)


def test_header_capture_preserves_existing_evidence(tmp_path, monkeypatch):
    import runpy
    import sys

    (tmp_path / "existing.sgml").write_bytes(b"existing evidence")
    monkeypatch.setattr(
        sys, "argv", ["freeze_filing_header.py", "1", ACCESSION, "--output", str(tmp_path)]
    )
    with pytest.raises(SystemExit) as exc:
        runpy.run_path(
            str(Path(__file__).parents[1] / "examples/freeze_filing_header.py"), run_name="__main__"
        )
    assert exc.value.code == 2
    assert (tmp_path / "existing.sgml").read_bytes() == b"existing evidence"
