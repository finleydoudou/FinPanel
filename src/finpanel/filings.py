"""Auditable filing timelines; no financial fact selection or normalization."""

import re
from collections import Counter, defaultdict
from dataclasses import replace
from datetime import UTC, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from finpanel.errors import ValidationError
from finpanel.models import Filing, ParseIssue
from finpanel.models.timeline import Availability, Coverage, FilingEvent, FilingTimeline
from finpanel.sec.client import SECClient
from finpanel.sec.common import normalize_cik
from finpanel.sec.submissions import (
    discover_historical_submissions,
    parse_historical_submissions,
    parse_submissions,
)
from finpanel.serialization import dumps

SEC_DAY_ZONE = ZoneInfo("America/New_York")


def _availability(fields: dict[str, Any], conflicts: tuple[str, ...]) -> Availability:
    if "acceptance_datetime" in conflicts or "filing_date" in conflicts:
        return Availability("unknown", reason="Conflicting source availability metadata")
    accepted = fields["acceptance_datetime"]
    filed = fields["filing_date"]
    midnight = False
    if accepted is not None and accepted.utcoffset() is not None:
        midnight = accepted.astimezone(SEC_DAY_ZONE).timetz().replace(tzinfo=None) == time.min
        if not midnight:
            return Availability(
                "acceptance_datetime",
                timestamp=accepted.astimezone(UTC),
                reason="SEC acceptance timestamp used as availability proxy",
            )
    if filed is not None:
        reason = "Acceptance missing or invalid; filing date only"
        if midnight:
            reason = "SEC-local midnight acceptance may be date-derived; filing date only"
        elif accepted is not None:
            reason = "Acceptance has no timezone; filing date only"
        return Availability("date_only", date=filed, reason=reason)
    return Availability("unknown", reason="No reliable acceptance timestamp or filing date")


def _merge(cik: str, records: list[Filing], issues: list[ParseIssue]) -> tuple[FilingEvent, ...]:
    groups: dict[str, list[Filing]] = defaultdict(list)
    for record in records:
        if not re.fullmatch(r"[0-9]{10}-[0-9]{2}-[0-9]{6}", record.accession_number):
            issues.append(
                ParseIssue(
                    "invalid_accession",
                    "Unusable SEC accession; row retained in issue",
                    record.provenance,
                    record.raw,
                )
            )
            continue
        groups[record.accession_number].append(record)
    result = []
    for accession, rows in sorted(groups.items()):
        rows.sort(
            key=lambda r: (
                r.provenance.source_url,
                r.provenance.response_sha256,
                r.provenance.pointer,
                dumps(r.raw),
            )
        )
        fields = {}
        conflicts = []
        for field in (
            "form",
            "filing_date",
            "report_date",
            "acceptance_datetime",
            "primary_document",
        ):
            values = [getattr(r, field) for r in rows if getattr(r, field) is not None]
            if values and any(v != values[0] for v in values[1:]):
                conflicts.append(field)
                fields[field] = None
            else:
                fields[field] = values[0] if values else None
        conflict_fields = tuple(conflicts)
        for field in conflicts:
            issues.append(
                ParseIssue(
                    "conflicting_metadata",
                    f"Accession {accession}: conflicting {field}",
                    rows[0].provenance,
                    {
                        "accession": accession,
                        "field": field,
                        "values": [getattr(r, field) for r in rows],
                    },
                )
            )
        form = fields["form"]
        result.append(
            FilingEvent(
                cik,
                accession,
                **fields,
                is_amendment=form.endswith("/A") if form else None,
                availability=_availability(fields, conflict_fields),
                conflicts=conflict_fields,
                source_records=tuple(rows),
            )
        )
    return tuple(sorted(result, key=_order))


def _order(event: FilingEvent) -> tuple:
    availability = event.availability
    if availability.timestamp is not None:
        point = availability.timestamp.astimezone(UTC)
    elif availability.date is not None:
        # This key is ordering only, not an asserted publication timestamp.
        point = datetime.combine(availability.date, time.min, SEC_DAY_ZONE).astimezone(UTC)
    else:
        return (1, datetime.max.replace(tzinfo=UTC), "unknown", event.accession_number)
    return (0, point, availability.precision, event.accession_number)


def timeline(
    cik: str | int, *, client: SECClient | None = None, refresh: bool = False
) -> FilingTimeline:
    """Load recent and every valid referenced history file; failed downloads raise.

    Pass a SECClient(offline=True) with a populated cache for guaranteed offline use.
    Caller-owned clients remain open. The default client reads FINPANEL_SEC_USER_AGENT.
    """
    cik = normalize_cik(cik)
    if client is None:
        with SECClient() as owned:
            return timeline(cik, client=owned, refresh=refresh)
    parent = client.submissions(cik, refresh=refresh)
    parent_data = parent.json()
    if normalize_cik(parent_data.get("cik")) != cik:
        raise ValidationError("Cached submissions CIK does not match the requested company")
    recent = parse_submissions(parent)
    discovery = discover_historical_submissions(parent)
    records = list(recent.records)
    issues = list(recent.issues + discovery.issues)
    sources = [parent.provenance("")]
    references = tuple(sorted(discovery.records, key=lambda r: (r.name, r.provenance.pointer)))
    loaded = []
    for filename in sorted({r.name for r in references}):
        source = client.historical_submissions(cik, filename, refresh=refresh)
        parsed = parse_historical_submissions(
            source,
            cik=cik,
            entity_name=parent_data.get("name")
            if isinstance(parent_data.get("name"), str)
            else None,
            fiscal_year_end=recent.metadata["fiscal_year_end"],
        )
        records.extend(parsed.records)
        issues.extend(parsed.issues)
        sources.append(source.provenance(""))
        loaded.append(filename)
        dates = [r.filing_date for r in parsed.records if r.filing_date is not None]
        for ref in (r for r in references if r.name == filename):
            if ref.filing_count is not None and ref.filing_count != len(parsed.records):
                issues.append(
                    ParseIssue(
                        "history_count_mismatch",
                        f"{filename}: parent expects {ref.filing_count}, "
                        f"parsed {len(parsed.records)}",
                        ref.provenance,
                        ref.raw,
                    )
                )
            if dates and (
                (ref.filing_from is not None and min(dates) != ref.filing_from)
                or (ref.filing_to is not None and max(dates) != ref.filing_to)
            ):
                issues.append(
                    ParseIssue(
                        "history_range_mismatch",
                        f"{filename}: filing dates differ from parent range",
                        ref.provenance,
                        ref.raw,
                    )
                )
    events = _merge(cik, records, issues)
    return FilingTimeline(cik, events, tuple(issues), tuple(sources), references, tuple(loaded))


def _cutoff(value: str | datetime) -> datetime:
    try:
        cutoff = (
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            if isinstance(value, str)
            else value
        )
    except ValueError as exc:
        raise ValidationError("as_of must be an ISO datetime with an explicit timezone") from exc
    if not isinstance(cutoff, datetime) or cutoff.utcoffset() is None:
        raise ValidationError("as_of must be an ISO datetime with an explicit timezone")
    return cutoff.astimezone(UTC)


def available_as_of(
    company: str | int | FilingTimeline,
    as_of: str | datetime,
    *,
    client: SECClient | None = None,
    refresh: bool = False,
) -> FilingTimeline:
    """Inclusive acceptance cutoff; date-only filings enter after the SEC local day.

    Unknown/conflicting availability is excluded. Source coverage and issues remain
    attached to the filtered result. Acceptance is a proxy, not verified dissemination.
    """
    cutoff = _cutoff(as_of)
    data = (
        company
        if isinstance(company, FilingTimeline)
        else timeline(company, client=client, refresh=refresh)
    )
    if data.as_of is not None and cutoff > data.as_of:
        raise ValidationError(
            "Cannot widen an already-filtered timeline; use the original timeline"
        )
    day = cutoff.astimezone(SEC_DAY_ZONE).date()
    records = tuple(
        event
        for event in data
        if (event.availability.timestamp is not None and event.availability.timestamp <= cutoff)
        or (event.availability.precision == "date_only" and event.availability.date < day)
    )
    return replace(data, records=records, as_of=cutoff)


def coverage(
    company: str | int | FilingTimeline, *, client: SECClient | None = None, refresh: bool = False
) -> Coverage:
    """Summarize observed source coverage; never infer completeness from silence."""
    data = (
        company
        if isinstance(company, FilingTimeline)
        else timeline(company, client=client, refresh=refresh)
    )
    dates = [r.filing_date for r in data if r.filing_date is not None]
    precision = Counter(r.availability.precision for r in data)
    gaps = [
        f"{code}: {count}" for code, count in sorted(Counter(i.code for i in data.issues).items())
    ]
    if not data.records:
        gaps.append("No usable filing events")
    if precision["unknown"]:
        gaps.append(f"Unknown availability: {precision['unknown']}")
    if precision["date_only"]:
        gaps.append(f"Intraday availability unresolved: {precision['date_only']}")
    missing_dates = sum(r.filing_date is None for r in data)
    if missing_dates:
        gaps.append(f"Filing date unavailable: {missing_dates}")
    missing_forms = sum(r.form is None for r in data)
    if missing_forms:
        gaps.append(f"Form unavailable: {missing_forms}")
    return Coverage(
        data.cik,
        min(dates) if dates else None,
        max(dates) if dates else None,
        len(data),
        dict(sorted(Counter(r.form or "(missing)" for r in data).items())),
        sum(r.is_amendment is True for r in data),
        precision["acceptance_datetime"],
        precision["date_only"],
        precision["unknown"],
        sum(len(r.source_records) > 1 for r in data),
        sum(len(r.source_records) for r in data),
        len({r.name for r in data.historical_references}),
        len(data.historical_files_loaded),
        tuple(gaps),
    )
