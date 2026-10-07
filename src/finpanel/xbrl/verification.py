"""Conservative original-source matching. No value-only or filename-based matches."""

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from finpanel.filings import _cutoff
from finpanel.models import FactObservation
from finpanel.xbrl.models import InstanceEvidence, OriginalContext, OriginalFact, OriginalUnit
from finpanel.xbrl.parser import ISO, XBRLI, tag


@dataclass(frozen=True)
class FactDecision:
    fact: OriginalFact
    context: OriginalContext | None
    unit: OriginalUnit | None
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class SourceVerification:
    observation: FactObservation
    as_of: datetime
    state: str
    scope_state: str
    period_state: str
    matches: tuple[FactDecision, ...]
    decisions: tuple[FactDecision, ...]
    instances: tuple[InstanceEvidence, ...]
    diagnostics: tuple[str, ...]
    temporal_contract: str = "filing_date_and_retrieval_time_bounded; no_backdated_verification"


def _taxonomy(namespace, taxonomy):
    patterns = {
        "us-gaap": r"https?://fasb\.org/us-gaap/\d{4}",
        "dei": r"https?://xbrl\.sec\.gov/dei/\d{4}",
    }
    return bool(re.fullmatch(patterns.get(taxonomy, r"(?!)"), namespace))


def _unit(unit, name):
    if unit is None or unit.diagnostics:
        return False

    def measure(value):
        if re.fullmatch("[A-Z]{3}", value):
            return tag(ISO, value)
        if value in {"shares", "pure"}:
            return tag(XBRLI, value)
        return None

    parts = name.split("/")
    if len(parts) == 1:
        return unit.numerator == (measure(parts[0]),) and not unit.denominator
    return (
        len(parts) == 2
        and unit.numerator == (measure(parts[0]),)
        and unit.denominator == (measure(parts[1]),)
    )


def _known_by(instance, cutoff):
    doc = instance.document
    if doc.filing_date is None or doc.retrieved_at is None:
        return False
    try:
        retrieved = datetime.fromisoformat(doc.retrieved_at)
        if retrieved.tzinfo is None:
            return False
        for timestamp in doc.discovery_retrieved_at:
            metadata_time = datetime.fromisoformat(timestamp)
            if metadata_time.tzinfo is None or metadata_time > cutoff:
                return False
        # Conservative upper boundary for a date-only filing across US time zones.
        filing_ready = datetime.combine(
            doc.filing_date + timedelta(days=1), datetime.min.time(), UTC
        ) + timedelta(hours=5)
        return retrieved <= cutoff and filing_ready <= cutoff
    except (ValueError, OverflowError):
        return False


def verify_fact(
    observation: FactObservation,
    *,
    instances: tuple[InstanceEvidence, ...] = (),
    as_of: str | datetime,
) -> SourceVerification:
    cutoff = _cutoff(as_of)
    decisions = []
    eligible = []
    diagnostics = []
    for instance in instances:
        doc = instance.document
        if doc.cik != observation.cik or doc.accession != observation.accession_number:
            continue
        if not _known_by(instance, cutoff):
            # Omit future bytes entirely from the result: they cannot strengthen or
            # otherwise change historical verification, diagnostics or provenance.
            continue
        if observation.filing_date and observation.filing_date >= cutoff.date():
            continue
        eligible.append(instance)
        contexts = {c.context_id: c for c in instance.contexts}
        units = {u.unit_id: u for u in instance.units}
        for fact in instance.facts:
            # Retain all original facts with this concept as matching candidates;
            # unrelated concepts cannot be matches and remain in source evidence.
            if fact.concept != observation.concept:
                continue
            context = contexts.get(fact.context_ref)
            unit = units.get(fact.unit_ref)
            reasons = []
            if observation.filing_date and doc.filing_date != observation.filing_date:
                reasons.append("filing_date_mismatch")
            if observation.form and doc.form != observation.form:
                reasons.append("filing_form_mismatch")
            if not _taxonomy(fact.namespace, observation.taxonomy):
                reasons.append("taxonomy_mismatch")
            if context is None:
                reasons.append("context_unavailable")
            else:
                entity = context.entity_identifier or ""
                if (
                    context.identifier_scheme != "http://www.sec.gov/CIK"
                    or not entity.isdigit()
                    or int(entity) != int(observation.cik)
                ):
                    reasons.append("entity_mismatch")
                if (context.period_type, context.start, context.end) != (
                    observation.context.kind,
                    observation.period_start,
                    observation.period_end,
                ):
                    reasons.append("period_mismatch")
                if context.diagnostics:
                    reasons.append("context_semantics_unsupported")
            if not _unit(unit, observation.unit):
                reasons.append(
                    "unit_unsupported" if unit is None or unit.diagnostics else "unit_mismatch"
                )
            if fact.nil or not isinstance(fact.value, Decimal) or fact.value != observation.value:
                reasons.append("value_mismatch")
            if fact.diagnostics:
                reasons.append("fact_semantics_unsupported")
            if fact.numeric.state.startswith("unsupported"):
                reasons.append("numeric_metadata_unsupported")
            decisions.append(FactDecision(fact, context, unit, tuple(reasons)))
    matches = tuple(d for d in decisions if not d.reasons)
    uncertain = [
        d
        for d in decisions
        if d.reasons
        and not any(
            r
            in {
                "taxonomy_mismatch",
                "entity_mismatch",
                "period_mismatch",
                "value_mismatch",
                "unit_mismatch",
                "filing_date_mismatch",
                "filing_form_mismatch",
            }
            for r in d.reasons
        )
    ]
    if not eligible:
        state = "instance_unavailable"
        diagnostics.append("no_eligible_instance_at_cutoff")
    elif not matches:
        state = (
            "unsupported"
            if any("unsupported" in r for d in decisions for r in d.reasons)
            else "source_mismatch"
        )
    elif uncertain or any(i.diagnostics for i in eligible):
        state = "ambiguous_match"
        diagnostics.append("unsupported_alternative_source_evidence")
    elif len(matches) == 1:
        state = "verified_unique"
    else:
        identities = {
            (
                d.context.fingerprint,
                d.unit.fingerprint,
                d.fact.namespace,
                d.fact.concept,
                d.fact.value,
                d.fact.numeric,
            )
            for d in matches
        }
        state = "verified_multiple_equivalent" if len(identities) == 1 else "ambiguous_match"
    if state.startswith("verified"):
        scope = "dimensioned" if matches[0].context.dimensions else "verified_undimensioned"
    elif state == "ambiguous_match":
        scope = "scope_conflict"
    elif state == "instance_unavailable":
        scope = "instance_unavailable"
    else:
        scope = "scope_unknown"
    period = (
        "consistent"
        if matches
        else "inconsistent"
        if any("period_mismatch" in d.reasons for d in decisions)
        else "insufficient_evidence"
    )
    return SourceVerification(
        observation,
        cutoff,
        state,
        scope,
        period,
        matches,
        tuple(decisions),
        tuple(eligible),
        tuple(diagnostics),
    )


def context_for_fact(verification: SourceVerification) -> tuple[OriginalContext, ...]:
    """Return every matching original context; never choose an arbitrary candidate."""
    return tuple(d.context for d in verification.matches)
