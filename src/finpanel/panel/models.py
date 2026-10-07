"""Explicit Cartesian requests and lossless long-form research rows."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from itertools import product

from finpanel.errors import ValidationError
from finpanel.filings import _cutoff
from finpanel.metrics.registry import REGISTRY
from finpanel.revisions import validate_policy
from finpanel.sec.common import normalize_cik

SCHEMA = "finpanel-long-panel-v1"
PERIODS = ("FY", "Q1", "Q2", "Q3", "Q4", "YTD-Q2", "YTD-Q3")
STATES = frozenset(
    {
        "resolved_reported",
        "resolved_derived",
        "unavailable",
        "conflicted",
        "ambiguous_period",
        "unsupported",
        "insufficient_evidence",
        "source_verification_failed",
    }
)


@dataclass(frozen=True)
class PeriodEnd:
    """Caller-supplied fiscal-label/date association for instant metrics, not inferred."""

    cik: str
    fiscal_year: int
    period: str
    end: date

    def __post_init__(self):
        object.__setattr__(self, "cik", normalize_cik(self.cik))
        if isinstance(self.end, str):
            try:
                object.__setattr__(self, "end", date.fromisoformat(self.end))
            except ValueError as exc:
                raise ValidationError("Invalid explicit period end") from exc
        if (
            type(self.end) is not date
            or self.period not in PERIODS
            or type(self.fiscal_year) is not int
            or not 1 <= self.fiscal_year <= 9999
        ):
            raise ValidationError("Invalid explicit period end")


@dataclass(frozen=True)
class PanelRequest:
    entities: tuple[str, ...]
    metrics: tuple[str, ...]
    fiscal_years: tuple[int, ...]
    periods: tuple[str, ...]
    as_of: tuple[datetime, ...]
    revision_policy: str = "latest_available"
    source_policy: str = "reported_then_derived"
    source_verification: str = "off"
    snapshot_id: str | None = None
    period_ends: tuple[PeriodEnd, ...] = ()
    errors: str = "collect"
    timeline_scope: str = "complete"

    def __post_init__(self):
        for name in ("entities", "metrics", "fiscal_years", "periods", "as_of"):
            values = getattr(self, name)
            if isinstance(values, (str, bytes)) or not values:
                raise ValidationError(f"{name} must be a nonempty sequence")
        if any(m not in REGISTRY for m in self.metrics):
            raise ValidationError("Only the six registered canonical metrics are supported")
        if any(p not in PERIODS for p in self.periods):
            raise ValidationError("Invalid normalized period")
        if any(type(y) is not int or not 1 <= y <= 9999 for y in self.fiscal_years):
            raise ValidationError("Fiscal years must be integers from 1 to 9999")
        if self.timeline_scope not in {"complete", "recent_only"}:
            raise ValidationError("timeline_scope must be complete or recent_only")
        validate_policy(self.revision_policy)
        if self.source_policy not in {"reported_only", "reported_then_derived", "derived_only"}:
            raise ValidationError("Invalid source policy")
        if self.source_verification not in {"off", "best_effort", "required"}:
            raise ValidationError("Invalid source verification policy")
        if self.errors not in {"collect", "raise"}:
            raise ValidationError("errors must be collect or raise")
        if self.snapshot_id is not None and (
            not isinstance(self.snapshot_id, str)
            or len(self.snapshot_id) != 64
            or any(c not in "0123456789abcdef" for c in self.snapshot_id)
        ):
            raise ValidationError("snapshot_id must be a SHA-256 identity")
        for name, values in (
            ("entities", [normalize_cik(c) for c in self.entities]),
            ("metrics", self.metrics),
            ("fiscal_years", self.fiscal_years),
            ("as_of", [_cutoff(c) for c in self.as_of]),
        ):
            object.__setattr__(self, name, tuple(sorted(set(values))))
        object.__setattr__(self, "periods", tuple(p for p in PERIODS if p in self.periods))
        ends = {}
        for item in self.period_ends:
            item = PeriodEnd(**item) if isinstance(item, dict) else item
            if not isinstance(item, PeriodEnd):
                raise ValidationError("period_ends requires PeriodEnd records")
            key = (item.cik, item.fiscal_year, item.period)
            if (
                item.cik not in self.entities
                or item.fiscal_year not in self.fiscal_years
                or item.period not in self.periods
            ):
                raise ValidationError("Explicit date lies outside requested grid")
            if key in ends and ends[key] != item:
                raise ValidationError("Conflicting explicit dates")
            ends[key] = item
        object.__setattr__(self, "period_ends", tuple(ends[k] for k in sorted(ends)))

    def grid(self):
        return product(self.entities, self.as_of, self.fiscal_years, self.periods, self.metrics)

    def instant_end(self, cik, year, period):
        return next(
            (
                x.end
                for x in self.period_ends
                if (x.cik, x.fiscal_year, x.period) == (cik, year, period)
            ),
            None,
        )


@dataclass(frozen=True)
class PanelRow:
    row_id: str
    cik: str
    entity_name: str | None
    ticker: str | None
    metric: str
    fiscal_year: int
    period: str
    period_start: date | None
    period_end: date | None
    as_of: datetime
    revision_policy: str
    source_policy: str
    state: str
    value: int | Decimal | None
    unit: str | None
    source_type: str | None
    source_concepts: tuple[str, ...]
    source_taxonomies: tuple[str, ...]
    accessions: tuple[str, ...]
    filing_availability: tuple[dict, ...]
    verification_state: str
    snapshot_id: str | None
    evidence_mode: str
    receipt_id: str
    reasons: tuple[str, ...]
    conflicts: tuple[str, ...]

    def __post_init__(self):
        if self.state not in STATES:
            raise ValidationError("Invalid panel row state")
        if self.value is not None:
            if type(self.value) not in (int, Decimal) or (
                isinstance(self.value, Decimal) and not self.value.is_finite()
            ):
                raise ValidationError("Panel values must be finite exact int/Decimal")
            if not self.state.startswith("resolved_"):
                raise ValidationError("Unresolved rows cannot expose scalar values")
