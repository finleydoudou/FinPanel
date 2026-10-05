"""Stable JSON with exact decimal numbers and no NaN/Infinity coercion."""

from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from typing import Any

import simplejson as json

from finpanel.errors import ValidationError


def _default(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def dumps(value: Any) -> str:
    return (
        json.dumps(
            value,
            default=_default,
            use_decimal=True,
            allow_nan=False,
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
        )
        + "\n"
    )


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValidationError(f"Duplicate JSON key: {key!r}")
        result[key] = value
    return result


def loads(raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(raw, use_decimal=True, allow_nan=False, object_pairs_hook=_unique)
    except (ValueError, UnicodeError) as exc:
        raise ValidationError(f"Invalid SEC JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValidationError("SEC response must be a JSON object")
    return value
