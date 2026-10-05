"""Derived filing events keep all source rows and explicit availability precision."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal

from finpanel.models.filing import Filing
from finpanel.models.source import ParseIssue, Provenance


@dataclass(frozen=True)
class HistoricalReference:
    cik: str
    name: str
    filing_count: int | None
    filing_from: date | None
    filing_to: date | None
    provenance: Provenance
    raw: dict[str, Any]


@dataclass(frozen=True)
class Availability:
    precision: Literal["acceptance_datetime", "date_only", "unknown"]
    timestamp: datetime | None = None
    date: date | None = None
    reason: str = ""


@dataclass(frozen=True)
class FilingEvent:
    cik: str
    accession_number: str
    form: str | None
    filing_date: date | None
    report_date: date | None
    acceptance_datetime: datetime | None
    primary_document: str | None
    is_amendment: bool | None
    availability: Availability
    conflicts: tuple[str, ...]
    source_records: tuple[Filing, ...]


@dataclass(frozen=True)
class FilingTimeline:
    cik: str
    records: tuple[FilingEvent, ...]
    issues: tuple[ParseIssue, ...]
    sources: tuple[Provenance, ...]
    historical_references: tuple[HistoricalReference, ...]
    historical_files_loaded: tuple[str, ...]
    as_of: datetime | None = None
    availability_policy: str = "sec-acceptance-conservative-v1"

    def __iter__(self) -> Iterator[FilingEvent]:
        return iter(self.records)

    def __len__(self) -> int:
        return len(self.records)


@dataclass(frozen=True)
class Coverage:
    cik: str
    earliest_filing: date | None
    latest_filing: date | None
    total_filings: int
    form_counts: dict[str, int]
    amendments: int
    acceptance_timestamps_available: int
    date_only_availability_records: int
    unknown_availability_records: int
    overlapping_accessions: int
    source_records: int
    historical_files_discovered: int
    historical_files_loaded: int
    potential_gaps: tuple[str, ...]
    completeness: str = "Not asserted; diagnostics cannot establish universal completeness"
