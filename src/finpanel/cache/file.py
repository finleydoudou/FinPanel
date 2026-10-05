"""Content-addressed raw bytes, immutable version metadata, atomic latest pointers."""

import os
import re
import tempfile
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

from finpanel.errors import CacheError, ValidationError
from finpanel.models import RawResponse
from finpanel.serialization import dumps, loads


def atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
            name = handle.name
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        if name is not None and os.path.exists(name):
            os.unlink(name)


class FileCache:
    def __init__(self, root: str | Path):
        self.root = Path(root)

    def _index(self, url: str) -> Path:
        return self.root / "raw" / "requests" / sha256(url.encode()).hexdigest()

    def get(self, url: str) -> RawResponse | None:
        index = self._index(url) / "latest.json"
        try:
            try:
                metadata_raw = index.read_bytes()
            except FileNotFoundError:
                return None
            meta = loads(metadata_raw)
            digest = meta["sha256"]
            if not isinstance(digest, str) or not re.fullmatch("[a-f0-9]{64}", digest):
                raise ValueError("invalid content hash")
            if meta["url"] != url:
                raise ValueError("cached URL mismatch")
            if not isinstance(meta["retrieved_at"], str) or not isinstance(meta["headers"], dict):
                raise ValueError("invalid cached response metadata")
            body = (self.root / "raw" / "objects" / f"{digest}.json").read_bytes()
            if sha256(body).hexdigest() != digest:
                raise ValueError("raw content hash mismatch")
            response = RawResponse(url, body, meta["retrieved_at"], meta["headers"], True)
            response.json()
            return response
        except (OSError, KeyError, TypeError, ValueError, ValidationError) as exc:
            raise CacheError(f"Cannot read cache entry {index}: {exc}") from exc

    def put(self, response: RawResponse) -> RawResponse:
        response.json()
        meta = {
            "url": response.url,
            "sha256": response.sha256,
            "retrieved_at": response.retrieved_at,
            "headers": response.headers,
        }
        try:
            atomic_write(self.root / "raw" / "objects" / f"{response.sha256}.json", response.body)
            encoded = dumps(meta).encode()
            # Version metadata is itself content-addressed; refresh retains previous retrievals.
            version = sha256(encoded).hexdigest()
            atomic_write(self._index(response.url) / "versions" / f"{version}.json", encoded)
            atomic_write(self._index(response.url) / "latest.json", encoded)
        except OSError as exc:
            raise CacheError(f"Cannot write raw cache: {exc}") from exc
        return replace(response, from_cache=False)
