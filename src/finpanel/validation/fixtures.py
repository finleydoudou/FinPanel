"""Lossless compressed Tier A transport; decompressed bytes retain original SEC hashes."""

import gzip
from hashlib import sha256
from pathlib import Path

from finpanel.models import RawResponse
from finpanel.serialization import loads
from finpanel.snapshots import SnapshotError


def import_fixtures(folder, store):
    folder = Path(folder)
    manifest = loads((folder / "manifest.json").read_bytes())
    artifacts = []
    for item in manifest["artifacts"]:
        path = folder / item["filename"]
        if path.parent.resolve() != folder.resolve():
            raise SnapshotError("Unsafe fixture filename")
        compressed = path.read_bytes()
        if sha256(compressed).hexdigest() != item["compressed_sha256"]:
            raise SnapshotError("Compressed fixture hash mismatch")
        body = gzip.decompress(compressed)
        a = item["artifact"]
        if sha256(body).hexdigest() != a["sha256"]:
            raise SnapshotError("Original SEC byte hash mismatch")
        raw = RawResponse(
            a["source_url"],
            body,
            a["retrieved_at"],
            headers=dict(a["http_metadata"]),
            raw_format=a["raw_format"],
        )
        captured = store.capture(
            raw,
            source_family=a["source_family"],
            cik=a["cik"],
            accession=a["accession"],
            authenticity="authentic",
        )
        if captured.capture_id != a["capture_id"]:
            raise SnapshotError("Capture identity differs")
        artifacts.append(captured)
    return store.create(
        artifacts, scope=manifest["scope"], incompleteness=tuple(manifest["incompleteness"])
    )
