"""Observed period shape, not an instance contextRef or fiscal-period interpretation."""

from dataclasses import dataclass
from datetime import date
from typing import Literal


@dataclass(frozen=True)
class FactContext:
    kind: Literal["instant", "duration", "unknown"]
    start: date | None
    end: date | None
    duration_days: int | None
    basis: str
    instance_context_id: str | None = None
