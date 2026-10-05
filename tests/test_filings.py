from contextlib import ExitStack
from dataclasses import replace
from datetime import UTC, date, datetime

import pytest

from finpanel import filings
from finpanel.cache import FileCache
from finpanel.errors import CacheMissError, ValidationError
from finpanel.models import RawResponse
from finpanel.sec.client import SECClient
from finpanel.sec.submissions import discover_historical_submissions, parse_historical_submissions
from finpanel.serialization import dumps

HISTORY = "CIK0000000001-submissions-001.json"


def row(number=1, **fields):
    return {
        "accessionNumber": f"0000000001-20-{number:06d}",
        "filingDate": "2020-06-30",
        "form": "10-Q",
        "acceptanceDateTime": "2020-06-30T15:00:00Z",
        **fields,
    }


def columns(rows):
    return {key: [r.get(key) for r in rows] for key in sorted({k for r in rows for k in r})}


@pytest.fixture
def sources(tmp_path):
    with ExitStack() as stack:

        def make(recent, history=None, references=None, history_payload=None):
            cache = FileCache(tmp_path / str(len(stack._exit_callbacks)))
            if references is None:
                references = (
                    [] if history is None else [{"name": HISTORY, "filingCount": len(history)}]
                )
            data = {
                "cik": 1,
                "name": "Synthetic",
                "filings": {"recent": columns(recent), "files": references},
            }
            parent = RawResponse(
                "https://data.sec.gov/submissions/CIK0000000001.json",
                dumps(data).encode(),
                "2026-10-06T00:00:00+00:00",
            )
            cache.put(parent)
            source = None
            if history is not None or history_payload is not None:
                data = columns(history) if history_payload is None else history_payload
                source = RawResponse(
                    f"https://data.sec.gov/submissions/{HISTORY}",
                    dumps(data).encode(),
                    parent.retrieved_at,
                )
                cache.put(source)
            client = stack.enter_context(SECClient(cache=cache, offline=True))
            return client, parent, source

        yield make


def test_history_discovery_and_parsing(sources):
    client, parent, source = sources([row()], [row(2, extra="preserved")])
    refs = discover_historical_submissions(parent)
    assert len(refs.records) == 1 and not refs.issues
    assert refs.records[0].provenance.pointer == "/filings/files/0"
    parsed = parse_historical_submissions(source, cik=1, entity_name="Synthetic")
    assert not parsed.issues
    assert parsed.records[0].provenance.pointer == "/accessionNumber/0"
    assert parsed.records[0].provenance.response_sha256 == source.sha256
    assert parsed.records[0].raw["extra"] == "preserved"
    assert parsed.records[0].entity_name == "Synthetic"
    assert len(filings.timeline(1, client=client)) == 2


@pytest.mark.parametrize(
    "references",
    [
        None,
        {},
        [None],
        [{"name": "../other.json"}],
        [{"name": "https://example.org/x"}],
        [{"name": "CIK0000000002-submissions-001.json"}],
        [{}],
    ],
)
def test_malformed_discovery_is_reported(sources, references):
    _, parent, _ = sources([row()])
    data = parent.json()
    data["filings"]["files"] = references
    result = discover_historical_submissions(replace(parent, body=dumps(data).encode()))
    assert result.issues
    assert not result.records


def test_reference_optional_errors_retain_usable_name(sources):
    _, parent, _ = sources(
        [], references=[{"name": HISTORY, "filingCount": -1, "filingFrom": "bad"}]
    )
    result = discover_historical_submissions(parent)
    assert len(result.records) == 1
    assert len(result.issues) == 2


def test_overlap_identity_and_amendments(sources):
    client, _, _ = sources(
        [row(), row(2, form="10-K")],
        [row(), row(3, form="10-K/A"), row(4, form="8-K/A"), row(5, form="10-Q/A")],
    )
    data = filings.timeline(1, client=client)
    assert len(data) == 5
    duplicate = next(r for r in data if r.accession_number.endswith("000001"))
    assert len(duplicate.source_records) == 2
    assert len({r.provenance.source_url for r in duplicate.source_records}) == 2
    assert sum(r.is_amendment for r in data) == 3
    assert not data.issues
    assert filings.coverage(data).overlapping_accessions == 1


def test_duplicate_reference_fetched_once_with_all_references_preserved(sources):
    client, _, _ = sources([row()], [row(2)], [{"name": HISTORY}, {"name": HISTORY}])
    data = filings.timeline(1, client=client)
    assert len(data.historical_references) == 2
    assert data.historical_files_loaded == (HISTORY,)
    assert len(data) == 2


def test_duplicate_rows_same_source_retained(sources):
    client, _, _ = sources([row(), row()])
    data = filings.timeline(1, client=client)
    assert len(data) == 1
    assert len(data.records[0].source_records) == 2
    assert {r.provenance.pointer for r in data.records[0].source_records} == {
        "/filings/recent/accessionNumber/0",
        "/filings/recent/accessionNumber/1",
    }


@pytest.mark.parametrize(
    "field,value", [("acceptanceDateTime", "2020-07-01T15:00:00Z"), ("filingDate", "2020-07-01")]
)
def test_conflicting_availability_is_unknown(sources, field, value):
    client, _, _ = sources([row()], [row(**{field: value})])
    data = filings.timeline(1, client=client)
    assert data.records[0].availability.precision == "unknown"
    assert data.records[0].conflicts
    assert len(data.records[0].source_records) == 2
    assert not filings.available_as_of(data, "2026-01-01T00:00:00Z").records
    assert data.issues[0].code == "conflicting_metadata"


def test_conflicting_form_not_guessed(sources):
    client, _, _ = sources([row()], [row(form="10-Q/A")])
    event = filings.timeline(1, client=client).records[0]
    assert event.form is None and event.is_amendment is None
    assert event.conflicts == ("form",)
    assert {r.form for r in event.source_records} == {"10-Q", "10-Q/A"}


def test_complementary_optional_metadata(sources):
    client, _, _ = sources([row(primaryDocument=None)], [row(primaryDocument="report.htm")])
    event = filings.timeline(1, client=client).records[0]
    assert event.primary_document == "report.htm"
    assert event.source_records[0].raw != event.source_records[1].raw


def test_order_determinism_and_unknown_last(sources):
    client, _, _ = sources(
        [row(3), row(2), row(1), row(4, filingDate=None, acceptanceDateTime=None)]
    )
    data = filings.timeline(1, client=client)
    assert [r.accession_number for r in data] == [row(n)["accessionNumber"] for n in (1, 2, 3, 4)]
    assert dumps(data) == dumps(filings.timeline(1, client=client))
    original = [r for event in data for r in event.source_records]
    assert filings._merge(data.cik, list(reversed(original)), []) == data.records


@pytest.mark.parametrize(
    "acceptance,filing,precision",
    [
        ("2020-06-30T15:00:00Z", "2020-06-30", "acceptance_datetime"),
        (None, "2020-06-30", "date_only"),
        ("bad", "2020-06-30", "date_only"),
        ("2020-06-30T15:00:00", "2020-06-30", "date_only"),
        ("2020-06-30T04:00:00Z", "2020-06-30", "date_only"),
        ("2020-01-01T05:00:00Z", "2020-01-01", "date_only"),
        ("2020-06-30T04:00:00Z", None, "unknown"),
        (None, None, "unknown"),
    ],
)
def test_availability_precision(sources, acceptance, filing, precision):
    client, _, _ = sources([row(acceptanceDateTime=acceptance, filingDate=filing)])
    event = filings.timeline(1, client=client).records[0]
    assert event.availability.precision == precision
    assert event.source_records[0].raw["acceptanceDateTime"] == acceptance
    if precision == "date_only":
        assert event.availability.timestamp is None
        assert event.availability.date == date.fromisoformat(filing)


@pytest.mark.parametrize(
    "cutoff,count",
    [("2020-06-30T14:59:59Z", 0), ("2020-06-30T15:00:00Z", 1), ("2020-06-30T11:00:00-04:00", 1)],
)
def test_exact_as_of_boundary(sources, cutoff, count):
    client, _, _ = sources([row()])
    assert len(filings.available_as_of(1, cutoff, client=client)) == count


@pytest.mark.parametrize(
    "filing,cutoff,count",
    [
        ("2020-06-30", "2020-07-01T00:00:00Z", 0),
        ("2020-06-30", "2020-07-01T03:59:59Z", 0),
        ("2020-06-30", "2020-07-01T04:00:00Z", 1),
        ("2020-01-01", "2020-01-02T04:59:59Z", 0),
        ("2020-01-01", "2020-01-02T05:00:00Z", 1),
    ],
)
def test_date_only_as_of_boundary(sources, filing, cutoff, count):
    client, _, _ = sources([row(acceptanceDateTime=None, filingDate=filing)])
    result = filings.available_as_of(1, cutoff, client=client)
    assert len(result) == count
    if count:
        assert result.records[0].availability.timestamp is None


@pytest.mark.parametrize("cutoff", ["2020-01-01", "2020-01-01T12:00:00", "not-a-date", None, 123])
def test_invalid_as_of_before_network(cutoff):
    with pytest.raises(ValidationError):
        filings.available_as_of(1, cutoff)


def test_aware_datetime_cutoff(sources):
    client, _, _ = sources([row()])
    assert (
        len(filings.available_as_of(1, datetime(2020, 6, 30, 15, tzinfo=UTC), client=client)) == 1
    )


def test_missing_history_never_returns_recent_only(sources):
    client, _, _ = sources([row()], references=[{"name": HISTORY}])
    with pytest.raises(CacheMissError, match=HISTORY):
        filings.timeline(1, client=client)


def test_malformed_historical_columns_and_invalid_identity(sources):
    client, _, source = sources(
        [row(accessionNumber="bad")],
        history_payload={
            "accessionNumber": [row(2)["accessionNumber"]],
            "form": ["10-Q", "10-K"],
            "acceptanceDateTime": "bad",
        },
        references=[{"name": HISTORY}],
    )
    parsed = parse_historical_submissions(source, cik=1)
    assert {i.code for i in parsed.issues} == {"column_length", "invalid_record", "invalid_field"}
    data = filings.timeline(1, client=client)
    assert len(data) == 1
    assert "invalid_accession" in {i.code for i in data.issues}


def test_coverage_diagnostics(sources):
    refs = [
        {"name": HISTORY, "filingCount": 9, "filingFrom": "1999-01-01", "filingTo": "2020-06-30"}
    ]
    client, _, _ = sources(
        [
            row(),
            row(2, acceptanceDateTime=None),
            row(3, acceptanceDateTime=None, filingDate=None, form=None),
        ],
        [row(4, form="10-Q/A")],
        refs,
    )
    data = filings.timeline(1, client=client)
    result = filings.coverage(data)
    assert result.total_filings == 4
    assert result.acceptance_timestamps_available == 2
    assert result.date_only_availability_records == 1
    assert result.unknown_availability_records == 1
    assert result.amendments == 1
    assert result.historical_files_loaded == result.historical_files_discovered == 1
    assert result.earliest_filing == result.latest_filing == date(2020, 6, 30)
    assert "history_count_mismatch: 1" in result.potential_gaps
    assert "history_range_mismatch: 1" in result.potential_gaps
    assert result.completeness.startswith("Not asserted")


def test_empty_coverage(sources):
    client, _, _ = sources([])
    result = filings.coverage(1, client=client)
    assert result.total_filings == 0
    assert result.earliest_filing is None
    assert "No usable filing events" in result.potential_gaps


def test_filtered_timeline_retains_cutoff_and_cannot_widen(sources):
    client, _, _ = sources([row()])
    data = filings.available_as_of(1, "2020-06-30T15:00:00Z", client=client)
    assert data.as_of == datetime(2020, 6, 30, 15, tzinfo=UTC)
    assert data.availability_policy == "sec-acceptance-conservative-v1"
    with pytest.raises(ValidationError, match="Cannot widen"):
        filings.available_as_of(data, "2020-07-01T15:00:00Z")
    assert len(filings.available_as_of(data, "2020-06-30T14:00:00Z")) == 0
