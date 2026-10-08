"""Internal, request-scoped reuse for immutable engine inputs during offline validation.

Never shared globally or between issuer batches. Callers must not mutate evidence
while an evaluation scope is open. Public APIs outside this scope behave unchanged.
"""

from collections import Counter
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

_ACTIVE = ContextVar("finpanel_evaluation_reuse", default=None)


@dataclass
class EvaluationReuse:
    enabled: bool = True
    cache: dict = field(default_factory=dict)
    builds: Counter = field(default_factory=Counter)
    hits: Counter = field(default_factory=Counter)

    def statistics(self):
        return {
            "builds": dict(sorted(self.builds.items())),
            "hits": dict(sorted(self.hits.items())),
        }


@contextmanager
def evaluation_reuse(*, enabled=True):
    scope = EvaluationReuse(enabled)
    token = _ACTIVE.set(scope)
    try:
        yield scope
    finally:
        scope.cache.clear()
        _ACTIVE.reset(token)


def memo(kind, key, build):
    scope = _ACTIVE.get()
    if scope is None:
        return build()
    cache_key = (kind, key)
    if scope.enabled and cache_key in scope.cache:
        scope.hits[kind] += 1
        return scope.cache[cache_key]
    scope.builds[kind] += 1
    value = build()
    if scope.enabled:
        scope.cache[cache_key] = value
    return value
