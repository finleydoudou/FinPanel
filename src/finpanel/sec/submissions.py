"""Parse recent and historical submission columns, preserving their original paths."""

from datetime import date, datetime
from typing import Any

from finpanel.errors import ValidationError
from finpanel.models import Filing, ParseResult, RawResponse
from finpanel.models.timeline import HistoricalReference
from finpanel.sec.common import Reader, historical_filename, normalize_cik, pointer


def parse_submissions(response: RawResponse) -> ParseResult[Filing]:
    data = response.json()
    cik = normalize_cik(data.get("cik"))
    reader = Reader(response)
    name = reader.optional(data, "name", str, "")
    year_end = reader.optional(data, "fiscalYearEnd", str, "")
    filings = data.get("filings")
    if not isinstance(filings, dict):
        reader.issue("/filings", filings, "Expected filings object", "invalid_container")
        filings = {}
    columns = filings.get("recent")
    if not isinstance(columns, dict):
        reader.issue("/filings/recent", columns, "Expected column arrays", "invalid_container")
        columns = {}
    records = _parse_columns(columns, reader, cik, name, year_end, "/filings/recent")
    return ParseResult(
        tuple(records),
        tuple(reader.issues),
        response.provenance(""),
        {
            "fiscal_year_end": year_end,
            "history_files": filings.get("files", []),
            "scope": "recent_only",
        },
    )


def _parse_columns(
    columns: dict[str, Any],
    reader: Reader,
    cik: str,
    name: str | None,
    year_end: str | None,
    path: str,
) -> list[Filing]:
    response = reader.response
    valid = {}
    for key, value in sorted(columns.items()):
        if isinstance(value, list):
            valid[key] = value
        else:
            reader.issue(path + pointer(key), value, "Expected array")
    count = max((len(v) for v in valid.values()), default=0)
    for key, value in valid.items():
        if len(value) != count:
            reader.issue(
                path + pointer(key),
                value,
                "Column length differs; missing cells remain missing",
                "column_length",
            )
    records = []
    for i in range(count):
        row = {key: values[i] for key, values in valid.items() if i < len(values)}
        # Rows come from column arrays; provenance identifies the accession cell.
        local = Reader(response)
        accn = local.optional(row, "accessionNumber", str, "")
        fields = {
            "filing_date": local.optional(row, "filingDate", date, ""),
            "report_date": local.optional(row, "reportDate", date, ""),
            "acceptance_datetime": local.optional(row, "acceptanceDateTime", datetime, ""),
            "form": local.optional(row, "form", str, ""),
            "primary_document": local.optional(row, "primaryDocument", str, ""),
        }
        for issue in local.issues:
            reader.issue(path + issue.provenance.pointer + f"/{i}", issue.raw, issue.message)
        if accn is None:
            reader.issue(
                path + f"/accessionNumber/{i}",
                row,
                "Filing lacks usable accession number",
                "invalid_record",
            )
            continue
        records.append(
            Filing(
                cik,
                name,
                accn,
                **fields,
                fiscal_year_end=year_end,
                provenance=response.provenance(path + f"/accessionNumber/{i}"),
                raw=row,
            )
        )
    return records


def parse_historical_submissions(
    response: RawResponse,
    *,
    cik: str | int,
    entity_name: str | None = None,
    fiscal_year_end: str | None = None,
) -> ParseResult[Filing]:
    """Historical files are root-level columns; issuer context comes from the parent."""
    cik = normalize_cik(cik)
    data = response.json()
    reader = Reader(response)
    if "accessionNumber" not in data:
        reader.issue("", data, "Historical response lacks accessionNumber", "invalid_container")
    records = _parse_columns(data, reader, cik, entity_name, fiscal_year_end, "")
    return ParseResult(
        tuple(records),
        tuple(reader.issues),
        response.provenance(""),
        {"scope": "historical_file", "cik_context": "parent_submissions"},
    )


def discover_historical_submissions(response: RawResponse) -> ParseResult[HistoricalReference]:
    data = response.json()
    cik = normalize_cik(data.get("cik"))
    reader = Reader(response)
    filings = data.get("filings")
    references = filings.get("files") if isinstance(filings, dict) else None
    if not isinstance(references, list):
        reader.issue(
            "/filings/files",
            references,
            "Historical file list missing or malformed; coverage cannot be established",
            "invalid_history_references",
        )
        references = []
    records = []
    for i, row in enumerate(references):
        path = pointer("filings", "files", i)
        if not isinstance(row, dict):
            reader.issue(
                path, row, "Expected historical file reference object", "invalid_reference"
            )
            continue
        try:
            name = historical_filename(cik, row.get("name"))
        except ValidationError as exc:
            reader.issue(path, row, str(exc), "invalid_reference")
            continue
        count = reader.optional(row, "filingCount", int, path)
        if count is not None and count < 0:
            reader.issue(path + "/filingCount", count, "Expected nonnegative filing count")
            count = None
        start = reader.optional(row, "filingFrom", date, path)
        end = reader.optional(row, "filingTo", date, path)
        if start is not None and end is not None and start > end:
            reader.issue(path, row, "Historical date range is reversed", "invalid_reference_range")
        records.append(
            HistoricalReference(cik, name, count, start, end, response.provenance(path), row)
        )
    return ParseResult(tuple(records), tuple(reader.issues), response.provenance(""))
