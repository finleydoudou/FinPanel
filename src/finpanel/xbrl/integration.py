"""Opt-in verification envelopes retain original WP1/WP2 results unchanged."""

from dataclasses import dataclass
from decimal import Decimal

from finpanel.errors import ValidationError
from finpanel.metrics.derivation_models import QuarterDerivation
from finpanel.metrics.resolver import MetricResult
from finpanel.revisions import RevisionGroup
from finpanel.xbrl.models import InstanceEvidence
from finpanel.xbrl.verification import SourceVerification, verify_fact


@dataclass(frozen=True)
class VerifiedMetric:
    original: MetricResult
    mode: str
    state: str
    value: int | Decimal | None
    candidates: tuple[SourceVerification, ...]
    selected: tuple[SourceVerification, ...]
    diagnostics: tuple[str, ...]


@dataclass(frozen=True)
class VerifiedDerivation:
    original: QuarterDerivation
    mode: str
    state: str
    value: int | Decimal | None
    minuend: VerifiedMetric | None
    subtrahend: VerifiedMetric | None
    scope_state: str
    diagnostics: tuple[str, ...]


@dataclass(frozen=True)
class RevisionSourceEvidence:
    group_key: dict
    observations: tuple[SourceVerification, ...]
    selected_observation_ids: tuple[str, ...]
    scope_state: str
    # Availability stays attached to the original revision candidates.
    original_group: RevisionGroup


def _mode(mode):
    if mode not in {"best_effort", "required"}:
        raise ValidationError("source_verification must be best_effort or required")


def _proven(v):
    return v.state in {"verified_unique", "verified_multiple_equivalent"}


def verify_metric(
    result: MetricResult,
    *,
    instances: tuple[InstanceEvidence, ...] = (),
    source_verification: str = "best_effort",
) -> VerifiedMetric:
    """Attach verification to every considered candidate, without reranking winners.

    required withholds the envelope scalar unless every selected observation has
    unambiguous undimensioned source evidence. The original result stays inspectable.
    """
    _mode(source_verification)
    verified = tuple(
        verify_fact(c.observation.fact.observation, instances=instances, as_of=result.as_of)
        for c in result.considered
    )
    ids = {c.observation.fact.observation_id for c in result.selected}
    selected = tuple(v for v in verified if v.observation.observation_id in ids)
    state, value = result.state, result.value
    diagnostics = []
    if selected and any(not _proven(v) for v in selected):
        diagnostics.append("original_source_not_fully_verified")
    if selected and any(v.scope_state != "verified_undimensioned" for v in selected):
        diagnostics.append("undimensioned_scope_not_proven")
    if (
        source_verification == "required"
        and result.state == "resolved"
        and (not selected or diagnostics)
    ):
        state, value = "source_verification_rejected", None
    return VerifiedMetric(
        result, source_verification, state, value, verified, selected, tuple(diagnostics)
    )


def _scope(verified):
    if not verified or any(not _proven(v) for v in verified):
        return "original_context_unknown"
    scopes = {
        (d.context.scope_fingerprint, d.unit.fingerprint) for v in verified for d in v.matches
    }
    if len(scopes) != 1:
        return "scope_different"
    return "same_scope_compatible"


def verify_derivation(
    result: QuarterDerivation,
    *,
    instances: tuple[InstanceEvidence, ...] = (),
    source_verification: str = "best_effort",
) -> VerifiedDerivation:
    _mode(source_verification)
    operands = tuple(
        verify_metric(r, instances=instances, source_verification=source_verification)
        if r is not None
        else None
        for r in (result.minuend, result.subtrahend)
    )
    selected = tuple(v for r in operands if r for v in r.selected)
    scope = (
        _scope(selected) if all(r and r.selected for r in operands) else "original_context_unknown"
    )
    state, value = result.status, result.value
    diagnostics = []
    if scope == "scope_different":
        diagnostics.append("original_context_scope_mismatch")
        state, value = "source_verification_rejected", None
    if any(v.scope_state == "dimensioned" for v in selected):
        diagnostics.append("dimensioned_arithmetic_not_supported")
        state, value = "source_verification_rejected", None
    if scope == "original_context_unknown":
        diagnostics.append("dimension_level_compatibility_not_proven")
    if any(v.state in {"source_mismatch", "ambiguous_match"} for v in selected):
        diagnostics.append("original_source_conflict")
        state, value = "source_verification_rejected", None
    if source_verification == "required" and (
        scope != "same_scope_compatible"
        or any(r is None or r.state != "resolved" for r in operands)
    ):
        state, value = "source_verification_rejected", None
    return VerifiedDerivation(
        result, source_verification, state, value, *operands, scope, tuple(diagnostics)
    )


def revision_evidence(
    result: MetricResult, *, instances: tuple[InstanceEvidence, ...] = ()
) -> tuple[RevisionSourceEvidence, ...]:
    """Enrich existing groups, retaining the original ordering and selected IDs."""
    rows = []
    for group in result.revision_groups:
        verified = tuple(
            verify_fact(c.observation.fact.observation, instances=instances, as_of=result.as_of)
            for c in group.candidates
        )
        rows.append(
            RevisionSourceEvidence(
                group.identity, verified, group.selected_observation_ids, _scope(verified), group
            )
        )
    return tuple(rows)
