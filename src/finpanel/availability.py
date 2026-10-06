"""Compare SEC metadata without treating acceptance as proven dissemination."""

from dataclasses import dataclass, replace
from datetime import UTC, time

from finpanel.filings import SEC_DAY_ZONE
from finpanel.models.evidence import Diagnostic, FilingHeader
from finpanel.models.timeline import Availability, FilingEvent


@dataclass(frozen=True)
class AvailabilityValidation:
    filing: FilingEvent
    availability: Availability
    headers: tuple[FilingHeader, ...]
    diagnostics: tuple[Diagnostic, ...]
    policy: str = "sec-header-corroboration-v1"
    comparison_status: str = "not_checked"


def validate(event: FilingEvent, headers: tuple[FilingHeader, ...] = ()) -> AvailabilityValidation:
    """Conflict => unknown. Otherwise corroborate submissions, or fill from a header.

    Agreement does not elevate acceptance to a public-dissemination timestamp.
    Filing/report date anomalies are warnings because date adjustment is possible.
    """
    headers = tuple(
        sorted(headers, key=lambda h: (h.provenance.source_url, h.provenance.response_sha256))
    )
    diagnostics = []
    evidence = list(event.availability.evidence)
    sources = tuple(r.provenance for r in event.source_records)

    def diag(category, code, message, refs=sources):
        diagnostics.append(Diagnostic(category, code, message, refs))

    if not headers:
        diag(
            "missing_data",
            "header_not_checked",
            "No filing header supplied; submissions proxy only",
        )
    for row in event.source_records:
        raw = row.raw.get("acceptanceDateTime")
        if raw in (None, ""):
            diag(
                "missing_data",
                "missing_acceptance",
                "Submissions acceptance missing",
                (row.provenance,),
            )
        elif row.acceptance_datetime is None:
            diag(
                "verified_inconsistency",
                "malformed_acceptance",
                "Submissions acceptance cannot be parsed",
                (row.provenance,),
            )
        elif row.acceptance_datetime.utcoffset() is None:
            diag(
                "precision_limitation",
                "naive_acceptance",
                "Submissions timestamp has no timezone",
                (row.provenance,),
            )
    for field in event.conflicts:
        diag("verified_inconsistency", "submissions_conflict", f"Conflicting submissions {field}")
    fatal = bool(set(event.conflicts) & {"filing_date", "acceptance_datetime"})
    for header in headers:
        evidence.extend(
            replace(e, interpretation=f"SEC header; wall-time policy: {header.timezone_policy}")
            for e in header.evidence
        )
        diagnostics.extend(header.diagnostics)
        refs = sources + (header.provenance,)
        if header.accession_number != event.accession_number or (
            header.ciks and event.cik not in header.ciks
        ):
            diag(
                "verified_inconsistency",
                "header_identity_mismatch",
                "Header cannot be linked to the requested filing",
                refs,
            )
            fatal = True
        if not header.ciks:
            diag(
                "missing_data",
                "missing_header_cik",
                "Header has no issuer CIK; accession is the link",
                refs,
            )
        if any(d.code == "header_field_conflict" for d in header.diagnostics):
            fatal = True
        for field in ("form", "filing_date", "report_date"):
            a, b = getattr(event, field), getattr(header, field)
            if a is not None and b is not None and a != b:
                diag(
                    "verified_inconsistency",
                    "metadata_mismatch",
                    f"Header and submissions disagree on {field}",
                    refs,
                )
                fatal = True
            elif a is None or b is None:
                diag(
                    "missing_data",
                    "missing_comparison_field",
                    f"Cannot compare {field} in both sources",
                    refs,
                )

    # Even an unusable midnight value still participates in source conflict detection.
    times = [
        r.acceptance_datetime
        for r in event.source_records
        if r.acceptance_datetime is not None and r.acceptance_datetime.utcoffset() is not None
    ]
    times += [h.acceptance_datetime for h in headers if h.acceptance_datetime is not None]
    normalized = []
    for value in times:
        try:
            normalized.append(value.astimezone(UTC))
        except (ValueError, OverflowError):
            diag(
                "verified_inconsistency",
                "unrepresentable_acceptance",
                "Acceptance cannot be represented in UTC",
            )
            fatal = True
    if len(set(normalized)) > 1:
        diag(
            "verified_inconsistency",
            "acceptance_mismatch",
            "SEC sources have different acceptance instants",
            sources + tuple(h.provenance for h in headers),
        )
        fatal = True
    # Compare headers to each other even when submissions has no usable field.
    for field in ("filing_date", "report_date", "form"):
        values = {getattr(h, field) for h in headers if getattr(h, field) is not None}
        if len(values) > 1:
            diag(
                "verified_inconsistency", "header_metadata_mismatch", f"Headers disagree on {field}"
            )
            fatal = True
    result = replace(event.availability, evidence=tuple(evidence))
    if fatal:
        result = Availability(
            "unknown",
            reason="Conflicting SEC evidence; no source selected",
            evidence=tuple(evidence),
        )
    elif result.precision != "acceptance_datetime":
        candidates = [
            t
            for t in normalized
            if t.astimezone(SEC_DAY_ZONE).timetz().replace(tzinfo=None) != time.min
        ]
        header_times = {h.acceptance_datetime for h in headers if h.acceptance_datetime is not None}
        if candidates and candidates[0] in header_times:
            result = Availability(
                "acceptance_datetime",
                timestamp=candidates[0],
                reason="Filing-header acceptance proxy under explicit timezone policy",
                method="filing_header_acceptance",
                evidence=tuple(evidence),
            )
        elif result.precision == "unknown":
            dates = {h.filing_date for h in headers if h.filing_date is not None}
            if len(dates) == 1:
                result = Availability(
                    "date_only",
                    date=dates.pop(),
                    reason="Header filing date only",
                    method="filing_date_fallback",
                    evidence=tuple(evidence),
                )
    if result.precision != "acceptance_datetime":
        diag("precision_limitation", "limited_availability_precision", result.reason)
    if any(
        t.astimezone(SEC_DAY_ZONE).timetz().replace(tzinfo=None) == time.min for t in normalized
    ):
        diag(
            "heuristic_warning",
            "midnight_acceptance",
            "Midnight may be date-derived; not proof of a bad filing",
        )
    for value in normalized:
        accepted_day = value.astimezone(SEC_DAY_ZONE).date()
        report_dates = {
            d for d in [event.report_date, *(h.report_date for h in headers)] if d is not None
        }
        if any(value_date > accepted_day for value_date in report_dates):
            diag(
                "heuristic_warning",
                "acceptance_before_report_end",
                "Acceptance precedes report date; inspect source context",
            )
        if event.filing_date is not None and accepted_day > event.filing_date:
            diag(
                "heuristic_warning",
                "acceptance_after_filing_day",
                "Filing date precedes acceptance day; adjustments are possible",
            )
    diagnostics = tuple(
        sorted(
            set(diagnostics),
            key=lambda d: (
                d.category,
                d.code,
                d.message,
                tuple((s.source_url, s.response_sha256, s.pointer) for s in d.sources),
            ),
        )
    )
    status = "not_checked"
    if fatal:
        status = "conflict"
    elif headers:
        status = "insufficient_evidence"
        if result.method == "filing_header_acceptance":
            status = "header_only"
        elif result.timestamp is not None and any(
            h.acceptance_datetime == result.timestamp for h in headers
        ):
            status = "acceptance_corroborated"
    return AvailabilityValidation(event, result, headers, diagnostics, comparison_status=status)
