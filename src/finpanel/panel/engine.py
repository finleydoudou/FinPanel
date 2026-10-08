"""Within-build orchestration of the existing audited resolution engines."""

from collections import Counter
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal

from finpanel import filings, metrics, xbrl
from finpanel.errors import CacheMissError, FinPanelError, ValidationError
from finpanel.metrics.derivation_models import DERIVABLE_METRICS
from finpanel.models import ParseIssue
from finpanel.models.timeline import FilingTimeline
from finpanel.panel.models import SCHEMA, PanelRequest, PanelRow
from finpanel.sec import parse_submissions
from finpanel.sec.client import SECClient
from finpanel.sec.submissions import discover_historical_submissions
from finpanel.snapshots.pipeline import CONTRACTS, _PinnedCache, _provenance, software_identity
from finpanel.snapshots.store import EvidenceStore, SnapshotError, digest


class PanelBuildError(FinPanelError):
    """Strict build encountered an unresolved grid cell."""


def row_record(row):
    """Canonical portable record: exact value spelling plus explicit Python number kind."""
    result = asdict(row)
    result["value"] = None if row.value is None else str(row.value)
    result["value_kind"] = (
        None if row.value is None else "decimal" if isinstance(row.value, Decimal) else "integer"
    )
    return result


@dataclass(frozen=True)
class PanelReceipt:
    receipt_id: str
    semantic: dict
    created_at: str


@dataclass(frozen=True)
class PanelResult:
    request: PanelRequest
    rows: tuple[PanelRow, ...]
    receipt: PanelReceipt
    provenance: dict
    results: dict
    performance: dict

    def inspect(self, row_id):
        if row_id not in self.provenance:
            raise ValidationError("Unknown panel row ID")
        return {
            "row": next(r for r in self.rows if r.row_id == row_id),
            "canonical_result": self.results.get(row_id),
            "evidence": self.provenance[row_id],
            "build_receipt": self.receipt,
        }

    def coverage(self):
        return {
            "requested_cells": len(self.rows),
            "states": dict(sorted(Counter(r.state for r in self.rows).items())),
            "reasons": dict(sorted(Counter(x for r in self.rows for x in r.reasons).items())),
            "by_dimension": {
                dimension: [
                    {"value": key[0], "state": key[1], "count": count}
                    for key, count in sorted(
                        Counter((str(getattr(r, dimension)), r.state) for r in self.rows).items()
                    )
                ]
                for dimension in ("cik", "metric", "fiscal_year", "period", "as_of")
            },
            "cells": [
                dict(
                    row_id=r.row_id,
                    cik=r.cik,
                    metric=r.metric,
                    fiscal_year=r.fiscal_year,
                    period=r.period,
                    as_of=r.as_of,
                    state=r.state,
                    reasons=r.reasons,
                )
                for r in self.rows
            ],
        }


class _FrozenClient:
    """Pin raw responses within this build only. Never cache across builds."""

    def __init__(self, client):
        self.client, self.raw = client, {}
        self.hits = 0

    def __getattr__(self, name):
        method = getattr(self.client, name)

        def call(*args, **kwargs):
            key = (name, args, tuple(sorted(kwargs.items())))
            if key in self.raw:
                self.hits += 1
                return self.raw[key]
            result = method(*args, **kwargs)
            self.raw[key] = result
            return result

        return call


def _timeline(cik, client, scope):
    if scope == "complete":
        return filings.timeline(cik, client=client)
    # Explicit scope, never an automatic fallback after missing history. Reuse
    # existing parsing/merging and retain unknown availability for unlinked facts.
    raw = client.submissions(cik)
    parsed = parse_submissions(raw)
    if str(raw.json().get("cik")).zfill(10) != cik:
        raise ValidationError("Submissions CIK mismatch")
    refs = discover_historical_submissions(raw)
    issues = list(parsed.issues + refs.issues)
    issues.append(
        ParseIssue(
            "panel_recent_only",
            "Referenced history explicitly excluded",
            raw.provenance("/filings/files"),
            parsed.metadata["history_files"],
        )
    )
    return FilingTimeline(
        cik,
        filings._merge(cik, list(parsed.records), issues),
        tuple(issues),
        (parsed.source,),
        refs.records,
        (),
    )


def _pin(result, sid):
    if isinstance(result, metrics.MetricResult):
        return replace(result, evidence_snapshot_id=sid)
    return replace(
        result,
        evidence_snapshot_id=sid,
        minuend=_pin(result.minuend, sid) if result.minuend else None,
        subtrahend=_pin(result.subtrahend, sid) if result.subtrahend else None,
    )


def _operands(result):
    return (
        tuple(x for x in (result.minuend, result.subtrahend) if x)
        if isinstance(result, metrics.QuarterDerivation)
        else (result,)
    )


def _candidate(c):
    o = c.observation.fact.observation
    return {
        "observation_id": o.observation_id,
        "accession": o.accession_number,
        "taxonomy": o.taxonomy,
        "concept": o.concept,
        "unit": o.unit,
        "value": str(o.value),
        "value_kind": "decimal" if isinstance(o.value, Decimal) else "integer",
        "period": c.observation.period.identity,
        "source": o.provenance,
        "eligibility": c.observation.eligibility,
        "calendar_evidence": c.observation.supporting_evidence,
    }


def _audit(result, verification, limitations):
    operands = _operands(result)
    return {
        "source_type": result.source_type,
        "selected": [[_candidate(c) for c in r.selected] for r in operands],
        "considered": [[_candidate(c) for c in r.considered] for r in operands],
        "rejected": [
            [
                {
                    "observation_id": x.fact.observation_id,
                    "reasons": x.reasons,
                    "source": x.fact.observation.provenance,
                    "eligibility": x.eligibility,
                }
                for x in r.target_rejections
            ]
            for r in operands
        ],
        "revision_groups": [
            [
                {
                    "identity": g.identity,
                    "status": g.status,
                    "conflicts": g.conflicts,
                    "selected_observation_ids": g.selected_observation_ids,
                    "candidates": [
                        {"observation_id": c.observation.fact.observation_id, "status": c.status}
                        for c in g.candidates
                    ],
                }
                for g in r.revision_groups
            ]
            for r in operands
        ],
        "sources": _provenance(tuple(r.selected for r in operands)),
        "verification": verification,
        "source_limitations": sorted(limitations),
        "derivation_availability": result.availability
        if isinstance(result, metrics.QuarterDerivation)
        else None,
        "derivation_contract": result.contract
        if isinstance(result, metrics.QuarterDerivation)
        else None,
    }


def _reason_codes(state, result, reasons):
    codes = set(reasons)
    if state == "ambiguous_period":
        codes.add("period_ambiguous")
    if state == "conflicted":
        codes.add(
            "unit_conflict" if any("unit" in x for x in codes) else "revision_or_scope_conflict"
        )
    if state == "source_verification_failed":
        codes.add("source_verification_failure")
    if isinstance(result, metrics.QuarterDerivation) and result.value is None:
        codes.add("insufficient_cumulative_operands")
    if state == "unavailable" and isinstance(result, metrics.MetricResult):
        codes.add("no_eligible_reported_observation")
    return tuple(sorted(codes))


def build(
    request: PanelRequest | None = None,
    *,
    store: EvidenceStore | None = None,
    client: SECClient | None = None,
    **grid,
) -> PanelResult:
    """Build every requested cell; pinned mode disallows any external client/fallback.

    One exact snapshot ID serves the entire dataset. Select latest/scope manifests
    explicitly with EvidenceStore.select before invoking this API.
    """
    if request is not None and grid:
        raise ValidationError("Supply a request or grid keywords, not both")
    request = PanelRequest(**grid) if request is None else request
    if not isinstance(request, PanelRequest):
        raise ValidationError("request must be PanelRequest")
    if request.snapshot_id and (store is None or client is not None):
        raise ValidationError("Pinned panels require a store and prohibit external clients")
    if not request.snapshot_id and store is not None:
        raise ValidationError("Store requires an explicit snapshot_id")
    snapshot = store.select(snapshot_id=request.snapshot_id) if request.snapshot_id else None
    cache = _PinnedCache(store, snapshot) if snapshot else None
    owned = client is None
    active = (
        client
        if client is not None
        else (SECClient(cache=cache, offline=True) if snapshot else SECClient())
    )
    try:
        return _build(request, _FrozenClient(active), snapshot, cache)
    finally:
        if owned:
            active.close()


def _build(request, client, snapshot, cache):
    import time

    started = time.perf_counter()
    software = software_identity()
    rows, provenance, results = [], {}, {}
    # All reuse is scoped to this build; canonical results share candidate evidence.
    reports, timelines, metadata, instances, parsed_filings = {}, {}, {}, {}, {}
    candidate_builds = candidate_hits = 0
    sid = request.snapshot_id
    mode = "exact_pinned_snapshot" if sid else "unsnapshotted_within_build"
    for cik, cutoff, year, period, metric in request.grid():
        cell = dict(cik=cik, as_of=cutoff, fiscal_year=year, period=period, metric=metric)
        rid = digest(cell)
        original = verified = None
        name = ticker = None
        state, value, unit, interval, source_type = "unavailable", None, None, None, None
        reasons, conflicts, limitations = [], [], []
        verification_state = "off"
        audit = {}
        try:
            if cik not in timelines:
                timelines[cik] = _timeline(cik, client, request.timeline_scope)
                raw = client.submissions(cik).json()
                tickers = raw.get("tickers", [])
                name = raw.get("name")
                ticker = tickers[0] if isinstance(tickers, list) and tickers else None
                metadata[cik] = (
                    name if isinstance(name, str) else None,
                    ticker if isinstance(ticker, str) else None,
                )
            name, ticker = metadata[cik]
            if request.timeline_scope == "recent_only":
                reasons.append("timeline_recent_only")
            key = (cik, cutoff, metric)
            if key not in reports:
                reports[key] = metrics.candidates(
                    cik, metric, as_of=cutoff, client=client, filing_timeline=timelines[cik]
                )
                candidate_builds += 1
            else:
                candidate_hits += 1
            report = reports[key]
            if metrics.REGISTRY[metric].context == "instant":
                end = request.instant_end(cik, year, period)
                if end is None or request.source_policy == "derived_only":
                    state = "unsupported"
                    reasons.append(
                        "explicit_instant_end_required"
                        if end is None
                        else "instant_derivation_unsupported"
                    )
                else:
                    original = metrics.resolve_candidates(
                        report, end=end, revision_policy=request.revision_policy
                    )
            elif request.source_policy == "derived_only" and period not in {"Q1", "Q2", "Q3", "Q4"}:
                state = "unsupported"
                reasons.append("derived_only_requires_quarter")
            elif request.source_policy == "derived_only":
                original = metrics.derive_from_candidates(
                    report,
                    fiscal_year=year,
                    quarter=period,
                    revision_policy=request.revision_policy,
                )
            elif (
                request.source_policy == "reported_then_derived"
                and period.startswith("Q")
                and metric in DERIVABLE_METRICS
            ):
                choice = metrics.resolve_quarter_candidates(
                    report,
                    fiscal_year=year,
                    quarter=period,
                    revision_policy=request.revision_policy,
                    source_policy=request.source_policy,
                )
                original = choice.derivation or choice.reported
                reasons.extend(choice.diagnostics)
            else:
                original = metrics.resolve_candidates(
                    report, fiscal_year=year, period=period, revision_policy=request.revision_policy
                )
            if original is not None:
                original = _pin(original, sid)
                derived = isinstance(original, metrics.QuarterDerivation)
                state = original.status if derived else original.state
                state = {
                    "eligible": "resolved_derived",
                    "resolved": "resolved_reported",
                    "ineligible": "unsupported",
                }.get(state, state)
                value, unit = original.value, original.unit
                interval = original.target_interval if derived else original.represented_period
                source_type = original.source_type
                reasons.extend(original.diagnostics)
                reasons.extend(original.reasons if derived else original.conflicts)
                conflicts.extend(x for r in _operands(original) for x in r.conflicts)
                if request.source_verification != "off":
                    if cik not in parsed_filings:
                        parsed_filings[cik] = {
                            f.accession_number: f
                            for f in parse_submissions(client.submissions(cik)).records
                        }
                    filings_by_acc = parsed_filings[cik]
                    accessions = sorted(
                        {
                            c.observation.fact.observation.accession_number
                            for r in _operands(original)
                            for c in r.considered
                            if c.observation.fact.observation.accession_number
                        }
                    )
                    found = []
                    for acc in accessions:
                        ikey = (cik, acc)
                        if ikey not in instances:
                            try:
                                if acc not in filings_by_acc:
                                    raise ValidationError("filing_not_in_recent_snapshot")
                                instances[ikey] = (
                                    xbrl.inspect_filing(filings_by_acc[acc], client=client)[1],
                                    None,
                                )
                            except SnapshotError:
                                raise
                            except FinPanelError as exc:
                                instances[ikey] = ((), type(exc).__name__)
                        evidence, limitation = instances[ikey]
                        found.extend(evidence)
                        if limitation:
                            limitations.append(acc + ":" + limitation)
                    verify = xbrl.verify_derivation if derived else xbrl.verify_metric
                    verified = verify(
                        original,
                        instances=tuple(found),
                        source_verification=request.source_verification,
                    )
                    value = verified.value
                    if verified.state == "source_verification_rejected":
                        state = "source_verification_failed"
                    reasons.extend(verified.diagnostics)
                    checks = (
                        tuple(
                            v
                            for r in (verified.minuend, verified.subtrahend)
                            if r
                            for v in r.selected
                        )
                        if derived
                        else verified.selected
                    )
                    verification_state = (
                        ",".join(sorted({v.state for v in checks})) or "no_selected_source"
                    )
                audit = _audit(original, verified, limitations)
                # Verification envelopes contain a full original result; keep them for inspect,
                # but export compact source decisions, not all aggregate SEC observations.
                if verified:
                    checks = (
                        tuple(
                            v
                            for r in (verified.minuend, verified.subtrahend)
                            if r
                            for v in r.selected
                        )
                        if derived
                        else verified.selected
                    )
                    audit["verification"] = [
                        {"state": v.state, "scope_state": v.scope_state, "sources": _provenance(v)}
                        for v in checks
                    ]
        except (FinPanelError, OSError) as exc:
            if request.errors == "raise":
                raise
            state, value, unit, interval, source_type = (
                "insufficient_evidence",
                None,
                None,
                None,
                None,
            )
            reasons = [
                ("pinned_snapshot_missing_evidence" if sid else "source_unavailable")
                if isinstance(exc, CacheMissError)
                else "evidence_integrity_failure"
                if isinstance(exc, SnapshotError)
                else "source_processing_failure"
            ]
            audit = {"error_type": type(exc).__name__, "reason": reasons[0]}
        selected = tuple(c for r in _operands(original) for c in r.selected) if original else ()
        facts = [c.observation.fact for c in selected]
        reasons = _reason_codes(state, original, reasons)
        audit.update(
            cell=cell,
            snapshot_id=sid,
            evidence_mode=mode,
            policies={
                "revision": request.revision_policy,
                "source": request.source_policy,
                "verification": request.source_verification,
                "timeline_scope": request.timeline_scope,
            },
        )
        audit["decision"] = dict(
            state=state,
            value=None if value is None else str(value),
            unit=unit,
            reasons=reasons,
            conflicts=conflicts,
        )
        receipt_id = digest(audit)
        row = PanelRow(
            rid,
            cik,
            name,
            ticker,
            metric,
            year,
            period,
            interval.start if interval else None,
            interval.end if interval else None,
            cutoff,
            request.revision_policy,
            request.source_policy,
            state,
            value,
            unit,
            source_type,
            tuple(sorted({f.observation.concept for f in facts})),
            tuple(sorted({f.observation.taxonomy for f in facts})),
            tuple(
                sorted(
                    {
                        f.observation.accession_number
                        for f in facts
                        if f.observation.accession_number
                    }
                )
            ),
            tuple(asdict(f.availability) for f in facts),
            verification_state,
            sid,
            mode,
            receipt_id,
            reasons,
            tuple(sorted(set(conflicts))),
        )
        if request.errors == "raise" and not row.state.startswith("resolved_"):
            raise PanelBuildError(f"Unresolved grid cell {rid}: {row.state}")
        rows.append(row)
        provenance[rid] = audit
        results[rid] = verified or original
    semantic = {
        "format": SCHEMA,
        "request": asdict(request),
        "software": software,
        "contracts": CONTRACTS,
        "evidence_mode": mode,
        "snapshot_id": sid,
        "row_hash": digest([row_record(r) for r in rows]),
        "row_receipts": [r.receipt_id for r in rows],
        "artifacts": [
            dict(capture_id=a.capture_id, sha256=a.sha256, source_url=a.source_url)
            for _, a in sorted(cache.used.items())
        ]
        if cache
        else sorted({(r.url, r.sha256) for r in client.raw.values()}),
        "missing_requests": sorted(cache.missing) if cache else [],
        "snapshot_completeness": snapshot.manifest["completeness"] if snapshot else None,
    }
    receipt = PanelReceipt(digest(semantic), semantic, datetime.now(UTC).isoformat())
    return PanelResult(
        request,
        tuple(rows),
        receipt,
        provenance,
        results,
        {
            "wall_seconds": time.perf_counter() - started,
            "candidate_builds": candidate_builds,
            "candidate_reuses": candidate_hits,
            "raw_response_reuses": client.hits,
        },
    )


def reproduce(receipt: PanelReceipt, *, store: EvidenceStore) -> PanelResult:
    """Fail closed on missing/corrupt evidence, changed software, or semantic mismatch."""
    if digest(receipt.semantic) != receipt.receipt_id or receipt.semantic.get("format") != SCHEMA:
        raise SnapshotError("Panel receipt integrity/format failure")
    if not receipt.semantic.get("snapshot_id"):
        raise SnapshotError("Unpinned panels cannot promise exact replay")
    if (
        receipt.semantic["software"] != software_identity()
        or receipt.semantic["contracts"] != CONTRACTS
    ):
        raise SnapshotError("Panel software/contract mismatch")
    actual = build(PanelRequest(**receipt.semantic["request"]), store=store)
    if actual.receipt.receipt_id != receipt.receipt_id:
        raise SnapshotError("Panel replay semantic mismatch or missing evidence")
    return actual
