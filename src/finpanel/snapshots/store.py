"""Immutable byte objects and deterministic version manifests, separate from FileCache."""

import os
import re
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Literal

from finpanel.errors import FinPanelError
from finpanel.models import RawResponse
from finpanel.serialization import dumps, loads

FORMAT = "finpanel-snapshot-v1"
FAMILIES = frozenset(
    {
        "submissions",
        "historical_submissions",
        "companyfacts",
        "companyconcept",
        "filing_directory",
        "filing_header",
        "filing_text",
        "xbrl_instance",
        "bulk_archive",
        "other_sec",
    }
)


class SnapshotError(FinPanelError):
    """Unavailable or invalid immutable evidence; never repaired automatically."""


def digest(value):
    return sha256(dumps(value).encode()).hexdigest()


def timestamp(value):
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            raise ValueError("timezone required")
        return dt.astimezone(UTC).isoformat()
    except (ValueError, TypeError, AttributeError) as exc:
        raise SnapshotError("Invalid evidence timestamp") from exc


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch("[a-f0-9]{64}", value):
        raise SnapshotError("Invalid content identifier")
    return value


@dataclass(frozen=True)
class Artifact:
    capture_id: str
    source_url: str
    source_family: str
    retrieved_at: str
    sha256: str
    size: int
    http_metadata: tuple[tuple[str, str], ...]
    cik: str | None
    accession: str | None
    locator: str
    raw_format: str
    authenticity: Literal["authentic", "synthetic", "unspecified"]
    raw_unmodified: bool
    parser_schema: str = "raw-bytes-v1"


@dataclass(frozen=True)
class Snapshot:
    snapshot_id: str
    manifest: dict


@dataclass(frozen=True)
class Integrity:
    snapshot_id: str
    valid: bool
    completeness: str
    errors: tuple[str, ...]


def _publish(path: Path, data: bytes):
    """Publish an fsynced temporary inode without ever replacing an existing object."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
            temp = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if temp.read_bytes() != data:
            raise SnapshotError("Temporary write verification failed")
        try:
            os.link(temp, path)
        except FileExistsError:
            if path.read_bytes() != data:
                raise SnapshotError("Immutable object collision or corruption") from None
        if path.read_bytes() != data:
            raise SnapshotError("Published object verification failed")
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


class EvidenceStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)

    def capture(
        self,
        raw: RawResponse,
        *,
        source_family: str,
        cik: str | None = None,
        accession: str | None = None,
        authenticity: str = "unspecified",
    ) -> Artifact:
        if source_family not in FAMILIES:
            raise SnapshotError("Unsupported source family")
        if authenticity not in {"authentic", "synthetic", "unspecified"}:
            raise SnapshotError("Invalid authenticity label")
        # Arbitrary binary bulk bytes are stored without attempting JSON/text parsing.
        headers = tuple(
            sorted(
                (k.lower(), v)
                for k, v in raw.headers.items()
                if k.lower() in {"etag", "last-modified", "content-type"}
            )
        )
        if len({k for k, v in headers}) != len(headers):
            raise SnapshotError("Duplicate HTTP metadata")
        metadata = dict(
            source_url=raw.url,
            source_family=source_family,
            retrieved_at=timestamp(raw.retrieved_at),
            sha256=raw.sha256,
            size=len(raw.body),
            http_metadata=headers,
            cik=cik,
            accession=accession,
            locator="objects/" + raw.sha256,
            raw_format=raw.raw_format,
            authenticity=authenticity,
            raw_unmodified=True,
            parser_schema="raw-bytes-v1",
        )
        artifact = Artifact(digest(metadata), **metadata)
        self._artifact(asdict(artifact))
        _publish(self.root / artifact.locator, raw.body)
        _publish(self.root / "captures" / f"{artifact.capture_id}.json", dumps(artifact).encode())
        return artifact

    def _artifact(self, data: dict) -> Artifact:
        try:
            copy = dict(data)
            copy["http_metadata"] = tuple(tuple(p) for p in copy["http_metadata"])
            a = Artifact(**copy)
            semantic = asdict(a)
            semantic.pop("capture_id")
            if digest(semantic) != identifier(a.capture_id):
                raise SnapshotError("Capture metadata hash mismatch")
            identifier(a.sha256)
            if a.locator != "objects/" + a.sha256:
                raise SnapshotError("Unsafe content locator")
            if a.source_family not in FAMILIES or a.raw_format not in {"json", "text", "binary"}:
                raise SnapshotError("Unsupported artifact type")
            if a.parser_schema != "raw-bytes-v1":
                raise SnapshotError("Unsupported artifact schema")
            if not isinstance(a.source_url, str) or not a.source_url:
                raise SnapshotError("Missing source URL")
            if any(
                len(pair) != 2 or any(not isinstance(v, str) for v in pair)
                for pair in a.http_metadata
            ):
                raise SnapshotError("Malformed HTTP metadata")
            if len({p[0] for p in a.http_metadata}) != len(a.http_metadata):
                raise SnapshotError("Duplicate HTTP metadata")
            if (
                a.authenticity not in {"authentic", "synthetic", "unspecified"}
                or a.raw_unmodified is not True
            ):
                raise SnapshotError("Invalid raw evidence status")
            if type(a.size) is not int or a.size < 0 or timestamp(a.retrieved_at) != a.retrieved_at:
                raise SnapshotError("Invalid artifact metadata")
            return a
        except (TypeError, KeyError, ValueError) as exc:
            raise SnapshotError("Malformed artifact metadata") from exc

    def raw(self, artifact: Artifact) -> RawResponse:
        a = self._artifact(asdict(artifact))
        try:
            body = (self.root / a.locator).read_bytes()
        except OSError as exc:
            raise SnapshotError("Missing artifact: " + a.sha256) from exc
        if len(body) != a.size or sha256(body).hexdigest() != a.sha256:
            raise SnapshotError("Corrupted artifact: " + a.sha256)
        return RawResponse(
            a.source_url, body, a.retrieved_at, dict(a.http_metadata), True, a.raw_format
        )

    def create(
        self,
        artifacts,
        *,
        scope: str,
        required_urls=None,
        relationships=(),
        incompleteness=(),
        notes=(),
    ) -> Snapshot:
        artifacts = tuple(sorted(artifacts, key=lambda a: (a.source_url, a.capture_id)))
        if not artifacts or not isinstance(scope, str) or not scope.strip():
            raise SnapshotError("Nonempty artifacts and declared scope required")
        if len({a.source_url for a in artifacts}) != len(artifacts):
            raise SnapshotError("Snapshot contains competing versions of one URL")
        for a in artifacts:
            self.raw(a)
        required = sorted(
            set(required_urls if required_urls is not None else [a.source_url for a in artifacts])
        )
        missing = sorted(set(required) - {a.source_url for a in artifacts})
        ids = {a.capture_id for a in artifacts}
        relations = sorted([dict(r) for r in relationships], key=dumps)
        for r in relations:
            if (
                set(r) != {"from", "to", "relation"}
                or r["from"] not in ids
                or r["to"] not in ids
                or not r["relation"]
            ):
                raise SnapshotError("Inconsistent artifact relationship")
        manifest = {
            "format": FORMAT,
            "scope": scope,
            "required_urls": required,
            "artifacts": [asdict(a) for a in artifacts],
            "relationships": relations,
            "captured_through": max(a.retrieved_at for a in artifacts),
            "creation_policy": "canonical-set; captured_through=max artifact retrieval",
            "incompleteness": sorted(set(incompleteness)),
            "missing_urls": missing,
            "completeness": "partial"
            if missing or incompleteness
            else "complete_for_declared_scope",
            "notes": sorted(set(notes)),
            "software": "finpanel-0.1.0",
            "artifact_schema": "raw-bytes-v1",
        }
        sid = digest(manifest)
        _publish(
            self.root / "snapshots" / f"{sid}.json",
            dumps({"snapshot_id": sid, **manifest}).encode(),
        )
        return Snapshot(sid, manifest)

    def load(self, snapshot_id: str) -> Snapshot:
        identifier(snapshot_id)
        try:
            data = loads((self.root / "snapshots" / f"{snapshot_id}.json").read_bytes())
        except (OSError, ValueError) as exc:
            raise SnapshotError("Missing or malformed snapshot") from exc
        if data.pop("snapshot_id", None) != snapshot_id:
            raise SnapshotError("Snapshot ID mismatch")
        if data.get("format") != FORMAT:
            raise SnapshotError("Unsupported manifest version")
        if digest(data) != snapshot_id:
            raise SnapshotError("Manifest hash mismatch")
        required = {
            "format",
            "scope",
            "required_urls",
            "artifacts",
            "relationships",
            "captured_through",
            "creation_policy",
            "incompleteness",
            "missing_urls",
            "completeness",
            "notes",
            "software",
            "artifact_schema",
        }
        if set(data) != required:
            raise SnapshotError("Malformed manifest fields")
        try:
            if not isinstance(data["scope"], str) or not data["scope"].strip():
                raise SnapshotError("Malformed declared scope")
            for key in ("required_urls", "incompleteness", "missing_urls", "notes"):
                if not isinstance(data[key], list) or any(
                    not isinstance(v, str) for v in data[key]
                ):
                    raise SnapshotError("Malformed manifest list: " + key)
            if data["artifact_schema"] != "raw-bytes-v1":
                raise SnapshotError("Unsupported artifact schema")
            artifacts = tuple(self._artifact(a) for a in data["artifacts"])
            if not artifacts or len({a.source_url for a in artifacts}) != len(artifacts):
                raise SnapshotError("Inconsistent artifact references")
            ids = {a.capture_id for a in artifacts}
            for r in data["relationships"]:
                if (
                    set(r) != {"from", "to", "relation"}
                    or r["from"] not in ids
                    or r["to"] not in ids
                ):
                    raise SnapshotError("Inconsistent relationship references")
            missing = sorted(set(data["required_urls"]) - {a.source_url for a in artifacts})
            expected = (
                "partial" if missing or data["incompleteness"] else "complete_for_declared_scope"
            )
            if (
                data["missing_urls"] != missing
                or data["completeness"] != expected
                or data["captured_through"] != max(a.retrieved_at for a in artifacts)
            ):
                raise SnapshotError("Inconsistent manifest completeness or capture time")
        except (TypeError, KeyError) as exc:
            raise SnapshotError("Malformed manifest") from exc
        return Snapshot(snapshot_id, data)

    def verify(self, snapshot_id: str) -> Integrity:
        try:
            snapshot = self.load(snapshot_id)
            for a in snapshot.manifest["artifacts"]:
                self.raw(self._artifact(a))
            return Integrity(snapshot_id, True, snapshot.manifest["completeness"], ())
        except (SnapshotError, OSError) as exc:
            return Integrity(snapshot_id, False, "unverifiable", (str(exc),))

    def list(self) -> tuple[Snapshot, ...]:
        # Invalid manifests are errors, never silently skipped to select a newer one.
        return tuple(self.load(p.stem) for p in sorted((self.root / "snapshots").glob("*.json")))

    def select(
        self, *, policy="exact", snapshot_id=None, scope=None, evidence_as_of=None
    ) -> Snapshot:
        if policy == "exact":
            if snapshot_id is None or evidence_as_of is not None:
                raise SnapshotError("Exact selection requires only snapshot_id")
            result = self.load(snapshot_id)
            if scope is not None and result.manifest["scope"] != scope:
                raise SnapshotError("Snapshot scope mismatch")
        else:
            if (
                policy not in {"latest_captured", "latest_captured_no_later_than"}
                or not scope
                or snapshot_id
            ):
                raise SnapshotError("Selection requires explicit policy and scope")
            if (policy == "latest_captured_no_later_than") != (evidence_as_of is not None):
                raise SnapshotError("Evidence capture cutoff required only for bounded selection")
            cutoff = timestamp(evidence_as_of) if evidence_as_of is not None else None
            options = [
                s
                for s in self.list()
                if s.manifest["scope"] == scope
                and (cutoff is None or s.manifest["captured_through"] <= cutoff)
            ]
            if not options:
                raise SnapshotError(
                    "No captured snapshot available; historical source state cannot be fabricated"
                )
            latest = max(s.manifest["captured_through"] for s in options)
            finalists = [s for s in options if s.manifest["captured_through"] == latest]
            if len(finalists) != 1:
                raise SnapshotError("Conflicting snapshots at the same capture time")
            result = finalists[0]
        integrity = self.verify(result.snapshot_id)
        if not integrity.valid:
            raise SnapshotError("; ".join(integrity.errors))
        return result
