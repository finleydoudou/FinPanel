"""Candidate inspection on freshly constructed Phase 0E evidence boundaries."""

from collections import Counter
from dataclasses import dataclass, replace
from datetime import datetime

from finpanel import asof as boundary
from finpanel import facts, filings, revisions
from finpanel.errors import ValidationError
from finpanel.metrics.registry import (
    REGISTRY,
    ConceptMapping,
    MetricDefinition,
    mapping_for,
    unit_status,
)
from finpanel.models.asof import BoundedObservation, EvidenceEligibility, EvidenceView
from finpanel.models.period import PeriodClassification
from finpanel.models.source import Provenance, RawResponse
from finpanel.models.timeline import FilingTimeline
from finpanel.sec.client import SECClient
from finpanel.sec.common import normalize_cik
from finpanel.sec.companyfacts import parse_companyfacts


@dataclass(frozen=True)
class MetricCandidate:
    observation: BoundedObservation
    mapping: ConceptMapping
    unit_status: str


@dataclass(frozen=True)
class RejectedObservation:
    fact: facts.LinkedFact
    eligibility: EvidenceEligibility
    period: PeriodClassification | None
    reasons: tuple[str, ...]
    unit_status: str


@dataclass(frozen=True)
class UnmappedConcept:
    taxonomy: str
    concept: str
    count: int
    source: Provenance
    reason: str = "unsupported_concept"


@dataclass(frozen=True)
class CandidateReport:
    cik: str
    metric: str
    as_of: datetime
    definition: MetricDefinition | None
    records: tuple[MetricCandidate, ...]
    rejected: tuple[RejectedObservation, ...]
    evidence: tuple[EvidenceView, ...]
    revision_groups: tuple[revisions.RevisionGroup, ...]
    unmapped_concepts: tuple[UnmappedConcept, ...] = ()
    status: str = "supported"
    mode: str = "as_of"
    policy: str = "explicit-reported-metrics-v1"


def _reasons(metric, fact, period):
    definition = REGISTRY[metric]
    obs = fact.observation
    reasons = []
    if obs.taxonomy not in definition.allowed_taxonomies:
        reasons.append("wrong_taxonomy")
    if mapping_for(metric, obs.taxonomy, obs.concept) is None:
        reasons.append("unsupported_concept")
    if fact.context.kind != definition.context:
        reasons.append("wrong_context_type")
    if unit_status(obs.unit) != "supported_usd":
        reasons.append("incompatible_unit")
    if any(d.category == "verified_inconsistency" for d in fact.diagnostics):
        reasons.append("conflicting_provenance")
    if not obs.provenance.source_url or not obs.provenance.response_sha256:
        reasons.append("insufficient_evidence")
    if period is not None:
        if period.kind == "ambiguous":
            reasons.append("ambiguous_period")
        elif period.kind not in definition.period_kinds:
            reasons.append("unsupported_period")
    return reasons


def _rejections(metric: str, view: EvidenceView) -> tuple[RejectedObservation, ...]:
    result = []
    for r in view.records:
        reasons = _reasons(metric, r.fact, r.period)
        if reasons:
            result.append(
                RejectedObservation(
                    r.fact,
                    r.eligibility,
                    r.period,
                    tuple(reasons),
                    unit_status(r.fact.observation.unit),
                )
            )
    for r in view.excluded_observations:
        reasons = _reasons(metric, r.fact, None)
        reason = r.eligibility.reason
        reasons.append(
            "unknown_availability"
            if ("unknown_availability" in reason or reason == "missing_or_invalid_filing_link")
            else "unavailable_as_of"
        )
        result.append(
            RejectedObservation(
                r.fact,
                r.eligibility,
                None,
                tuple(reasons),
                unit_status(r.fact.observation.unit),
            )
        )
    return tuple(result)


def from_inspections(
    cik: str | int,
    metric: str,
    *,
    as_of: str | datetime,
    inspections: tuple[facts.FactInspection, ...],
) -> CandidateReport:
    """Offline/research entry point; require coverage of every mapped exact concept.

    Empty inspections explicitly represent absent concepts. Callers are responsible
    for supplying a coherent complete snapshot; parser/coverage issues stay visible.
    Calendars are rebuilt separately per concept using only eligible evidence.
    """
    cik, cutoff = normalize_cik(cik), filings._cutoff(as_of)
    definition = REGISTRY.get(metric)
    if definition is None:
        return CandidateReport(cik, metric, cutoff, None, (), (), (), (), status="unsupported")
    expected = {m.concept for m in definition.mappings}
    names = [i.concept for i in inspections]
    if len(names) != len(set(names)) or not expected <= set(names):
        raise ValidationError("Supply exactly one inspection for every mapped concept")
    records, rejected, views, groups = [], [], [], []
    partitioned = []
    for inspection in sorted(inspections, key=lambda i: i.concept):
        # Unsupported namespace/context/unit evidence must not anchor supported periods.
        valid = tuple(r for r in inspection.records if not _reasons(metric, r, None))
        invalid = tuple(r for r in inspection.records if _reasons(metric, r, None))
        partitioned.append(replace(inspection, records=valid))
        if invalid:
            partitioned.append(replace(inspection, records=invalid))
    for inspection in partitioned:
        if inspection.cik != cik or any(
            r.observation.concept != inspection.concept for r in inspection.records
        ):
            raise ValidationError("Metric inspection issuer/concept mismatch")
        view = boundary.from_inspection(inspection, cutoff)
        views.append(view)
        # Preserve the complete exact-concept groups even for rejected contracts.
        groups.extend(revisions.analyze(view, policy="all_available").groups)
        rejected.extend(_rejections(metric, view))
        for r in view.records:
            if not _reasons(metric, r.fact, r.period):
                records.append(
                    MetricCandidate(
                        r,
                        mapping_for(
                            metric, r.fact.observation.taxonomy, r.fact.observation.concept
                        ),
                        unit_status(r.fact.observation.unit),
                    )
                )
    return CandidateReport(
        cik,
        metric,
        cutoff,
        definition,
        tuple(sorted(records, key=lambda r: r.observation.fact.observation_id)),
        tuple(sorted(rejected, key=lambda r: r.fact.observation_id)),
        tuple(views),
        tuple(groups),
    )


class _SnapshotClient:
    """Pin one raw Company Facts response while reusing the validated fact linker."""

    def __init__(self, source: RawResponse):
        self.source = source

    def companyfacts(self, cik, *, refresh=False):
        return self.source


def candidates(
    cik: str | int,
    metric: str,
    *,
    as_of: str | datetime,
    client: SECClient | None = None,
    filing_timeline: FilingTimeline | None = None,
    inspect_concepts: tuple[str, ...] = (),
    refresh: bool = False,
) -> CandidateReport:
    """Inspect mapped concepts plus optional exact names; no winner is selected.

    The unmapped inventory points to all other concepts in the raw snapshot;
    inspect_concepts expands any such concept into individual rejection records.
    An explicitly supplied timeline may have limited coverage: missing links remain
    unknown. Default loading requires all referenced submission history files.
    """
    cik, cutoff = normalize_cik(cik), filings._cutoff(as_of)
    if metric not in REGISTRY:
        return from_inspections(cik, metric, as_of=cutoff, inspections=())
    if client is None:
        with SECClient() as owned:
            return candidates(
                cik,
                metric,
                as_of=cutoff,
                client=owned,
                filing_timeline=filing_timeline,
                inspect_concepts=inspect_concepts,
                refresh=refresh,
            )
    source = client.companyfacts(cik, refresh=refresh)
    parsed = parse_companyfacts(source)
    data = (
        filing_timeline
        if filing_timeline is not None
        else filings.timeline(cik, client=client, refresh=refresh)
    )
    names = {m.concept for m in REGISTRY[metric].mappings} | set(inspect_concepts)
    pinned = _SnapshotClient(source)
    inspections = tuple(
        facts.for_concept(
            cik,
            name,
            client=pinned,
            filing_timeline=data,
        )
        for name in sorted(names)
    )
    result = from_inspections(cik, metric, as_of=cutoff, inspections=inspections)
    counts = Counter(
        (r.taxonomy, r.concept)
        for r in parsed.records
        if not mapping_for(metric, r.taxonomy, r.concept)
    )
    inventory = tuple(
        UnmappedConcept(
            taxonomy,
            concept,
            count,
            source.provenance(
                "/facts/"
                + taxonomy.replace("~", "~0").replace("/", "~1")
                + "/"
                + concept.replace("~", "~0").replace("/", "~1")
            ),
        )
        for (taxonomy, concept), count in sorted(counts.items())
    )
    return replace(result, unmapped_concepts=inventory)
