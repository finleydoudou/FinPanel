"""Reported scalars only; exact-concept temporal ordering belongs to Phase 0E."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from finpanel import revisions
from finpanel.errors import ValidationError
from finpanel.metrics.engine import (
    CandidateReport,
    MetricCandidate,
    RejectedObservation,
    _reasons,
    _rejections,
    candidates,
)
from finpanel.metrics.registry import REGISTRY, mapping_for
from finpanel.models.period import PeriodIdentity
from finpanel.models.timeline import FilingTimeline
from finpanel.sec.client import SECClient


@dataclass(frozen=True)
class MetricResult:
    cik: str
    metric: str
    as_of: datetime
    state: Literal["resolved", "conflicted", "unavailable", "unsupported", "ambiguous_period"]
    revision_policy: str
    query: dict
    value: int | Decimal | None
    unit: str | None
    represented_period: PeriodIdentity | None
    selected: tuple[MetricCandidate, ...]
    considered: tuple[MetricCandidate, ...]
    target_rejections: tuple[RejectedObservation, ...]
    conflicts: tuple[str, ...]
    diagnostics: tuple[str, ...]
    candidates: CandidateReport
    revision_groups: tuple[revisions.RevisionGroup, ...]
    mapping_policy: str = "lowest-numeric-priority; distinct-concepts-never-assumed-equivalent"
    source_type: Literal["reported"] = "reported"

    evidence_snapshot_id: str | None = None

    @property
    def evidence_mode(self) -> str:
        return (
            "exact_pinned_snapshot"
            if self.evidence_snapshot_id
            else "unsnapshotted_explicit_inputs"
        )


def _date(value):
    try:
        return date.fromisoformat(value) if isinstance(value, str) else value
    except ValueError as exc:
        raise ValidationError("Dates must be YYYY-MM-DD") from exc


def resolve_candidates(
    report: CandidateReport,
    *,
    fiscal_year: int | None = None,
    period: str | None = None,
    start: date | str | None = None,
    end: date | str | None = None,
    revision_policy: str = "latest_available",
) -> MetricResult:
    """Resolve a complete candidate report. Instant queries require an explicit end date.

    Duration queries use either fiscal_year + period or exact start + end dates.
    Exact dates do not bypass ambiguous period classification. all_available can
    return a scalar only when the entire selected history agrees, retaining every
    supporting observation. No value is used to break a ranking tie.
    """
    revisions.validate_policy(revision_policy)
    start, end = _date(start), _date(end)
    definition = REGISTRY.get(report.metric)
    query = {"fiscal_year": fiscal_year, "period": period, "start": start, "end": end}
    groups = []
    relevant = []
    target_rejections = []

    def result(state, selected=(), conflicts=(), diagnostics=()):
        obs = selected[0].observation if selected else None
        return MetricResult(
            report.cik,
            report.metric,
            report.as_of,
            state,
            revision_policy,
            query,
            obs.fact.observation.value if obs else None,
            obs.fact.observation.unit if obs else None,
            obs.period.identity if obs else None,
            tuple(selected),
            tuple(relevant),
            tuple(target_rejections),
            tuple(conflicts),
            tuple(diagnostics),
            report,
            tuple(groups),
        )

    if definition is None:
        return result("unsupported", diagnostics=("unsupported_metric",))
    if report.mode != "as_of" or report.definition != definition:
        raise ValidationError("Metric resolution requires the registered as-of contract")
    if any(
        d is not None and (not isinstance(d, date) or isinstance(d, datetime)) for d in (start, end)
    ):
        raise ValidationError("Dates must be calendar dates")
    if definition.context == "instant":
        if end is None or start is not None or fiscal_year is not None or period is not None:
            raise ValidationError(
                "Instant metrics require end only; fiscal labels are not inferred"
            )
    elif start is not None or end is not None:
        if start is None or end is None or start > end or fiscal_year is not None or period:
            raise ValidationError("Duration date query requires start <= end without fiscal labels")
    elif (
        not isinstance(fiscal_year, int)
        or isinstance(fiscal_year, bool)
        or not 1 <= fiscal_year <= 9999
        or period not in {"FY", "Q1", "Q2", "Q3", "Q4", "YTD-Q2", "YTD-Q3"}
    ):
        raise ValidationError("Duration metrics require fiscal_year and an explicit period label")

    available = {}
    names = set()
    for view in report.evidence:
        if view.cik != report.cik or view.as_of != report.as_of:
            raise ValidationError("Candidate evidence issuer/cutoff mismatch")
        names.add(view.concept)
        history = revisions.analyze(view, policy=revision_policy)
        groups.extend(history.groups)
        for r in view.records:
            available[r.fact.observation_id] = r
    if not {m.concept for m in definition.mappings} <= names:
        raise ValidationError("Missing mapped concept evidence")
    expected_ids = {
        key for key, r in available.items() if not _reasons(report.metric, r.fact, r.period)
    }
    actual_ids = [c.observation.fact.observation_id for c in report.records]
    if len(actual_ids) != len(set(actual_ids)) or set(actual_ids) != expected_ids:
        raise ValidationError("Candidate report omits or duplicates admissible observations")
    expected_rejected = tuple(
        sorted(
            (r for v in report.evidence for r in _rejections(report.metric, v)),
            key=lambda r: r.fact.observation_id,
        )
    )
    if report.rejected != expected_rejected:
        raise ValidationError("Rejection audit differs from bounded evidence")
    for c in report.records:
        obs = c.observation.fact.observation
        if available.get(
            c.observation.fact.observation_id
        ) != c.observation or c.mapping != mapping_for(report.metric, obs.taxonomy, obs.concept):
            raise ValidationError("Candidate differs from bounded evidence or mapping")

    def matches(c):
        p = c.observation.period.identity
        return (
            (p.start, p.end) == (start, end)
            if end is not None
            else (p.fiscal_year, p.label) == (fiscal_year, period)
        )

    relevant = [c for c in report.records if matches(c)]
    dates = {(c.observation.period.start, c.observation.period.end) for c in relevant}
    blockers = set()
    for r in report.rejected:
        # Known future observations must not affect values OR resolution states.
        if "unavailable_as_of" in r.reasons:
            continue
        obs = r.fact.observation
        if mapping_for(report.metric, obs.taxonomy, obs.concept) is None:
            continue
        represented = (r.fact.context.start, r.fact.context.end)
        if end is not None:
            related = represented == (start, end)
        elif represented in dates:
            related = True
        elif r.period and r.period.kind in definition.period_kinds:
            identity = r.period.identity
            related = (identity.fiscal_year, identity.label) == (fiscal_year, period)
        elif dates and all(
            (r.fact.context.end is not None and a is not None and r.fact.context.end < a)
            or (r.fact.context.start is not None and b is not None and r.fact.context.start > b)
            for a, b in dates
        ):
            # A comparative for a disjoint older interval is not this target,
            # even when Company Facts fy names the later reporting fiscal year.
            related = False
        else:
            # Raw fy/fp cannot establish identity, but uncertainty about that
            # requested fiscal period must block a scalar, even across concepts.
            related = obs.fiscal_year == fiscal_year and obs.fiscal_period == (
                "FY" if period in {"FY", "Q4"} else period.removeprefix("YTD-")
            )
        if related:
            target_rejections.append(r)
            blockers.update(r.reasons)
    if relevant and blockers & {
        "unknown_availability",
        "conflicting_provenance",
        "incompatible_unit",
        "insufficient_evidence",
    }:
        return result("conflicted", conflicts=sorted(blockers))
    if blockers & {"ambiguous_period", "unsupported_period"}:
        return result("ambiguous_period", diagnostics=sorted(blockers))
    if not relevant:
        state = (
            "unsupported"
            if blockers & {"incompatible_unit", "wrong_context_type"}
            else "unavailable"
        )
        return result(
            state, diagnostics=tuple(sorted(blockers)) or ("no_eligible_reported_observation",)
        )
    ids = {c.observation.fact.observation_id for c in relevant}
    relevant_groups = [
        g for g in groups if any(c.observation.fact.observation_id in ids for c in g.candidates)
    ]
    conflicts = {reason for g in relevant_groups for reason in g.conflicts}
    if conflicts:
        return result("conflicted", conflicts=sorted(conflicts))
    priority = min(c.mapping.priority for c in relevant)
    preferred = [c for c in relevant if c.mapping.priority == priority]
    if len({(c.mapping.taxonomy, c.mapping.concept) for c in preferred}) != 1:
        return result("conflicted", conflicts=("multiple_supported_concept_scopes",))
    chosen_ids = {i for g in relevant_groups for i in g.selected_observation_ids}
    selected = [c for c in preferred if c.observation.fact.observation_id in chosen_ids]
    identities = {
        (
            c.observation.period.start,
            c.observation.period.end,
            c.observation.period.identity.fiscal_year,
            c.observation.period.identity.label,
            c.observation.fact.observation.unit,
        )
        for c in selected
    }
    if len(identities) != 1:
        return result("conflicted", conflicts=("incompatible_period_or_unit",))
    if len({c.observation.fact.observation.value for c in selected}) != 1:
        return result("conflicted", conflicts=("incompatible_candidate_values",))
    return result("resolved", selected, diagnostics=("directly_reported; no arithmetic",))


def resolve(
    cik: str | int,
    metric: str,
    *,
    as_of: str | datetime,
    fiscal_year: int | None = None,
    period: str | None = None,
    start: date | str | None = None,
    end: date | str | None = None,
    revision_policy: str = "latest_available",
    client: SECClient | None = None,
    filing_timeline: FilingTimeline | None = None,
    refresh: bool = False,
) -> MetricResult:
    return resolve_candidates(
        candidates(
            cik,
            metric,
            as_of=as_of,
            client=client,
            filing_timeline=filing_timeline,
            refresh=refresh,
        ),
        fiscal_year=fiscal_year,
        period=period,
        start=start,
        end=end,
        revision_policy=revision_policy,
    )
