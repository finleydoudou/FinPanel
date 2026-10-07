"""Arithmetic reconstructions are not SEC-reported observations."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, localcontext
from types import MappingProxyType
from typing import Literal

from finpanel.errors import ValidationError
from finpanel.metrics.resolver import MetricResult
from finpanel.models.asof import EvidenceEligibility
from finpanel.models.period import PeriodIdentity

DERIVABLE_METRICS = frozenset({"revenue", "net_income", "operating_cash_flow"})


@dataclass(frozen=True)
class QuarterFormula:
    quarter: Literal["Q2", "Q3", "Q4"]
    derivation_type: Literal["ytd_difference", "annual_residual"]
    minuend_period: str
    subtrahend_period: str
    formula: str


FORMULAS = MappingProxyType(
    {
        "Q2": QuarterFormula("Q2", "ytd_difference", "YTD-Q2", "Q1", "YTD-Q2 - YTD-Q1"),
        "Q3": QuarterFormula("Q3", "ytd_difference", "YTD-Q3", "YTD-Q2", "YTD-Q3 - YTD-Q2"),
        "Q4": QuarterFormula("Q4", "annual_residual", "FY", "YTD-Q3", "FY - YTD-Q3"),
    }
)


@dataclass(frozen=True)
class DerivationAvailability:
    derivable_as_of: datetime | None
    selected_evidence_ready_at: datetime | None
    precision: Literal["exact_proxy_inputs", "includes_date_only", "unavailable"]
    evidence: tuple[EvidenceEligibility, ...] = ()
    meaning: str = (
        "Computational eligibility bound for selected evidence, including calendar support; "
        "not SEC publication time or the earliest possible derivation under all source sets"
    )


@dataclass(frozen=True)
class QuarterDerivation:
    cik: str
    metric: str
    fiscal_year: int
    quarter: str
    contract: QuarterFormula | None
    minuend: MetricResult | None
    subtrahend: MetricResult | None
    value: int | Decimal | None
    unit: str | None
    target_interval: PeriodIdentity | None
    as_of: datetime
    revision_policy: str
    status: Literal["eligible", "ineligible", "conflicted", "insufficient_evidence"]
    availability: DerivationAvailability
    reasons: tuple[str, ...]
    diagnostics: tuple[str, ...]
    source_type: Literal["derived"] = "derived"
    policy: str = "exact-concept-reported-cumulative-difference-v1"


def exact_subtract(minuend: int | Decimal, subtrahend: int | Decimal) -> int | Decimal:
    """Subtract exact source numbers without inheriting a caller's Decimal rounding.

    Integers stay integers. Decimal scale follows the operands; this is arithmetic
    precision, not a claim about original XBRL decimals/rounding metadata.
    """
    for value in (minuend, subtrahend):
        if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
            raise ValidationError("Derivation requires exact int or Decimal operands")
        if isinstance(value, Decimal) and not value.is_finite():
            raise ValidationError("Derivation requires finite operands")
    if isinstance(minuend, int) and isinstance(subtrahend, int):
        return minuend - subtrahend
    a, b = Decimal(minuend), Decimal(subtrahend)
    exponent = min(a.as_tuple().exponent, b.as_tuple().exponent)
    adjusted = max(a.adjusted(), b.adjusted())
    with localcontext() as context:
        context.prec = max(1, adjusted - exponent + 3)
        context.Emax = max(context.Emax, adjusted + 2)
        context.Emin = min(context.Emin, exponent)
        return a - b
