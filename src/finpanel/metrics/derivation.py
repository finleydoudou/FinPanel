"""Strict same-concept cumulative arithmetic above the reported canonical engine."""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Literal

from finpanel.errors import ValidationError
from finpanel.metrics.derivation_models import (
    DERIVABLE_METRICS,
    FORMULAS,
    DerivationAvailability,
    QuarterDerivation,
    exact_subtract,
)
from finpanel.metrics.engine import CandidateReport
from finpanel.metrics.resolver import MetricResult, resolve_candidates
from finpanel.models.period import PeriodIdentity


@dataclass(frozen=True)
class OperandEligibility:
    status: Literal["eligible", "ineligible", "conflicted", "insufficient_evidence"]
    reasons: tuple[str, ...]
    target_interval: PeriodIdentity | None = None
    diagnostics: tuple[str, ...] = (
        "company_level_scope_only; original_instance_dimensions_not_proven_equal",
        "source_decimals_metadata_unavailable; arithmetic_precision_is_not_measurement_precision",
    )


def operand_eligibility(
    minuend: MetricResult,
    subtrahend: MetricResult,
    *,
    fiscal_year: int,
    quarter: str,
) -> OperandEligibility:
    """Validate resolved operands and recheck their canonical evidence before arithmetic."""
    a, b = minuend, subtrahend
    reasons = []
    formula = FORMULAS.get(quarter)
    if formula is None:
        reasons.append("unsupported_quarter_formula")
    if a.metric not in DERIVABLE_METRICS or b.metric not in DERIVABLE_METRICS:
        reasons.append("unsupported_derived_metric")
    for name in ("cik", "metric", "as_of", "revision_policy", "evidence_snapshot_id"):
        if getattr(a, name) != getattr(b, name):
            reasons.append(f"{name}_mismatch")
    if a.unit is not None and b.unit is not None and a.unit != b.unit:
        reasons.append("unit_mismatch")
    if a.source_type != "reported" or b.source_type != "reported":
        reasons.append("operands_must_be_reported")
    if reasons:
        return OperandEligibility("ineligible", tuple(reasons))
    if a.state != "resolved" or b.state != "resolved":
        reasons = tuple(
            f"{label}:{r.state}:{reason}"
            for label, r in (("minuend", a), ("subtrahend", b))
            for reason in (
                *r.conflicts,
                *r.diagnostics,
                *(x for reject in r.target_rejections for x in reject.reasons),
            )
        )
        status = (
            "conflicted"
            if any(r.state == "conflicted" for r in (a, b))
            else "insufficient_evidence"
        )
        return OperandEligibility(status, reasons or ("unresolved_operand",))
    if not a.selected or not b.selected or a.value is None or b.value is None:
        return OperandEligibility("insufficient_evidence", ("missing_operand_provenance",))
    scopes = [{(c.mapping.taxonomy, c.mapping.concept) for c in r.selected} for r in (a, b)]
    if scopes[0] != scopes[1] or len(scopes[0]) != 1:
        return OperandEligibility("ineligible", ("exact_concept_mismatch",))
    if next(iter(scopes[0]))[0] != "us-gaap":
        return OperandEligibility("ineligible", ("unsupported_taxonomy",))
    pa, pb = a.represented_period, b.represented_period
    if pa is None or pb is None:
        return OperandEligibility("insufficient_evidence", ("missing_period_identity",))
    if pa.fiscal_year != fiscal_year or pb.fiscal_year != fiscal_year:
        return OperandEligibility("ineligible", ("fiscal_year_mismatch",))
    if pa.label != formula.minuend_period or pb.label != formula.subtrahend_period:
        return OperandEligibility("ineligible", ("operand_period_label_mismatch",))
    if None in (pa.start, pa.end, pb.start, pb.end):
        return OperandEligibility("insufficient_evidence", ("incomplete_interval",))
    if pa.start != pb.start:
        return OperandEligibility("ineligible", ("fiscal_start_mismatch",))
    if not pa.start <= pb.end < pa.end:
        return OperandEligibility("ineligible", ("invalid_interval_order",))
    windows = []
    for label, r in ((formula.minuend_period, a), (formula.subtrahend_period, b)):
        for c in r.selected:
            p = c.observation.period
            expected_kind = (
                "annual" if label == "FY" else "single_quarter" if label == "Q1" else "year_to_date"
            )
            if p.kind != expected_kind or (label != "FY" and p.is_year_to_date is not True):
                return OperandEligibility("ineligible", ("incompatible_normalized_period",))
            if p.mode != "as_of" or p.as_of != r.as_of:
                return OperandEligibility("ineligible", ("period_outside_asof_boundary",))
        ids = {c.observation.fact.observation_id for c in r.selected}
        observed = set()
        for view in r.candidates.evidence:
            if any(c.fact.observation_id in ids for c in view.records) and view.calendar:
                if fiscal_year in view.calendar.ambiguous_years:
                    return OperandEligibility(
                        "insufficient_evidence", ("ambiguous_fiscal_calendar",)
                    )
                observed.update(
                    (y.start, y.end) for y in view.calendar.years if y.fiscal_year == fiscal_year
                )
        windows.append(observed)
        try:
            verified = resolve_candidates(
                r.candidates, **r.query, revision_policy=r.revision_policy
            )
        except ValidationError:
            return OperandEligibility("ineligible", ("invalid_canonical_evidence",))
        if replace(r, evidence_snapshot_id=None) != verified:
            return OperandEligibility("ineligible", ("canonical_resolution_mismatch",))
    if len(windows[0]) != 1 or windows[0] != windows[1]:
        return OperandEligibility("ineligible", ("fiscal_calendar_mismatch",))
    year_start, year_end = next(iter(windows[0]))
    if pa.start != year_start or pa.end > year_end or (quarter == "Q4" and pa.end != year_end):
        return OperandEligibility("ineligible", ("interval_outside_fiscal_window",))
    return OperandEligibility(
        "eligible",
        (),
        PeriodIdentity(
            a.cik,
            pb.end + timedelta(days=1),
            pa.end,
            fiscal_year,
            quarter,
        ),
    )


def _revision_pairing(a: MetricResult, b: MetricResult):
    diagnostics, conflicts = [], []
    accessions = [
        {c.observation.fact.observation.accession_number for c in r.selected} for r in (a, b)
    ]
    shared = bool(accessions[0] & accessions[1])
    diagnostics.append("shared_filing_operands" if shared else "cross_filing_operands")
    changed, amended = [], []
    for r in (a, b):
        ids = {c.observation.fact.observation_id for c in r.selected}
        groups = [
            g
            for g in r.revision_groups
            if ids & {c.observation.fact.observation_id for c in g.candidates}
        ]
        changed.append(
            any(
                len({c.observation.fact.observation.value for c in g.candidates}) > 1
                for g in groups
            )
        )
        amended.append(any(c.observation.fact.filing.is_amendment for c in r.selected))
    if any(changed):
        diagnostics.append("operand_value_revision_history")
    if changed[0] != changed[1] or amended[0] != amended[1]:
        diagnostics.append("different_observed_revision_states")
    if any(amended) and not shared:
        conflicts.append("unpaired_amendment")
    if a.revision_policy == "first_reported":
        diagnostics.append("constructed_from_first_reported_components; not_a_reported_quarter")
    elif a.revision_policy == "latest_available" and not shared:
        # Individually unique latest values do not prove a coherent restatement
        # pair. A shared filing must corroborate a changed/amended selection.
        if any(changed):
            conflicts.append("unpaired_value_revision")
    return tuple(conflicts), tuple(diagnostics)


def _readiness(a: MetricResult, b: MetricResult) -> DerivationAvailability:
    from datetime import UTC, datetime, time

    from finpanel.asof import eligibility
    from finpanel.filings import SEC_DAY_ZONE
    from finpanel.serialization import dumps

    evidence = {}
    for r in (a, b):
        for c in r.selected:
            record = c.observation
            decisions = [record.eligibility, *record.supporting_evidence]
            event = record.fact.filing
            decisions.append(
                eligibility(
                    event.source_records[0].provenance,
                    event.accession_number,
                    event.availability,
                    r.as_of,
                    role="filing",
                )
            )
            for d in decisions:
                if not d.eligible_as_of or d.as_of != a.as_of:
                    raise ValidationError("Derivation readiness contains ineligible evidence")
                evidence[dumps(d)] = d
    times, date_only = [], False
    for d in evidence.values():
        availability = d.source_availability
        if availability.precision == "acceptance_datetime":
            times.append(availability.timestamp)
        elif availability.precision == "date_only":
            date_only = True
            times.append(
                datetime.combine(
                    availability.date + timedelta(days=1), time.min, SEC_DAY_ZONE
                ).astimezone(UTC)
            )
        else:
            raise ValidationError("Unknown availability cannot establish derivation readiness")
    bound = max(times)
    if bound > a.as_of:
        raise ValidationError("Derivation evidence is not ready at cutoff")
    return DerivationAvailability(
        a.as_of,
        bound,
        "includes_date_only" if date_only else "exact_proxy_inputs",
        tuple(evidence[k] for k in sorted(evidence)),
    )


def derive_operands(
    minuend: MetricResult,
    subtrahend: MetricResult,
    *,
    fiscal_year: int,
    quarter: str,
) -> QuarterDerivation:
    """Revalidate canonical resolutions before using their values as operands."""
    _request(fiscal_year, quarter, minuend.revision_policy)
    if minuend.evidence_snapshot_id != subtrahend.evidence_snapshot_id:
        raise ValidationError("Arithmetic operands must belong to the same evidence snapshot")

    check = operand_eligibility(minuend, subtrahend, fiscal_year=fiscal_year, quarter=quarter)
    status, reasons = check.status, check.reasons
    diagnostics = check.diagnostics
    ready = DerivationAvailability(None, None, "unavailable")
    value = None
    if status == "eligible":
        conflicts, revision_diagnostics = _revision_pairing(minuend, subtrahend)
        diagnostics += revision_diagnostics
        if conflicts:
            status, reasons = "conflicted", conflicts
        else:
            ready = _readiness(minuend, subtrahend)
            value = exact_subtract(minuend.value, subtrahend.value)
    return QuarterDerivation(
        minuend.cik,
        minuend.metric,
        fiscal_year,
        quarter,
        FORMULAS.get(quarter),
        minuend,
        subtrahend,
        value,
        minuend.unit if minuend.unit == subtrahend.unit else None,
        check.target_interval,
        minuend.as_of,
        minuend.revision_policy,
        status,
        ready,
        reasons,
        diagnostics,
        evidence_snapshot_id=minuend.evidence_snapshot_id,
    )


def _request(fiscal_year, quarter, revision_policy):
    from finpanel.revisions import validate_policy

    validate_policy(revision_policy)
    if (
        not isinstance(fiscal_year, int)
        or isinstance(fiscal_year, bool)
        or not 1 <= fiscal_year <= 9999
    ):
        raise ValidationError("fiscal_year must be an integer from 1 through 9999")
    if quarter not in {"Q1", "Q2", "Q3", "Q4"}:
        raise ValidationError("quarter must be Q1, Q2, Q3 or Q4")


def _unsupported(
    cik: str,
    metric: str,
    fiscal_year: int,
    quarter: str,
    cutoff: datetime,
    revision_policy: str,
) -> QuarterDerivation:

    reasons = []
    if metric not in DERIVABLE_METRICS:
        reasons.append("unsupported_derived_metric")
    if quarter not in FORMULAS:
        reasons.append("q1_is_reported_only")
    return QuarterDerivation(
        cik,
        metric,
        fiscal_year,
        quarter,
        FORMULAS.get(quarter),
        None,
        None,
        None,
        None,
        None,
        cutoff,
        revision_policy,
        "ineligible",
        DerivationAvailability(None, None, "unavailable"),
        tuple(reasons),
        (),
    )


def derive_from_candidates(
    report: CandidateReport,
    *,
    fiscal_year: int,
    quarter: str,
    revision_policy: str = "latest_available",
) -> QuarterDerivation:
    """Resolve both operands from one bounded candidate set before subtracting."""
    _request(fiscal_year, quarter, revision_policy)
    if report.metric not in DERIVABLE_METRICS or quarter not in FORMULAS:
        return _unsupported(
            report.cik, report.metric, fiscal_year, quarter, report.as_of, revision_policy
        )
    formula = FORMULAS[quarter]
    a, b = (
        resolve_candidates(
            report, fiscal_year=fiscal_year, period=label, revision_policy=revision_policy
        )
        for label in (formula.minuend_period, formula.subtrahend_period)
    )
    return derive_operands(a, b, fiscal_year=fiscal_year, quarter=quarter)
