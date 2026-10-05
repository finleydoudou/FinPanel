from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from finpanel.models.source import Provenance


@dataclass(frozen=True)
class Filing:
    cik: str
    entity_name: str | None
    accession_number: str
    filing_date: date | None
    report_date: date | None
    acceptance_datetime: datetime | None
    form: str | None
    primary_document: str | None
    fiscal_year_end: str | None
    provenance: Provenance
    raw: dict[str, Any]
