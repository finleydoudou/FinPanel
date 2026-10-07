"""Explicit quarter APIs; existing metrics.resolve stays reported-only."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal

from finpanel.errors import ValidationError
from finpanel.filings import _cutoff
from finpanel.metrics.derivation import _request, _unsupported, derive_from_candidates
from finpanel.metrics.derivation_models import (
    DERIVABLE_METRICS,
    FORMULAS,
    QuarterDerivation,
    exact_subtract,
)
from finpanel.metrics.engine import CandidateReport, candidates
from finpanel.metrics.resolver import MetricResult, resolve_candidates
from finpanel.models.period import PeriodIdentity
from finpanel.models.timeline import FilingTimeline
from finpanel.sec.client import SECClient
from finpanel.sec.common import normalize_cik


@dataclass(frozen=True)
class QuarterResolution:
    cik: str
    metric: str
    fiscal_year: int
    quarter: str
    as_of: datetime
    revision_policy: str
    source_policy: str
    state: str
    source_type: Literal["reported", "derived", "none"]
    value: int | Decimal | None
    unit: str | None
    target_interval: PeriodIdentity | None
    reported: MetricResult | None
    derivation: QuarterDerivation | None
    diagnostics: tuple[str, ...]


@dataclass(frozen=True)
class QuarterComparison:
    reported: MetricResult | None
    derived: QuarterDerivation
    status: Literal["equal", "different", "not_comparable", "scope_mismatch", "interval_mismatch"]
    difference: int | Decimal | None
    difference_formula: str = "reported - derived"
    interpretation: str = (
        "Diagnostic only; differences may reflect adjustments, reclassification, "
        "unobserved scope or revision effects. No filing error is inferred."
    )


def derive_quarter(
    cik: str | int,
    metric: str,
    *,
    fiscal_year: int,
    quarter: str,
    as_of: str | datetime,
    revision_policy: str = "latest_available",
    client: SECClient | None = None,
    filing_timeline: FilingTimeline | None = None,
    refresh: bool = False,
) -> QuarterDerivation:
    _request(fiscal_year, quarter, revision_policy)
    cik, cutoff = normalize_cik(cik), _cutoff(as_of)
    if metric not in DERIVABLE_METRICS or quarter not in FORMULAS:
        return _unsupported(cik, metric, fiscal_year, quarter, cutoff, revision_policy)
    report = candidates(
        cik, metric, as_of=cutoff, client=client, filing_timeline=filing_timeline, refresh=refresh
    )
    return derive_from_candidates(
        report, fiscal_year=fiscal_year, quarter=quarter, revision_policy=revision_policy
    )


def resolve_quarter_candidates(
    report: CandidateReport,
    *,
    fiscal_year: int,
    quarter: str,
    revision_policy: str = "latest_available",
    source_policy: str = "reported_only",
) -> QuarterResolution:
    _request(fiscal_year, quarter, revision_policy)
    if source_policy not in {"reported_only", "reported_then_derived"}:
        raise ValidationError("source_policy must be reported_only or reported_then_derived")
    if report.metric not in DERIVABLE_METRICS:
        return QuarterResolution(
            report.cik,
            report.metric,
            fiscal_year,
            quarter,
            report.as_of,
            revision_policy,
            source_policy,
            "unsupported",
            "none",
            None,
            None,
            None,
            None,
            None,
            ("unsupported_quarter_metric",),
        )
    reported = resolve_candidates(
        report, fiscal_year=fiscal_year, period=quarter, revision_policy=revision_policy
    )
    derivation = None
    state, source, value = reported.state, "none", None
    unit, interval = None, None
    diagnostics = []
    if reported.state == "resolved":
        source, value, unit, interval = (
            "reported",
            reported.value,
            reported.unit,
            reported.represented_period,
        )
        diagnostics.append("direct_reported_value_preferred")
    elif (
        source_policy == "reported_then_derived"
        and reported.state == "unavailable"
        and not reported.target_rejections
        and quarter in FORMULAS
    ):
        derivation = derive_from_candidates(
            report, fiscal_year=fiscal_year, quarter=quarter, revision_policy=revision_policy
        )
        if derivation.status == "eligible":
            state, source, value = "resolved", "derived", derivation.value
            unit, interval = derivation.unit, derivation.target_interval
        else:
            state = "conflicted" if derivation.status == "conflicted" else "unavailable"
            diagnostics.extend(derivation.reasons)
    else:
        diagnostics.append("reported_uncertainty_not_repaired_by_arithmetic")
    return QuarterResolution(
        report.cik,
        report.metric,
        fiscal_year,
        quarter,
        report.as_of,
        revision_policy,
        source_policy,
        state,
        source,
        value,
        unit,
        interval,
        reported,
        derivation,
        tuple(diagnostics),
    )


def resolve_quarter(
    cik: str | int,
    metric: str,
    *,
    fiscal_year: int,
    quarter: str,
    as_of: str | datetime,
    revision_policy: str = "latest_available",
    source_policy: str = "reported_only",
    client: SECClient | None = None,
    filing_timeline: FilingTimeline | None = None,
    refresh: bool = False,
) -> QuarterResolution:
    _request(fiscal_year, quarter, revision_policy)
    return resolve_quarter_candidates(
        candidates(
            cik,
            metric,
            as_of=as_of,
            client=client,
            filing_timeline=filing_timeline,
            refresh=refresh,
        ),
        fiscal_year=fiscal_year,
        quarter=quarter,
        revision_policy=revision_policy,
        source_policy=source_policy,
    )


def compare_quarter_candidates(
    report: CandidateReport,
    *,
    fiscal_year: int,
    quarter: str,
    revision_policy: str = "latest_available",
) -> QuarterComparison:
    derived = derive_from_candidates(
        report, fiscal_year=fiscal_year, quarter=quarter, revision_policy=revision_policy
    )
    reported = (
        resolve_candidates(
            report, fiscal_year=fiscal_year, period=quarter, revision_policy=revision_policy
        )
        if report.metric in DERIVABLE_METRICS
        else None
    )
    if reported is None or reported.state != "resolved" or derived.status != "eligible":
        return QuarterComparison(reported, derived, "not_comparable", None)
    reported_scopes = {(c.mapping.taxonomy, c.mapping.concept) for c in reported.selected}
    derived_scopes = {(c.mapping.taxonomy, c.mapping.concept) for c in derived.minuend.selected}
    if reported.unit != derived.unit or reported_scopes != derived_scopes:
        return QuarterComparison(reported, derived, "scope_mismatch", None)
    if reported.represented_period != derived.target_interval:
        return QuarterComparison(reported, derived, "interval_mismatch", None)
    difference = exact_subtract(reported.value, derived.value)
    return QuarterComparison(
        reported, derived, "equal" if difference == 0 else "different", difference
    )


def compare_quarter(
    cik: str | int,
    metric: str,
    *,
    fiscal_year: int,
    quarter: str,
    as_of: str | datetime,
    revision_policy: str = "latest_available",
    client: SECClient | None = None,
    filing_timeline: FilingTimeline | None = None,
    refresh: bool = False,
) -> QuarterComparison:
    _request(fiscal_year, quarter, revision_policy)
    return compare_quarter_candidates(
        candidates(
            cik,
            metric,
            as_of=as_of,
            client=client,
            filing_timeline=filing_timeline,
            refresh=refresh,
        ),
        fiscal_year=fiscal_year,
        quarter=quarter,
        revision_policy=revision_policy,
    )
