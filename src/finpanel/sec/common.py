"""Shared validation; optional malformed values produce issues, never guesses."""

import re
from datetime import date, datetime
from typing import Any

from finpanel.errors import ValidationError
from finpanel.models.source import ParseIssue, RawResponse


def normalize_cik(cik: str | int) -> str:
    if isinstance(cik, bool) or not isinstance(cik, (str, int)):
        raise ValidationError("CIK must be an integer or an ASCII digit string")
    value = str(cik).strip()
    if not re.fullmatch(r"[0-9]{1,10}", value) or int(value) == 0:
        raise ValidationError("CIK must contain 1–10 digits and be positive")
    return value.zfill(10)


def pointer(*parts: str | int) -> str:
    return "/" + "/".join(str(p).replace("~", "~0").replace("/", "~1") for p in parts)


class Reader:
    def __init__(self, response: RawResponse):
        self.response = response
        self.issues: list[ParseIssue] = []

    def issue(self, path: str, raw: Any, message: str, code: str = "invalid_field") -> None:
        self.issues.append(ParseIssue(code, message, self.response.provenance(path), raw))

    def optional(self, row: dict, key: str, kind: type, path: str) -> Any:
        value = row.get(key)
        if value is None or value == "":
            return None
        try:
            if kind is date:
                if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                    raise ValueError("expected ISO date")
                return date.fromisoformat(value)
            if kind is datetime:
                if not isinstance(value, str) or "T" not in value:
                    raise ValueError("expected ISO datetime")
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            if type(value) is not kind:
                raise ValueError(f"expected {kind.__name__}")
            return value
        except ValueError as exc:
            self.issue(path + pointer(key), value, f"{key}: {exc}")
            return None
