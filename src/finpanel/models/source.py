"""Byte-level source identity and explicit parser diagnostics."""

from dataclasses import dataclass, field
from functools import cached_property
from hashlib import sha256
from typing import Any, Literal

from finpanel.errors import ValidationError
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
    raw_format: Literal["json", "text"] = "json"

    @cached_property
    def sha256(self) -> str:
        return sha256(self.body).hexdigest()

    def json(self) -> dict[str, Any]:
        if self.raw_format != "json":
            raise ValidationError("Response is text, not JSON")
        return loads(self.body)

    def text(self) -> str:
        try:
            return self.body.decode("utf-8-sig")
        except UnicodeError as exc:
            raise ValidationError("SEC text response is not valid UTF-8") from exc

    def validate(self) -> None:
        if self.raw_format == "json":
            self.json()
        elif self.raw_format == "text":
            self.text()
        else:
            raise ValidationError("Unsupported raw response format")

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
