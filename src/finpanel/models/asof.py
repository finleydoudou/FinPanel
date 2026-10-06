"""Auditable eligibility decisions under the filing-availability proxy boundary."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from finpanel.facts import LinkedFact
from finpanel.models.evidence import Diagnostic
from finpanel.models.period import FiscalCalendar, PeriodClassification
from finpanel.models.source import ParseIssue, Provenance
from finpanel.models.timeline import Availability, FilingEvent


@dataclass(frozen=True)
class EvidenceEligibility:
    source: Provenance
    source_accession: str | None
    source_availability: Availability
    as_of: datetime
    eligible_as_of: bool
    reason: str
    role: Literal["filing", "fact", "field", "issuer_metadata"]
    observation_id: str | None = None


@dataclass(frozen=True)
class FilingDecision:
    filing: FilingEvent
    eligibility: EvidenceEligibility


@dataclass(frozen=True)
class ExcludedObservation:
    fact: LinkedFact
    eligibility: EvidenceEligibility


@dataclass(frozen=True)
class BoundedObservation:
    fact: LinkedFact
    period: PeriodClassification
    eligibility: EvidenceEligibility
    supporting_evidence: tuple[EvidenceEligibility, ...]
    mode: str = "as_of"


@dataclass(frozen=True)
class EvidenceView:
    cik: str
    as_of: datetime
    concept: str | None
    filings: tuple[FilingDecision, ...]
    records: tuple[BoundedObservation, ...]
    calendar: FiscalCalendar | None
    admitted_evidence: tuple[EvidenceEligibility, ...]
    excluded_evidence: tuple[EvidenceEligibility, ...]
    excluded_filings: tuple[FilingDecision, ...]
    excluded_observations: tuple[ExcludedObservation, ...]
    diagnostics: tuple[Diagnostic, ...]
    source_issues: tuple[ParseIssue, ...] = ()
    timeline_issues: tuple[ParseIssue, ...] = ()
    mode: str = "as_of"
    policy: str = "filing-proxy-evidence-boundary-v1"
