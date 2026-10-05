from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from finpanel.models.source import Provenance


@dataclass(frozen=True)
class FactObservation:
    cik: str
    entity_name: str | None
    taxonomy: str
    concept: str
    label: str | None
    description: str | None
    unit: str
    value: int | Decimal
    accession_number: str | None
    form: str | None
    filing_date: date | None
    report_date: date | None
    fiscal_year: int | None
    fiscal_period: str | None
    period_start: date | None
    period_end: date | None
    frame: str | None
    provenance: Provenance
    raw: dict[str, Any]
