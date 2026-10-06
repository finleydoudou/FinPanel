from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from finpanel.models.context import FactContext
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

    @property
    def observation_id(self) -> str:
        """Stable identity of a response observation, not of an economic value."""
        from hashlib import sha256

        from finpanel.serialization import dumps

        return sha256(dumps(self.provenance).encode()).hexdigest()

    @property
    def context(self) -> FactContext:
        if self.period_start is not None and self.period_end is not None:
            if self.period_start <= self.period_end:
                return FactContext(
                    "duration",
                    self.period_start,
                    self.period_end,
                    (self.period_end - self.period_start).days + 1,
                    "Observed start/end; inclusive calendar-day count",
                )
        elif "start" not in self.raw and self.period_end is not None:
            return FactContext(
                "instant",
                None,
                self.period_end,
                None,
                "Observed end with absent start; not taxonomy-validated",
            )
        return FactContext(
            "unknown",
            self.period_start,
            self.period_end,
            None,
            "Missing, invalid or reversed period fields",
        )
