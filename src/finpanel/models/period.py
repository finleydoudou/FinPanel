"""Derived fiscal interpretations; all dates and labels remain separate from SEC fields."""

from dataclasses import dataclass
from datetime import date
from typing import Literal

from finpanel.models.evidence import Diagnostic, Evidence


@dataclass(frozen=True)
class FiscalYearWindow:
    cik: str
    fiscal_year: int
    start: date
    end: date
    evidence: tuple[Evidence, ...]
    method: str = "annual_context_matches_filing_report_end"


@dataclass(frozen=True)
class QuarterBoundary:
    fiscal_year: int
    quarter: int
    end: date
    evidence: tuple[Evidence, ...]


@dataclass(frozen=True)
class FiscalCalendar:
    cik: str
    years: tuple[FiscalYearWindow, ...] = ()
    quarters: tuple[QuarterBoundary, ...] = ()
    ambiguous_years: tuple[int, ...] = ()
    current_year_end_hints: tuple[str, ...] = ()
    evidence: tuple[Evidence, ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()
    policy: str = "observed-fiscal-windows-v1"


@dataclass(frozen=True)
class PeriodIdentity:
    cik: str
    start: date | None
    end: date | None
    fiscal_year: int | None = None
    label: str | None = None


@dataclass(frozen=True)
class PeriodClassification:
    kind: Literal[
        "instant",
        "annual",
        "single_quarter",
        "year_to_date",
        "other_duration",
        "ambiguous",
        "unknown",
    ]
    start: date | None
    end: date | None
    duration_days: int | None
    method: str
    status: Literal["observed_shape", "rule_supported", "ambiguous", "insufficient_data"]
    identity: PeriodIdentity
    is_single_quarter: bool | None
    is_year_to_date: bool | None
    evidence: tuple[Evidence, ...]
    diagnostics: tuple[Diagnostic, ...]
    policy: str = "reported-context-periods-v1"
