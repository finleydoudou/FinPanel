"""Filter evidence before derivation; SEC acceptance remains a proxy, not dissemination proof."""

from dataclasses import replace
from datetime import datetime

from finpanel import facts, filings, periods
from finpanel.errors import ValidationError
from finpanel.models.asof import (
    BoundedObservation,
    EvidenceEligibility,
    EvidenceView,
    ExcludedObservation,
    FilingDecision,
)
from finpanel.models.evidence import Diagnostic
from finpanel.models.source import Provenance
from finpanel.models.timeline import Availability, FilingEvent, FilingTimeline
from finpanel.sec.client import SECClient
from finpanel.sec.common import normalize_cik
from finpanel.serialization import dumps


def eligibility(
    source: Provenance,
    accession: str | None,
    availability: Availability,
    as_of: str | datetime,
    *,
    role="field",
    observation_id: str | None = None,
) -> EvidenceEligibility:
    cutoff = filings._cutoff(as_of)
    eligible = False
    reason = "unknown_availability"
    if availability.precision == "acceptance_datetime":
        stamp = availability.timestamp
        if stamp is not None and stamp.utcoffset() is not None:
            eligible = stamp <= cutoff
            reason = "acceptance_proxy_at_or_before_cutoff" if eligible else "future_acceptance"
    elif availability.precision == "date_only" and availability.date is not None:
        day = cutoff.astimezone(filings.SEC_DAY_ZONE).date()
        eligible = availability.date < day
        reason = (
            "filing_day_completed"
            if eligible
            else "date_only_same_day_excluded"
            if availability.date == day
            else "future_filing_day"
        )
    return EvidenceEligibility(
        source,
        accession,
        replace(availability, evidence=()),
        cutoff,
        eligible,
        reason,
        role,
        observation_id,
    )


def _unique(items):
    return tuple(v for _, v in sorted({dumps(i): i for i in items}.items()))


def _bounded_filing(event: FilingEvent) -> FilingEvent:
    # Current issuer attributes have no historical availability attached to them.
    return replace(
        event,
        source_records=tuple(
            replace(r, entity_name=None, fiscal_year_end=None) for r in event.source_records
        ),
    )


def from_inspection(
    inspection: facts.FactInspection,
    as_of: str | datetime,
    *,
    filing_timeline: FilingTimeline | None = None,
) -> EvidenceView:
    """Project a source inspection into an as-of view without retrospective calendar reuse.

    Snapshot-wide parser/coverage issues and excluded records are audit data, not
    admissible derivation inputs. Unversioned issuer metadata is always withheld.
    """
    cutoff = filings._cutoff(as_of)
    if filing_timeline is not None:
        if filing_timeline.cik != inspection.cik or filing_timeline.as_of is not None:
            raise ValidationError("Evidence boundary requires an unfiltered same-issuer timeline")
        events = {r.accession_number: r for r in filing_timeline}
    else:
        events = {}
        for record in inspection.records:
            if record.filing is not None:
                event = record.filing
                if event.accession_number in events and events[event.accession_number] != event:
                    raise ValidationError("Inconsistent linked filing events for one accession")
                events[event.accession_number] = event
    if any(r.observation.cik != inspection.cik for r in inspection.records):
        raise ValidationError("Observation issuer differs from inspection issuer")
    if any(e.cik != inspection.cik for e in events.values()):
        raise ValidationError("Filing issuer differs from inspection issuer")
    admitted, excluded = [], []
    accepted_filings, rejected_filings = [], []
    decisions = {}
    for accession, event in sorted(events.items()):
        if not event.source_records:
            raise ValidationError("Filing eligibility requires raw source provenance")
        decision = eligibility(
            event.source_records[0].provenance, accession, event.availability, cutoff, role="filing"
        )
        decisions[accession] = decision
        bucket = admitted if decision.eligible_as_of else excluded
        bucket.append(decision)
        for evidence in event.availability.evidence:
            bucket.append(eligibility(evidence.source, accession, event.availability, cutoff))
        bounded = _bounded_filing(event)
        (accepted_filings if decision.eligible_as_of else rejected_filings).append(
            FilingDecision(bounded if decision.eligible_as_of else event, decision)
        )
        for row in event.source_records:
            if row.provenance.pointer.startswith("/filings/recent/"):
                for field, value in (
                    ("fiscalYearEnd", row.fiscal_year_end),
                    ("name", row.entity_name),
                ):
                    if value is not None:
                        excluded.append(
                            EvidenceEligibility(
                                replace(row.provenance, pointer=f"/{field}"),
                                None,
                                Availability("unknown"),
                                cutoff,
                                False,
                                "unversioned_issuer_metadata",
                                "issuer_metadata",
                            )
                        )
    eligible_records, excluded_records = [], []
    fact_decisions = {}
    for record in inspection.records:
        obs = record.observation
        decision = eligibility(
            obs.provenance,
            obs.accession_number,
            record.availability,
            cutoff,
            role="fact",
            observation_id=record.observation_id,
        )
        event_decision = decisions.get(obs.accession_number)
        if (
            record.filing is None
            or event_decision is None
            or record.filing.cik != obs.cik
            or record.filing.accession_number != obs.accession_number
        ):
            decision = replace(
                decision, eligible_as_of=False, reason="missing_or_invalid_filing_link"
            )
        elif events[obs.accession_number] != record.filing:
            raise ValidationError("Linked filing differs from supplied timeline event")
        elif not event_decision.eligible_as_of:
            decision = replace(
                decision, eligible_as_of=False, reason=f"filing_excluded:{event_decision.reason}"
            )
        bucket = admitted if decision.eligible_as_of else excluded
        bucket.append(decision)
        for evidence in periods._evidence(obs, record.filing):
            bucket.append(replace(decision, source=evidence.source, role="field"))
        if obs.entity_name is not None:
            excluded.append(
                EvidenceEligibility(
                    replace(obs.provenance, pointer="/entityName"),
                    None,
                    Availability("unknown"),
                    cutoff,
                    False,
                    "unversioned_issuer_metadata",
                    "issuer_metadata",
                )
            )
        if decision.eligible_as_of:
            bounded = replace(
                record,
                observation=replace(obs, entity_name=None),
                filing=_bounded_filing(record.filing),
            )
            eligible_records.append(bounded)
            fact_decisions[record.observation_id] = decision
        else:
            excluded_records.append(ExcludedObservation(record, decision))
    # This is the only input to calendar construction. No excluded records,
    # retrospective anchors, repeated-period groups, or current MMDD hints enter it.
    bounded_inspection = facts.FactInspection(
        inspection.cik,
        inspection.concept,
        tuple(eligible_records),
        (),
        (),
        (),
        (),
        (),
    )
    interpreted = periods.interpret(bounded_inspection)
    admitted = _unique(admitted)
    by_source = {}
    for decision in admitted:
        by_source.setdefault(decision.source, []).append(decision)
    records = []
    for result in interpreted.records:
        used = []
        for evidence in result.period.evidence:
            matches = by_source.get(evidence.source, [])
            if not matches:
                raise ValidationError(
                    "Derived period contains evidence outside the cutoff boundary"
                )
            used.extend(matches)
        records.append(
            BoundedObservation(
                result.fact,
                replace(result.period, mode="as_of", as_of=cutoff),
                fact_decisions[result.fact.observation_id],
                _unique(used),
            )
        )
    diagnostics = [
        Diagnostic(
            "precision_limitation",
            "snapshot_metadata_proxy",
            "Current SEC snapshots do not prove historical field versions; "
            "original filing availability is the documented proxy",
        )
    ]
    if any(d.reason == "unversioned_issuer_metadata" for d in excluded):
        diagnostics.append(
            Diagnostic(
                "missing_data",
                "issuer_metadata_excluded",
                "Current issuer attributes have no historical availability",
            )
        )
    if excluded_records:
        diagnostics.append(
            Diagnostic(
                "precision_limitation",
                "evidence_excluded_before_derivation",
                "Ineligible observations cannot supply calendar or period evidence",
            )
        )
    return EvidenceView(
        inspection.cik,
        cutoff,
        inspection.concept,
        tuple(accepted_filings),
        tuple(records),
        interpreted.calendar,
        admitted,
        _unique(excluded),
        tuple(rejected_filings),
        tuple(excluded_records),
        tuple(diagnostics),
        inspection.source_issues,
        filing_timeline.issues if filing_timeline is not None else inspection.timeline_issues,
    )


def view(
    cik: str | int,
    as_of: str | datetime,
    *,
    concept: str | None = None,
    taxonomy: str | None = None,
    client: SECClient | None = None,
    refresh: bool = False,
) -> EvidenceView:
    """Filings by default; supply an exact concept to include facts and bounded periods."""
    cutoff = filings._cutoff(as_of)
    cik = normalize_cik(cik)
    if client is None:
        with SECClient() as owned:
            return view(
                cik, cutoff, concept=concept, taxonomy=taxonomy, client=owned, refresh=refresh
            )
    timeline = filings.timeline(cik, client=client, refresh=refresh)
    if concept is None:
        inspection = facts.FactInspection(cik, "", (), (), (), (), (), ())
    else:
        inspection = facts.for_concept(
            cik,
            concept,
            taxonomy=taxonomy,
            client=client,
            filing_timeline=timeline,
            refresh=refresh,
        )
    result = from_inspection(inspection, cutoff, filing_timeline=timeline)
    return replace(
        result, concept=concept, calendar=result.calendar if concept is not None else None
    )


def revisions(
    cik: str | int,
    concept: str,
    as_of: str | datetime,
    *,
    policy: str = "all_available",
    taxonomy: str | None = None,
    client: SECClient | None = None,
    refresh: bool = False,
):
    from finpanel.revisions import analyze, validate_policy

    validate_policy(policy)
    return analyze(
        view(cik, as_of, concept=concept, taxonomy=taxonomy, client=client, refresh=refresh),
        policy=policy,
    )
