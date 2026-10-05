"""Byte-level source identity and explicit parser diagnostics."""

from dataclasses import dataclass, field
from functools import cached_property
from hashlib import sha256
from typing import Any

from finpanel.serialization import loads


@dataclass(frozen=True)
class Provenance:
    source_url: str
    response_sha256: str
    pointer: str


@dataclass(frozen=True)
class RawResponse:
    url: str
    body: bytes
    retrieved_at: str
    headers: dict[str, str] = field(default_factory=dict)
    from_cache: bool = False

    @cached_property
    def sha256(self) -> str:
        return sha256(self.body).hexdigest()

    def json(self) -> dict[str, Any]:
        return loads(self.body)

    def provenance(self, pointer: str) -> Provenance:
        return Provenance(self.url, self.sha256, pointer)


@dataclass(frozen=True)
class ParseIssue:
    code: str
    message: str
    provenance: Provenance
    raw: Any


@dataclass(frozen=True)
class ParseResult[T]:
    records: tuple[T, ...]
    issues: tuple[ParseIssue, ...]
    source: Provenance
    metadata: dict[str, Any] = field(default_factory=dict)
