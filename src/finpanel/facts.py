"""Inspect all observations for an exact concept name; never choose a winning value."""

from dataclasses import dataclass
from datetime import date

from finpanel import filings
from finpanel.availability import validate
from finpanel.errors import ValidationError
from finpanel.models import FactObservation, ParseIssue, Provenance
from finpanel.models.context import FactContext
from finpanel.models.evidence import Diagnostic
from finpanel.models.timeline import Availability, FilingEvent, FilingTimeline
from finpanel.sec.client import SECClient
from finpanel.sec.common import normalize_cik
from finpanel.sec.companyfacts import parse_companyfacts
from finpanel.sec.headers import parse_filing_header


@dataclass(frozen=True)
class LinkedFact:
    observation: FactObservation
    observation_id: str
    context: FactContext
    filing: FilingEvent | None
    availability: Availability
    diagnostics: tuple[Diagnostic, ...]


@dataclass(frozen=True)
class RepeatedPeriod:
    taxonomy: str
    concept: str
    unit: str
    context_type: str
    start: date | None
    end: date
    accessions: tuple[str, ...]
    observation_ids: tuple[str, ...]
    values_differ: bool
    interpretation: str = (
        "Same observed period across filings; comparative/revision cause not inferred"
    )


@dataclass(frozen=True)
class FactInspection:
    cik: str
    concept: str
    records: tuple[LinkedFact, ...]
    repeated_periods: tuple[RepeatedPeriod, ...]
    diagnostics: tuple[Diagnostic, ...]
    source_issues: tuple[ParseIssue, ...]
    timeline_issues: tuple[ParseIssue, ...]
    sources: tuple[Provenance, ...]


def for_concept(
    cik: str | int,
    concept: str,
    *,
    taxonomy: str | None = None,
    client: SECClient | None = None,
    filing_timeline: FilingTimeline | None = None,
    header_accessions: tuple[str, ...] = (),
    refresh: bool = False,
) -> FactInspection:
    """Exact name search across namespaces unless taxonomy is supplied.

    All duplicates survive. Headers are fetched only for explicitly requested
    accessions. Missing filing links remain unknown and are reported, not guessed.
    """
    cik = normalize_cik(cik)
    if not isinstance(concept, str) or not concept:
        raise ValidationError("concept must be a nonempty exact SEC concept name")
    if client is None:
        with SECClient() as owned:
            return for_concept(
                cik,
                concept,
                taxonomy=taxonomy,
                client=owned,
                filing_timeline=filing_timeline,
                header_accessions=header_accessions,
                refresh=refresh,
            )
    source = client.companyfacts(cik, refresh=refresh)
    if normalize_cik(source.json().get("cik")) != cik:
        raise ValidationError("Company Facts response CIK does not match requested issuer")
    parsed = parse_companyfacts(source)
    selected = [
        r
        for r in parsed.records
        if r.concept == concept and (taxonomy is None or r.taxonomy == taxonomy)
    ]
    diagnostics = []
    if not selected:
        if header_accessions:
            raise ValidationError("No matching observations for requested header validation")
        diagnostics.append(
            Diagnostic(
                "missing_data",
                "concept_not_found",
                "No matching concept observations",
                (source.provenance(""),),
            )
        )
        return FactInspection(
            cik, concept, (), (), tuple(diagnostics), parsed.issues, (), (source.provenance(""),)
        )
    data = (
        filing_timeline
        if filing_timeline is not None
        else filings.timeline(cik, client=client, refresh=refresh)
    )
    if data.cik != cik or data.as_of is not None:
        raise ValidationError("Fact inspection requires an unfiltered timeline for the same CIK")
    events = {r.accession_number: r for r in data}
    requested = set(header_accessions)
    selected_accessions = {r.accession_number for r in selected}
    if not requested <= selected_accessions or not requested <= events.keys():
        raise ValidationError(
            "Header accessions must belong to selected observations with filing links"
        )
    headers = {
        a: parse_filing_header(client.filing_header(cik, a, refresh=refresh))
        for a in sorted(requested)
    }
    validations = {
        a: validate(events[a], (headers[a],) if a in headers else ())
        for a in sorted(selected_accessions - {None})
        if a in events
    }
    records = []
    groups: dict[tuple, list[LinkedFact]] = {}
    for observation in selected:
        accession = observation.accession_number
        event = events.get(accession)
        local = []
        if event is None:
            local.append(
                Diagnostic(
                    "missing_data",
                    "filing_not_found",
                    "Observation has no matching filing event; availability unknown",
                    (observation.provenance,),
                )
            )
            availability = Availability(
                "unknown", reason="No filing link; Company Facts filed date is not substituted"
            )
        else:
            validation = validations[accession]
            availability = validation.availability
            local.extend(validation.diagnostics)
            for field, supplied in (
                ("form", observation.form),
                ("filing_date", observation.filing_date),
            ):
                expected = getattr(event, field)
                if supplied is not None and expected is not None and supplied != expected:
                    local.append(
                        Diagnostic(
                            "verified_inconsistency",
                            "fact_filing_metadata_mismatch",
                            f"Company Facts and filing event disagree on {field}",
                            (
                                observation.provenance,
                                *tuple(r.provenance for r in event.source_records),
                            ),
                        )
                    )
            if any(d.code == "fact_filing_metadata_mismatch" for d in local):
                availability = Availability(
                    "unknown",
                    reason="Fact-to-filing metadata conflict",
                    evidence=availability.evidence,
                )
        context = observation.context
        if context.kind == "unknown":
            local.append(
                Diagnostic(
                    "precision_limitation",
                    "unknown_fact_context",
                    context.basis,
                    (observation.provenance,),
                )
            )
        record = LinkedFact(
            observation, observation.observation_id, context, event, availability, tuple(local)
        )
        records.append(record)
        if context.kind != "unknown" and accession is not None:
            key = (
                observation.taxonomy,
                observation.concept,
                observation.unit,
                context.kind,
                context.start,
                context.end,
            )
            groups.setdefault(key, []).append(record)
    repeated = []
    for key, members in sorted(groups.items()):
        accessions = tuple(sorted({r.observation.accession_number for r in members}))
        if len(accessions) > 1:
            repeated.append(
                RepeatedPeriod(
                    *key,
                    accessions,
                    tuple(r.observation_id for r in members),
                    len({r.observation.value for r in members}) > 1,
                )
            )
    if repeated:
        diagnostics.append(
            Diagnostic(
                "heuristic_warning",
                "same_period_multiple_filings",
                "Repeated period/concept observations exist; "
                "no comparative/restatement winner selected",
                (source.provenance(""),),
            )
        )
    sources = (source.provenance(""), *data.sources, *tuple(h.provenance for h in headers.values()))
    return FactInspection(
        cik,
        concept,
        tuple(records),
        tuple(repeated),
        tuple(diagnostics),
        parsed.issues,
        data.issues,
        sources,
    )
