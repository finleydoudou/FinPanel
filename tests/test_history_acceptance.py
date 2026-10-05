from datetime import UTC, date, datetime
from hashlib import sha256
from pathlib import Path

from finpanel import filings
from finpanel.models import RawResponse
from finpanel.sec.client import SECClient
from finpanel.sec.submissions import discover_historical_submissions, parse_historical_submissions
from finpanel.serialization import dumps, loads

ROOT = Path(__file__).parent / "fixtures"


def test_authentic_history_manifest_and_complete_source_rows(historical_cache):
    manifest = loads((ROOT / "history" / "manifest.json").read_bytes())
    assert manifest["kind"] == "official_sec_historical_snapshots"
    parent_bytes = (ROOT / "sec" / manifest["parent_file"]).read_bytes()
    assert sha256(parent_bytes).hexdigest() == manifest["parent_sha256"]
    parent = RawResponse(manifest["parent_source_url"], parent_bytes, "fixture")
    refs = discover_historical_submissions(parent)
    assert not refs.issues
    assert set(manifest["files"]) == {r.name for r in refs.records}
    raw_count = len(parent.json()["filings"]["recent"]["accessionNumber"])
    accessions = set(parent.json()["filings"]["recent"]["accessionNumber"])
    for filename, meta in manifest["files"].items():
        body = (ROOT / "history" / filename).read_bytes()
        assert sha256(body).hexdigest() == meta["sha256"]
        assert meta["raw_unmodified"] is True
        assert meta["source_url"] == f"https://data.sec.gov/submissions/{filename}"
        assert meta["cik"] == "0000320193"
        assert datetime.fromisoformat(meta["retrieved_at"]).tzinfo is not None
        source = RawResponse(meta["source_url"], body, meta["retrieved_at"])
        parsed = parse_historical_submissions(source, cik=meta["cik"])
        assert not parsed.issues
        data = source.json()
        raw_count += len(data["accessionNumber"])
        accessions.update(data["accessionNumber"])
        assert len(parsed.records) == meta["records"] == len(data["accessionNumber"])
        for index, record in enumerate(parsed.records):
            assert record.raw == {key: values[index] for key, values in data.items()}
            assert record.provenance.pointer == f"/accessionNumber/{index}"
            assert record.provenance.response_sha256 == source.sha256
    with SECClient(cache=historical_cache, offline=True) as client:
        timeline = filings.timeline(320193, client=client)
        repeated = filings.timeline(320193, client=client)
    assert dumps(timeline) == dumps(repeated)
    assert len(timeline) == len(accessions) == 2260
    assert sum(len(r.source_records) for r in timeline) == raw_count
    assert {r.accession_number for r in timeline} == accessions
    assert {i.code for i in timeline.issues} == {"history_range_mismatch"}
    report = filings.coverage(timeline)
    assert report.earliest_filing == date(1994, 1, 26)
    assert report.latest_filing == date(2026, 10, 2)
    assert report.amendments >= 58
    assert report.date_only_availability_records > 0
    assert report.acceptance_timestamps_available > 0
    assert report.historical_files_loaded == 1
    for event in timeline:
        if event.availability.precision == "date_only":
            assert event.availability.timestamp is None
            assert event.source_records[0].acceptance_datetime is not None
    filtered = filings.available_as_of(timeline, "2020-06-30T15:00:00Z")
    assert 0 < len(filtered) < len(timeline)
    assert filtered.issues == timeline.issues
    cutoff = datetime(2020, 6, 30, 15, tzinfo=UTC)
    for event in filtered:
        if event.availability.timestamp is not None:
            assert event.availability.timestamp <= cutoff
        else:
            assert event.availability.date < date(2020, 6, 30)
