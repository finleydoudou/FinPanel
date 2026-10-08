"""Temporal candidate contracts for exact concepts; never canonical metric winners."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Literal

from finpanel.errors import ValidationError
from finpanel.filings import SEC_DAY_ZONE
from finpanel.models.asof import BoundedObservation, EvidenceView, ExcludedObservation
from finpanel.models.period import PeriodIdentity
from finpanel.serialization import dumps

POLICIES = {"first_reported", "latest_available", "all_available"}


def validate_policy(policy: str) -> None:
    if policy not in POLICIES:
        raise ValidationError(
            "Revision policy must be first_reported, latest_available or all_available"
        )


@dataclass(frozen=True)
class RevisionCandidate:
    observation: BoundedObservation
    status: Literal["selected_by_contract", "retained_history", "unresolved"]
    is_amendment: bool | None
    is_comparative: bool | None


@dataclass(frozen=True)
class RevisionGroup:
    identity: dict
    normalized_period: PeriodIdentity | None
    candidates: tuple[RevisionCandidate, ...]
    selected_observation_ids: tuple[str, ...]
    status: Literal["resolved", "conflicted"]
    conflicts: tuple[str, ...]
    unknown_availability_observations: tuple[ExcludedObservation, ...]


@dataclass(frozen=True)
class RevisionHistory:
    cik: str
    concept: str | None
    as_of: datetime
    policy: str
    groups: tuple[RevisionGroup, ...]
    evidence: EvidenceView
    status: Literal["resolved", "conflicted", "no_eligible_candidates"] = "no_eligible_candidates"
    mode: str = "as_of"
    contract: str = "exact-concept-temporal-candidates-v1"
    selection_scope: str = "Temporal candidates only; no economic or canonical metric winner"


def _key(fact):
    obs, ctx = fact.observation, fact.context
    # Unknown shapes cannot establish identity across observations.
    return {
        "cik": obs.cik,
        "taxonomy": obs.taxonomy,
        "concept": obs.concept,
        "unit": obs.unit,
        "context": ctx.kind,
        "start": ctx.start,
        "end": ctx.end,
        "unresolved_observation": fact.observation_id if ctx.kind == "unknown" else None,
    }


def _interval(record):
    availability = record.fact.availability
    if availability.precision == "acceptance_datetime":
        return availability.timestamp, availability.timestamp, False
    # This half-open uncertainty interval is for partial ordering only, never a
    # fabricated exact publication timestamp. Eligibility already uses the next day.
    start = datetime.combine(availability.date, time.min, SEC_DAY_ZONE)
    end = datetime.combine(availability.date + timedelta(days=1), time.min, SEC_DAY_ZONE)
    return start, end, True


def _before(a, b):
    _, upper, exclusive = _interval(a)
    lower, _, _ = _interval(b)
    return upper < lower or (exclusive and upper == lower)


def analyze(view: EvidenceView, *, policy: str = "all_available") -> RevisionHistory:
    from finpanel._reuse import memo

    # Cached RevisionHistory retains the exact view, so its object ID cannot be reused.
    return memo("revision_analysis", (id(view), policy), lambda: _analyze(view, policy=policy))


def _analyze(view: EvidenceView, *, policy: str) -> RevisionHistory:
    from finpanel.asof import eligibility

    validate_policy(policy)
    if view.mode != "as_of":
        raise ValidationError("Revision analysis requires an as-of evidence view")
    groups = defaultdict(list)
    unknown = defaultdict(list)
    admitted = {
        d.source for d in view.admitted_evidence if d.eligible_as_of and d.as_of == view.as_of
    }
    for record in view.records:
        decision = eligibility(
            record.fact.observation.provenance,
            record.fact.observation.accession_number,
            record.fact.availability,
            view.as_of,
        )
        if (
            not decision.eligible_as_of
            or not record.eligibility.eligible_as_of
            or record.eligibility.as_of != view.as_of
            or record.period.mode != "as_of"
            or record.period.as_of != view.as_of
        ):
            raise ValidationError("Revision candidates must be eligible at the view cutoff")
        used = {e.source for e in record.period.evidence}
        supported = {e.source for e in record.supporting_evidence}
        if not used <= supported <= admitted or any(
            not e.eligible_as_of
            or e.as_of != view.as_of
            or not eligibility(
                e.source, e.source_accession, e.source_availability, view.as_of
            ).eligible_as_of
            for e in record.supporting_evidence
        ):
            raise ValidationError(
                "Revision interpretation uses evidence outside the cutoff boundary"
            )
        groups[dumps(_key(record.fact))].append(record)
    for record in view.excluded_observations:
        if (
            "unknown_availability" in record.eligibility.reason
            or record.eligibility.reason == "missing_or_invalid_filing_link"
        ):
            unknown[dumps(_key(record.fact))].append(record)
    result = []
    for key, members in sorted(groups.items()):
        members = sorted(members, key=lambda r: r.fact.observation_id)
        conflicts = []
        periods = {dumps(r.period.identity) for r in members}
        usable = all(
            r.period.kind in ("instant", "annual", "single_quarter", "year_to_date")
            for r in members
        )
        if not usable:
            conflicts.append("insufficient_period_evidence")
        if len(periods) != 1:
            conflicts.append("period_classification_disagreement")
        if unknown[key]:
            conflicts.append("unknown_availability")
        if policy == "all_available":
            chosen = members
        elif policy == "first_reported":
            chosen = [r for r in members if not any(_before(other, r) for other in members)]
        else:
            chosen = [r for r in members if not any(_before(r, other) for other in members)]
        if policy != "all_available" and len(chosen) > 1:
            conflicts.append("multiple_equally_ranked_or_unordered_candidates")
        if len({r.fact.observation.value for r in chosen}) > 1:
            conflicts.append("incompatible_candidate_values")
        selected = () if conflicts else tuple(r.fact.observation_id for r in chosen)
        chosen_ids = {r.fact.observation_id for r in chosen}
        candidates = []
        for record in members:
            filing, context = record.fact.filing, record.fact.context
            comparative = (
                context.end < filing.report_date
                if filing and filing.report_date and context.end
                else None
            )
            candidate_status = (
                "selected_by_contract"
                if record.fact.observation_id in selected
                else "unresolved"
                if conflicts and record.fact.observation_id in chosen_ids
                else "retained_history"
            )
            candidates.append(
                RevisionCandidate(
                    record, candidate_status, filing.is_amendment if filing else None, comparative
                )
            )
        result.append(
            RevisionGroup(
                _key(members[0].fact),
                members[0].period.identity if usable and len(periods) == 1 else None,
                tuple(candidates),
                selected,
                "conflicted" if conflicts else "resolved",
                tuple(conflicts),
                tuple(unknown[key]),
            )
        )
    status = (
        "no_eligible_candidates"
        if not result
        else "conflicted"
        if any(g.status == "conflicted" for g in result)
        else "resolved"
    )
    return RevisionHistory(
        view.cik, view.concept, view.as_of, policy, tuple(result), view, status=status
    )
