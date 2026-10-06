"""Conservative reported-context classification. No value arithmetic or selection."""

from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import timedelta

from finpanel import facts
from finpanel.errors import ValidationError
from finpanel.models import FactObservation
from finpanel.models.evidence import Diagnostic, Evidence
from finpanel.models.period import (
    FiscalCalendar,
    FiscalYearWindow,
    PeriodClassification,
    PeriodIdentity,
    QuarterBoundary,
)
from finpanel.models.timeline import FilingEvent
from finpanel.sec.client import SECClient
from finpanel.sec.common import normalize_cik
from finpanel.serialization import dumps

ANNUAL_DAYS = (350, 378)
QUARTER_DAYS = (70, 112)
YTD_DAYS = {1: QUARTER_DAYS, 2: (150, 210), 3: (230, 308)}
ANNUAL_FORMS = {"10-K", "10-K/A"}
QUARTER_FORMS = {"10-Q", "10-Q/A"}


def _within(days, limits):
    return days is not None and limits[0] <= days <= limits[1]


def _unique(evidence):
    return tuple(v for _, v in sorted({dumps(e): e for e in evidence}.items()))


def _evidence(observation, filing=None):
    result = [
        Evidence(
            k,
            observation.raw[k],
            replace(observation.provenance, pointer=f"{observation.provenance.pointer}/{k}"),
        )
        for k in ("start", "end", "fy", "fp", "form", "filed", "accn", "frame", "reportDate")
        if k in observation.raw
    ]
    if filing:
        result.extend(filing.availability.evidence)
    return _unique(result)


def _compatible(observation, filing):
    return filing is not None and (
        observation.cik == filing.cik
        and observation.accession_number == filing.accession_number
        and observation.form == filing.form
        and not set(filing.conflicts) & {"form", "report_date", "filing_date"}
        and (
            observation.filing_date is None
            or filing.filing_date is None
            or observation.filing_date == filing.filing_date
        )
        and (observation.report_date is None or filing.report_date == observation.report_date)
    )


def build_calendar(cik: str | int, records: tuple[facts.LinkedFact, ...]) -> FiscalCalendar:
    """Use current annual and YTD contexts as anchors, never comparative fy labels.

    Anchors are local to the supplied observation set. No cross-concept assumption,
    current-MMDD backfill, inferred January start, or future-availability claim.
    """
    cik = normalize_cik(cik)
    if any(r.observation.cik != cik for r in records):
        raise ValidationError("Calendar observations must belong to the requested issuer")
    candidates = defaultdict(list)
    hints = set()
    hint_evidence = []
    for record in records:
        obs, filing = record.observation, record.filing
        if filing:
            for row in filing.source_records:
                # History inherits issuer context but its raw response has no root MMDD.
                if row.fiscal_year_end and row.provenance.pointer.startswith("/filings/recent/"):
                    hints.add(row.fiscal_year_end)
                    hint_evidence.append(
                        Evidence(
                            "fiscalYearEnd",
                            row.fiscal_year_end,
                            replace(row.provenance, pointer="/fiscalYearEnd"),
                            "Current issuer metadata only; not a historical boundary",
                        )
                    )
        if (
            _compatible(obs, filing)
            and obs.form in ANNUAL_FORMS
            and obs.fiscal_period == "FY"
            and obs.fiscal_year is not None
            and 1 <= obs.fiscal_year <= 9999
            and _within(obs.context.duration_days, ANNUAL_DAYS)
            and obs.period_end == filing.report_date
        ):
            candidates[(obs.fiscal_year, obs.period_start, obs.period_end)].extend(
                _evidence(obs, filing)
            )
    years = tuple(
        FiscalYearWindow(cik, fy, start, end, _unique(evidence))
        for (fy, start, end), evidence in sorted(candidates.items())
    )
    ambiguous = set()
    for i, a in enumerate(years):
        for b in years[i + 1 :]:
            if a.fiscal_year == b.fiscal_year or max(a.start, b.start) <= min(a.end, b.end):
                ambiguous.update((a.fiscal_year, b.fiscal_year))
    quarters = defaultdict(list)
    for record in records:
        obs, filing = record.observation, record.filing
        if not (
            _compatible(obs, filing)
            and obs.form in QUARTER_FORMS
            and obs.fiscal_period in ("Q1", "Q2", "Q3")
            and obs.period_end == filing.report_date
        ):
            continue
        q = int(obs.fiscal_period[1])
        for year in years:
            if (
                year.fiscal_year not in ambiguous
                and obs.fiscal_year == year.fiscal_year
                and obs.period_start == year.start
                and obs.period_end < year.end
                and _within(obs.context.duration_days, YTD_DAYS[q])
            ):
                quarters[(year.fiscal_year, q, obs.period_end)].extend(_evidence(obs, filing))
    boundaries = tuple(
        QuarterBoundary(fy, q, end, _unique(evidence))
        for (fy, q, end), evidence in sorted(quarters.items())
    )
    # Conflicting quarter endpoints or impossible ordering invalidate that year's labels.
    for year in years:
        endpoints = {
            q: {b.end for b in boundaries if b.fiscal_year == year.fiscal_year and b.quarter == q}
            for q in (1, 2, 3)
        }
        if any(len(v) > 1 for v in endpoints.values()):
            ambiguous.add(year.fiscal_year)
        unique = [(q, next(iter(v))) for q, v in endpoints.items() if len(v) == 1]
        if any(a[1] >= b[1] for a, b in zip(unique, unique[1:], strict=False)):
            ambiguous.add(year.fiscal_year)
    diagnostics = ()
    if ambiguous:
        diagnostics = (
            Diagnostic(
                "verified_inconsistency",
                "fiscal_calendar_conflict",
                "Conflicting observed fiscal windows or quarter boundaries",
            ),
        )
    return FiscalCalendar(
        cik,
        years,
        boundaries,
        tuple(sorted(ambiguous)),
        tuple(sorted(hints)),
        _unique(hint_evidence),
        diagnostics,
    )


def classify_period(
    observation: FactObservation | facts.LinkedFact,
    *,
    calendar: FiscalCalendar | None = None,
    filing: FilingEvent | None = None,
) -> PeriodClassification:
    """Classify one observation; optional calendar supplies auditable neighboring evidence."""
    if isinstance(observation, facts.LinkedFact):
        if filing is not None and filing != observation.filing:
            raise ValidationError("Explicit filing differs from linked filing")
        filing = observation.filing
        observation = observation.observation
    obs = observation
    if calendar is not None and calendar.cik != obs.cik:
        raise ValidationError("Fiscal calendar belongs to another issuer")
    context = obs.context
    evidence = list(_evidence(obs, filing))
    diagnostics = []

    def diag(category, code, message):
        diagnostics.append(Diagnostic(category, code, message, (obs.provenance,)))

    def result(kind, method, status, year=None, label=None, single=None, ytd=None):
        return PeriodClassification(
            kind,
            context.start,
            context.end,
            context.duration_days,
            method,
            status,
            PeriodIdentity(obs.cik, context.start, context.end, year, label),
            single,
            ytd,
            _unique(evidence),
            tuple(sorted(diagnostics, key=lambda d: (d.category, d.code))),
        )

    if context.kind == "instant":
        return result(
            "instant", "observed_end_without_start", "observed_shape", single=False, ytd=False
        )
    if context.kind == "unknown":
        reversed_dates = context.start and context.end and context.start > context.end
        diag(
            "verified_inconsistency" if reversed_dates else "missing_data",
            "reversed_period" if reversed_dates else "unusable_period_dates",
            context.basis,
        )
        return result("unknown", "unusable_context", "insufficient_data")
    days = context.duration_days
    if days < QUARTER_DAYS[0] or days > ANNUAL_DAYS[1]:
        diag("heuristic_warning", "unusual_duration", "Outside usual quarter/full-year guardrails")
    if obs.form in ANNUAL_FORMS and days < ANNUAL_DAYS[0]:
        diag(
            "heuristic_warning",
            "annual_form_short_context",
            "Annual filings can contain short contexts; form does not establish duration",
        )
    if obs.fiscal_period in ("Q1", "Q2", "Q3") and _within(days, ANNUAL_DAYS):
        diag(
            "heuristic_warning",
            "quarter_metadata_annual_duration",
            "Quarter reporting metadata accompanies a full-year-length context",
        )
    if obs.fiscal_period in ("Q1", "Q2", "Q3"):
        q = int(obs.fiscal_period[1])
        if not (_within(days, QUARTER_DAYS) or _within(days, YTD_DAYS[q])):
            diag(
                "heuristic_warning",
                "fp_duration_guardrail",
                "Observed duration does not fit this reporting fp; inspect comparative context",
            )
    if filing is not None and not _compatible(obs, filing):
        diag(
            "verified_inconsistency",
            "period_filing_mismatch",
            "Fact and filing metadata cannot establish a consistent period link",
        )
        return result("ambiguous", "conflicting_filing_metadata", "ambiguous")
    if obs.report_date is not None and context.end > obs.report_date:
        diag(
            "heuristic_warning",
            "context_after_report_date",
            "Context end follows supplied report date",
        )
        return result("ambiguous", "report_date_conflict", "ambiguous")
    if filing and filing.report_date and context.end > filing.report_date:
        diag(
            "heuristic_warning",
            "context_after_report_date",
            "Context end follows filing report date",
        )
        return result("ambiguous", "report_date_conflict", "ambiguous")
    if calendar is None:
        if filing is not None:
            linked = facts.LinkedFact(
                obs, obs.observation_id, context, filing, filing.availability, ()
            )
            calendar = build_calendar(obs.cik, (linked,))
        else:
            calendar = FiscalCalendar(obs.cik)
    evidence.extend(calendar.evidence)
    windows = [w for w in calendar.years if w.start <= context.start <= context.end <= w.end]
    if len(windows) != 1 or any(w.fiscal_year in calendar.ambiguous_years for w in windows):
        if windows:
            for window in windows:
                evidence.extend(window.evidence)
                for boundary in calendar.quarters:
                    if boundary.fiscal_year == window.fiscal_year:
                        evidence.extend(boundary.evidence)
            diag(
                "precision_limitation",
                "fiscal_calendar_ambiguity",
                "Fiscal window is not unique and consistent",
            )
        else:
            diag(
                "missing_data",
                "missing_fiscal_boundary",
                "No observed full-year window covers this context",
            )
        if not any(_within(days, r) for r in (ANNUAL_DAYS, *YTD_DAYS.values())):
            diag(
                "precision_limitation",
                "unclassified_duration",
                "No standard reported-period rule applies",
            )
            return result("other_duration", "observed_nonstandard_duration", "observed_shape")
        return result("ambiguous", "insufficient_calendar_evidence", "ambiguous")
    year = windows[0]
    evidence.extend(year.evidence)
    current = filing is not None and context.end == filing.report_date
    if filing and filing.report_date and context.end < filing.report_date:
        diag(
            "heuristic_warning",
            "comparative_context",
            "Represented period precedes filing report end; filing fy/fp is not reassigned to it",
        )
    if current and obs.fiscal_year is not None and obs.fiscal_year != year.fiscal_year:
        diag(
            "verified_inconsistency",
            "fiscal_year_conflict",
            "Current context fy conflicts with observed fiscal window",
        )
        return result("ambiguous", "conflicting_fiscal_metadata", "ambiguous")
    if (context.start, context.end) == (year.start, year.end):
        if obs.fiscal_period not in (None, "FY") and current:
            diag(
                "verified_inconsistency",
                "fp_duration_conflict",
                "Current annual window has quarterly fp metadata",
            )
            return result("ambiguous", "conflicting_fiscal_metadata", "ambiguous")
        return result(
            "annual",
            "exact_observed_annual_window",
            "rule_supported",
            year.fiscal_year,
            "FY",
            False,
            None,
        )
    boundaries = {b.quarter: b for b in calendar.quarters if b.fiscal_year == year.fiscal_year}
    matches = [q for q, b in boundaries.items() if context.end == b.end]
    # Q4 only when a reported context starts immediately after observed Q3, never subtraction.
    if context.end == year.end:
        matches.append(4)
    if len(matches) == 1:
        q = matches[0]
        if q < 4:
            evidence.extend(boundaries[q].evidence)
        previous = (
            year.start
            if q == 1
            else (boundaries[q - 1].end + timedelta(days=1) if q - 1 in boundaries else None)
        )
        if q > 1 and q - 1 in boundaries:
            evidence.extend(boundaries[q - 1].evidence)
        single = previous is not None and context.start == previous and _within(days, QUARTER_DAYS)
        ytd = q <= 3 and context.start == year.start and _within(days, YTD_DAYS[q])
        if single or ytd:
            if current and obs.fiscal_period not in (None, f"Q{q}", "FY" if q == 4 else f"Q{q}"):
                diag(
                    "verified_inconsistency",
                    "fp_duration_conflict",
                    "Current fp disagrees with observed quarter boundary",
                )
                return result("ambiguous", "conflicting_fiscal_metadata", "ambiguous")
            return result(
                "single_quarter" if single else "year_to_date",
                "observed_fiscal_start_and_quarter_boundaries",
                "rule_supported",
                year.fiscal_year,
                f"Q{q}" if single else f"YTD-Q{q}",
                single,
                ytd,
            )
    diag(
        "precision_limitation",
        "unclassified_duration",
        "Dates do not establish one supported fiscal period",
    )
    if obs.fiscal_period in ("Q1", "Q2", "Q3"):
        q = int(obs.fiscal_period[1])
        if not (_within(days, QUARTER_DAYS) or _within(days, YTD_DAYS[q])):
            diag(
                "heuristic_warning",
                "fp_duration_conflict",
                "Observed duration does not fit the reporting fp guardrails",
            )
    if not any(_within(days, r) for r in (ANNUAL_DAYS, *YTD_DAYS.values())):
        return result("other_duration", "observed_nonstandard_duration", "observed_shape")
    diag(
        "missing_data",
        "missing_quarter_boundary",
        "Required quarter start/end evidence is unavailable",
    )
    return result("ambiguous", "insufficient_quarter_evidence", "ambiguous")


@dataclass(frozen=True)
class PeriodObservation:
    fact: facts.LinkedFact
    period: PeriodClassification


@dataclass(frozen=True)
class PeriodInspection:
    cik: str
    concept: str
    records: tuple[PeriodObservation, ...]
    calendar: FiscalCalendar
    provenance: facts.FactInspection
    mode: str = "retrospective"


def interpret(inspection: facts.FactInspection) -> PeriodInspection:
    calendar = build_calendar(inspection.cik, inspection.records)
    records = []
    groups = defaultdict(set)
    for r in inspection.records:
        o = r.observation
        if r.context.kind == "duration":
            groups[(o.accession_number, o.taxonomy, o.concept, o.unit)].add(
                (r.context.start, r.context.end)
            )
    for r in inspection.records:
        period = classify_period(r, calendar=calendar)
        o = r.observation
        if r.context.kind == "duration" and any(
            (s, e) != (period.start, period.end) and max(s, period.start) <= min(e, period.end)
            for s, e in groups[(o.accession_number, o.taxonomy, o.concept, o.unit)]
        ):
            diagnostic = Diagnostic(
                "heuristic_warning",
                "overlapping_contexts",
                "Distinct contexts overlap in this filing; quarter/YTD nesting may be normal",
                (o.provenance,),
            )
            period = replace(period, diagnostics=(*period.diagnostics, diagnostic))
        records.append(PeriodObservation(r, period))
    return PeriodInspection(
        inspection.cik, inspection.concept, tuple(records), calendar, inspection
    )


def for_concept(
    cik: str | int,
    concept: str,
    *,
    taxonomy: str | None = None,
    client: SECClient | None = None,
    refresh: bool = False,
) -> PeriodInspection:
    return interpret(
        facts.for_concept(cik, concept, taxonomy=taxonomy, client=client, refresh=refresh)
    )
