"""Evidence refers to raw source fields, not assertions of public dissemination."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal

from finpanel.models.source import Provenance


@dataclass(frozen=True)
class Evidence:
    field: str
    raw_value: Any
    source: Provenance
    interpretation: str = "As supplied by SEC"


@dataclass(frozen=True)
class Diagnostic:
    category: Literal[
        "verified_inconsistency", "missing_data", "precision_limitation", "heuristic_warning"
    ]
    code: str
    message: str
    sources: tuple[Provenance, ...] = ()


@dataclass(frozen=True)
class FilingHeader:
    accession_number: str | None
    ciks: tuple[str, ...]
    form: str | None
    filing_date: date | None
    report_date: date | None
    acceptance_datetime: datetime | None
    acceptance_raw: str | None
    timezone_policy: str
    public_document_count: int | None
    evidence: tuple[Evidence, ...]
    diagnostics: tuple[Diagnostic, ...]
    provenance: Provenance
    raw_fields: dict[str, tuple[str, ...]]
