"""Original instance evidence, deliberately separate from inferred fiscal periods."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from finpanel.models import Provenance
from finpanel.xbrl.discovery import SourceDocument


@dataclass(frozen=True)
class Dimension:
    axis: str
    kind: str
    member: str | None
    typed_xml: str | None
    location: str


@dataclass(frozen=True)
class OriginalContext:
    context_id: str
    entity_identifier: str | None
    identifier_scheme: str | None
    period_type: str
    start: date | None
    end: date | None
    dimensions: tuple[Dimension, ...]
    dimension_state: str
    segment_xml: str | None
    scenario_xml: str | None
    other_scope: tuple[str, ...]
    fingerprint: str
    scope_fingerprint: str
    provenance: Provenance
    raw_xml: str
    diagnostics: tuple[str, ...]


@dataclass(frozen=True)
class OriginalUnit:
    unit_id: str
    numerator: tuple[str, ...]
    denominator: tuple[str, ...]
    fingerprint: str
    raw_xml: str
    provenance: Provenance
    diagnostics: tuple[str, ...]


@dataclass(frozen=True)
class NumericMetadata:
    decimals: str | None
    precision: str | None
    state: str
    rounding_quantum: Decimal | None
    # An uncertainty magnitude diagnostic only; never a replacement equality rule.
    half_quantum: Decimal | None


@dataclass(frozen=True)
class OriginalFact:
    namespace: str
    concept: str
    context_ref: str | None
    unit_ref: str | None
    lexical_value: str
    value: Decimal | str | None
    nil: bool
    numeric: NumericMetadata
    attributes: tuple[tuple[str, str], ...]
    provenance: Provenance
    diagnostics: tuple[str, ...]


@dataclass(frozen=True)
class InstanceEvidence:
    document: SourceDocument
    contexts: tuple[OriginalContext, ...]
    units: tuple[OriginalUnit, ...]
    facts: tuple[OriginalFact, ...]
    diagnostics: tuple[str, ...]
