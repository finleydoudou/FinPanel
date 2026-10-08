"""Explicit offline validation tools; coverage is never an accuracy estimate."""

from finpanel.validation.acquisition import acquire
from finpanel.validation.universe import selection, universe

__all__ = ["acquire", "selection", "universe"]
