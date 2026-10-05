"""Parse recent submission columns without merging amendments or fetching history."""

from datetime import date, datetime

from finpanel.models import Filing, ParseResult, RawResponse
from finpanel.sec.common import Reader, normalize_cik, pointer


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
    valid = {}
    for key, value in sorted(columns.items()):
        if isinstance(value, list):
            valid[key] = value
        else:
            reader.issue(pointer("filings", "recent", key), value, "Expected array")
    count = max((len(v) for v in valid.values()), default=0)
    for key, value in valid.items():
        if len(value) != count:
            reader.issue(
                pointer("filings", "recent", key),
                value,
                "Column length differs; missing cells remain missing",
                "column_length",
            )
    records = []
    for i in range(count):
        row = {key: values[i] for key, values in valid.items() if i < len(values)}
        # Rows come from column arrays; provenance identifies the accession cell.
        path = pointer("filings", "recent")
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
