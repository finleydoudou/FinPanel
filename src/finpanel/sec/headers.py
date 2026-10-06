"""Minimal SEC header fields only. No document-body or rendered HTML parsing."""

import re
from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from finpanel.errors import ValidationError
from finpanel.models import RawResponse
from finpanel.models.evidence import Diagnostic, Evidence, FilingHeader
from finpanel.sec.common import normalize_cik

ALIASES = {
    "ACCESSION NUMBER": "ACCESSION-NUMBER",
    "CONFORMED SUBMISSION TYPE": "TYPE",
    "FILED AS OF DATE": "FILING-DATE",
    "CONFORMED PERIOD OF REPORT": "PERIOD",
    "PUBLIC DOCUMENT COUNT": "PUBLIC-DOCUMENT-COUNT",
    "CENTRAL INDEX KEY": "CIK",
}


def parse_filing_header(
    source: RawResponse, *, timezone: str | None = "America/New_York"
) -> FilingHeader:
    zone = None
    if timezone is not None:
        try:
            zone = ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError, TypeError) as exc:
            raise ValidationError("Unknown header timezone policy") from exc
    text = source.text()
    if "<SEC-HEADER>" not in text or "</SEC-HEADER>" not in text or "<html" in text.lower():
        raise ValidationError("Expected a complete SEC text header")
    fields: dict[str, list[str]] = {}
    evidence = []
    diagnostics = []
    active = False
    for number, line in enumerate(text.splitlines(), 1):
        if "<SEC-HEADER>" in line:
            active = True
        if "</SEC-HEADER>" in line:
            break
        if not active:
            continue
        tagged = re.fullmatch(r"\s*<([A-Z][A-Z0-9-]*)>([^<]*)\s*", line)
        labeled = re.fullmatch(r"\s*([A-Z][A-Z -]*):\s*(.*?)\s*", line)
        match = tagged or labeled
        if not match:
            continue
        key, value = match.groups()
        key = ALIASES.get(key, key)
        value = value.strip()
        if not value:
            continue
        fields.setdefault(key, []).append(value)
        evidence.append(Evidence(key, value, source.provenance(f"line:{number}")))

    def diag(category, code, message):
        diagnostics.append(Diagnostic(category, code, message, (source.provenance(""),)))

    def single(key):
        values = fields.get(key, [])
        if len(set(values)) > 1:
            diag("verified_inconsistency", "header_field_conflict", f"Conflicting header {key}")
            return None
        return values[0] if values else None

    def day(key):
        raw = single(key)
        if raw is None:
            return None
        try:
            if not re.fullmatch(r"[0-9]{8}", raw):
                raise ValueError
            return datetime.strptime(raw, "%Y%m%d").date()
        except ValueError:
            diag("verified_inconsistency", "malformed_header_date", f"Invalid {key}")
            return None

    accession = single("ACCESSION-NUMBER")
    if accession is None:
        diag("missing_data", "missing_header_accession", "No unambiguous header accession")
    elif not re.fullmatch(r"[0-9]{10}-[0-9]{2}-[0-9]{6}", accession):
        diag("verified_inconsistency", "invalid_header_accession", "Malformed header accession")
        accession = None
    raw_time = single("ACCEPTANCE-DATETIME")
    accepted = None
    policy = timezone or "unspecified"
    if raw_time is None:
        diag("missing_data", "missing_header_acceptance", "No unambiguous header acceptance")
    else:
        try:
            if not re.fullmatch(r"[0-9]{14}", raw_time):
                raise ValueError
            naive = datetime.strptime(raw_time, "%Y%m%d%H%M%S")
            if zone is None:
                diag(
                    "precision_limitation",
                    "naive_header_acceptance",
                    "Header wall time has no timezone policy",
                )
            else:
                candidates = {
                    naive.replace(tzinfo=zone, fold=fold).astimezone(UTC)
                    for fold in (0, 1)
                    if naive.replace(tzinfo=zone, fold=fold)
                    .astimezone(UTC)
                    .astimezone(zone)
                    .replace(tzinfo=None)
                    == naive
                }
                if len(candidates) != 1:
                    diag(
                        "precision_limitation",
                        "ambiguous_header_time",
                        "DST gap/fold cannot identify one instant",
                    )
                else:
                    accepted = candidates.pop()
        except (ValueError, OverflowError):
            diag(
                "verified_inconsistency",
                "malformed_header_acceptance",
                "Invalid header acceptance timestamp",
            )
    ciks = []
    for value in fields.get("CIK", []):
        try:
            ciks.append(normalize_cik(value))
        except ValidationError:
            diag("verified_inconsistency", "invalid_header_cik", "Malformed header CIK")
    count_raw = single("PUBLIC-DOCUMENT-COUNT")
    count = int(count_raw) if count_raw is not None and re.fullmatch(r"[0-9]+", count_raw) else None
    if count_raw is not None and count is None:
        diag("verified_inconsistency", "invalid_document_count", "Malformed public document count")
    return FilingHeader(
        accession,
        tuple(sorted(set(ciks))),
        single("TYPE"),
        day("FILING-DATE"),
        day("PERIOD"),
        accepted,
        raw_time,
        policy,
        count,
        tuple(evidence),
        tuple(diagnostics),
        source.provenance(""),
        {k: tuple(v) for k, v in sorted(fields.items())},
    )
