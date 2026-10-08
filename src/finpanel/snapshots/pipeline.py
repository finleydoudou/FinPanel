"""Pinned offline pipelines and compact, deterministic replay receipts."""

import importlib.metadata
import platform
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from finpanel import __version__, metrics, xbrl
from finpanel.errors import FinPanelError
from finpanel.models import Provenance
from finpanel.sec import parse_companyfacts, parse_submissions
from finpanel.sec.client import SECClient
from finpanel.serialization import dumps, loads
from finpanel.snapshots.store import EvidenceStore, SnapshotError, digest, timestamp

RECEIPT_FORMAT = "finpanel-receipt-v1"
CONTRACTS = {
    "canonical": "explicit-reported-metrics-v1",
    "derivation": "exact-concept-reported-cumulative-difference-v1",
    "original_verification": "retrieval-bounded-xbrl-v1",
    "snapshot_query": "pinned-query-v1",
}


def software_identity():
    root = Path(__file__).resolve().parents[1]
    code = {
        str(p.relative_to(root)): sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*.py"))
    }
    return {
        "finpanel": __version__,
        "code_sha256": digest(code),
        "python": platform.python_version(),
        "dependencies": {
            name: importlib.metadata.version(name) for name in ("httpx", "simplejson")
        },
    }


class _PinnedCache:
    def __init__(self, store, snapshot):
        self.store = store
        self.artifacts = {
            a["source_url"]: store._artifact(a) for a in snapshot.manifest["artifacts"]
        }
        self.used = {}
        self.missing = set()

    def get(self, url):
        artifact = self.artifacts.get(url)
        if artifact is None:
            self.missing.add(url)
            return None
        if artifact.raw_format == "binary":
            raise SnapshotError("Binary artifact cannot serve JSON/text pipeline")
        expected = None
        if url.startswith("https://data.sec.gov/api/xbrl/companyfacts/"):
            expected = "companyfacts"
        elif url.startswith("https://data.sec.gov/submissions/"):
            expected = "historical_submissions" if "-submissions-" in url else "submissions"
        elif url.endswith("/index.json") or url.endswith("-index.html"):
            expected = "filing_directory"
        elif url.endswith(".hdr.sgml"):
            expected = "filing_header"
        if expected and artifact.source_family != expected:
            raise SnapshotError("Source family does not match the requested endpoint")
        self.used[url] = artifact
        return self.store.raw(artifact)

    def put(self, raw):
        raise SnapshotError("Pinned evidence is read-only")


@dataclass(frozen=True)
class Receipt:
    receipt_id: str
    semantic: dict
    executed_at: str


@dataclass(frozen=True)
class PinnedResult:
    result: object
    reproducibility: Receipt
    snapshot_id: str
    operand_snapshot_ids: tuple[str, ...]
    evidence_mode: str = "exact_pinned_snapshot"


@dataclass(frozen=True)
class Replay:
    verified: bool
    reason: str
    expected_receipt_id: str
    actual_receipt_id: str | None = None


def _provenance(value):
    """Collect compact immutable source pointers, not entire evidence payloads."""
    from dataclasses import fields, is_dataclass

    found = set()
    seen = set()

    def walk(obj):
        if id(obj) in seen:
            return
        seen.add(id(obj))
        if isinstance(obj, Provenance):
            found.add((obj.source_url, obj.response_sha256, obj.pointer))
        elif is_dataclass(obj):
            for f in fields(obj):
                walk(getattr(obj, f.name))
        elif isinstance(obj, dict):
            for v in obj.values():
                walk(v)
        elif isinstance(obj, (list, tuple)):
            for v in obj:
                walk(v)

    walk(value)
    return [dict(source_url=u, sha256=h, pointer=p) for u, h, p in sorted(found)]


def run(
    store: EvidenceStore,
    *,
    snapshot_id: str,
    operation: str,
    cik: str | int,
    as_of: str,
    metric: str | None = None,
    parameters: dict | None = None,
    source_verification: str = "off",
    executed_at: str | None = None,
) -> PinnedResult:
    """No cache fallback and no caller-supplied operands: one snapshot supplies the whole query."""
    if operation not in {"resolve", "derive_quarter", "verify_fact"}:
        raise SnapshotError("Unsupported replay operation")
    if source_verification not in {"off", "best_effort", "required"}:
        raise SnapshotError("Invalid verification mode")
    from finpanel.filings import _cutoff
    from finpanel.sec.common import normalize_cik

    cutoff = _cutoff(as_of).isoformat()
    cik = normalize_cik(cik)
    parameters = loads(dumps(parameters or {}).encode())
    allowed = {
        "resolve": {"fiscal_year", "period", "start", "end", "revision_policy"},
        "derive_quarter": {"fiscal_year", "quarter", "revision_policy"},
        "verify_fact": {"accession", "taxonomy", "concept", "unit", "start", "end"},
    }[operation]
    if set(parameters) - allowed:
        raise SnapshotError("Unsupported pinned query parameter or external operand")
    if operation != "verify_fact":
        parameters.setdefault("revision_policy", "latest_available")
    else:
        parameters.setdefault("taxonomy", "us-gaap")
        parameters.setdefault("unit", "USD")
    snapshot = store.select(snapshot_id=snapshot_id)
    cache = _PinnedCache(store, snapshot)
    with SECClient(cache=cache, offline=True) as client:
        if operation == "verify_fact":
            observations = [
                o
                for o in parse_companyfacts(client.companyfacts(cik)).records
                if o.accession_number == parameters.get("accession")
                and o.taxonomy == parameters["taxonomy"]
                and o.concept == parameters.get("concept")
                and o.unit == parameters["unit"]
                and str(o.period_start) == str(parameters.get("start"))
                and str(o.period_end) == str(parameters.get("end"))
            ]
            if len(observations) != 1:
                raise SnapshotError("Pinned fact query must identify exactly one observation")
            original = observations[0]
            accessions = {original.accession_number}
        else:
            original = getattr(metrics, operation)(
                cik, metric, as_of=cutoff, client=client, **parameters
            )
            if operation == "resolve":
                original = replace(original, evidence_snapshot_id=snapshot_id)
            else:
                original = replace(
                    original,
                    evidence_snapshot_id=snapshot_id,
                    minuend=replace(original.minuend, evidence_snapshot_id=snapshot_id)
                    if original.minuend
                    else None,
                    subtrahend=replace(original.subtrahend, evidence_snapshot_id=snapshot_id)
                    if original.subtrahend
                    else None,
                )
            operands = (
                (original.minuend, original.subtrahend)
                if operation == "derive_quarter"
                else (original,)
            )
            accessions = {
                c.observation.fact.observation.accession_number
                for r in operands
                if r
                for c in r.considered
            }
        instances = []
        source_limits = []
        if source_verification != "off" or operation == "verify_fact":
            filings = parse_submissions(client.submissions(cik)).records
            for accession in sorted(a for a in accessions if a):
                matched = [f for f in filings if f.accession_number == accession]
                if len(matched) != 1:
                    source_limits.append("filing_not_in_recent_snapshot:" + accession)
                    continue
                try:
                    _, found = xbrl.inspect_filing(matched[0], client=client)
                    instances.extend(found)
                except FinPanelError as exc:
                    # Integrity failures never downgrade into best effort.
                    if isinstance(exc, SnapshotError):
                        raise
                    source_limits.append(accession + ":" + str(exc))
        if operation == "verify_fact":
            result = xbrl.verify_fact(original, instances=tuple(instances), as_of=cutoff)
            result = replace(result, evidence_snapshot_id=snapshot_id)
            state = result.state
            value = result.observation.value if state.startswith("verified") else None
            unit = result.observation.unit if value is not None else None
        else:
            result = original
            if source_verification != "off":
                verify = (
                    xbrl.verify_derivation if operation == "derive_quarter" else xbrl.verify_metric
                )
                result = verify(
                    original, instances=tuple(instances), source_verification=source_verification
                )
            state = getattr(result, "state", getattr(result, "status", None))
            value = result.value
            unit = original.unit
    query = {
        "operation": operation,
        "cik": cik,
        "metric": metric,
        "as_of": cutoff,
        "parameters": parameters,
        "source_verification": source_verification,
    }
    summary = {
        "state": state,
        "value": value,
        "unit": unit,
        "source_policy": "derived_explicit"
        if operation == "derive_quarter"
        else "reported_only"
        if operation == "resolve"
        else "original_fact_verification",
    }
    used = [
        {
            "capture_id": a.capture_id,
            "source_url": a.source_url,
            "sha256": a.sha256,
            "retrieved_at": a.retrieved_at,
        }
        for url, a in sorted(cache.used.items())
    ]
    semantic = {
        "format": RECEIPT_FORMAT,
        "software": software_identity(),
        "contracts": dict(CONTRACTS),
        "snapshot_id": snapshot_id,
        "scope": snapshot.manifest["scope"],
        "snapshot_completeness": snapshot.manifest["completeness"],
        "captured_through": snapshot.manifest["captured_through"],
        "query": query,
        "result": summary,
        "artifacts": used,
        "missing_requests": sorted(cache.missing),
        "source_limitations": sorted(source_limits),
        "provenance": _provenance(
            result.matches
            if operation == "verify_fact"
            else tuple(r.selected for r in (original.minuend, original.subtrahend) if r)
            if operation == "derive_quarter"
            else original.selected
        ),
        "operand_snapshot_ids": [snapshot_id, snapshot_id] if operation == "derive_quarter" else [],
    }
    receipt = Receipt(
        digest(semantic), semantic, timestamp(executed_at or datetime.now(UTC).isoformat())
    )
    return PinnedResult(result, receipt, snapshot_id, tuple(semantic["operand_snapshot_ids"]))


def read_receipt(path: str | Path) -> Receipt:
    try:
        data = loads(Path(path).read_bytes())
        r = Receipt(**data)
        if not isinstance(r.semantic, dict):
            raise SnapshotError("Malformed receipt semantics")
        if r.semantic.get("format") != RECEIPT_FORMAT or digest(r.semantic) != r.receipt_id:
            raise SnapshotError("Receipt integrity or format failure")
        timestamp(r.executed_at)
        return r
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise SnapshotError("Malformed receipt") from exc


def reproduce(receipt: Receipt, *, store: EvidenceStore) -> Replay:
    try:
        if not isinstance(receipt.semantic, dict):
            raise SnapshotError("Malformed receipt semantics")
        if digest(receipt.semantic) != receipt.receipt_id:
            raise SnapshotError("Receipt hash mismatch")
        if receipt.semantic.get("format") != RECEIPT_FORMAT:
            raise SnapshotError("Unsupported receipt version")
        if (
            receipt.semantic["software"] != software_identity()
            or receipt.semantic["contracts"] != CONTRACTS
        ):
            raise SnapshotError("Incompatible software or contract version")
        actual = run(
            store, snapshot_id=receipt.semantic["snapshot_id"], **receipt.semantic["query"]
        )
        equal = actual.reproducibility.receipt_id == receipt.receipt_id
        return Replay(
            equal,
            "exact_replay" if equal else "semantic_receipt_mismatch",
            receipt.receipt_id,
            actual.reproducibility.receipt_id,
        )
    except (FinPanelError, KeyError, TypeError, OSError) as exc:
        return Replay(False, str(exc), receipt.receipt_id)


def export_bundle(
    receipt: Receipt, *, store: EvidenceStore, destination: str | Path, include_raw: bool = False
):
    from finpanel.snapshots.store import _publish

    snapshot = store.select(snapshot_id=receipt.semantic["snapshot_id"])
    if digest(receipt.semantic) != receipt.receipt_id:
        raise SnapshotError("Invalid receipt")
    dest = Path(destination)
    _publish(dest / "receipt.json", dumps(receipt).encode())
    _publish(
        dest / "snapshots" / f"{snapshot.snapshot_id}.json",
        dumps({"snapshot_id": snapshot.snapshot_id, **snapshot.manifest}).encode(),
    )
    if include_raw:
        for metadata in snapshot.manifest["artifacts"]:
            a = store._artifact(metadata)
            _publish(dest / a.locator, store.raw(a).body)
    _publish(
        dest / "bundle.json",
        dumps(
            {
                "kind": "self-contained bundle" if include_raw else "manifest-only bundle",
                "snapshot_id": snapshot.snapshot_id,
                "receipt_id": receipt.receipt_id,
            }
        ).encode(),
    )
