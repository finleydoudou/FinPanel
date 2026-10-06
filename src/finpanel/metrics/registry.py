"""Explicit reported-metric contracts. Labels never participate in matching."""

from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal


@dataclass(frozen=True)
class ConceptMapping:
    taxonomy: str
    concept: str
    metric: str
    priority: int
    context: Literal["instant", "duration"]
    rationale: str
    support_notes: str


@dataclass(frozen=True)
class MetricDefinition:
    identifier: str
    name: str
    context: Literal["instant", "duration"]
    period_kinds: tuple[str, ...]
    unit_family: str
    allowed_taxonomies: tuple[str, ...]
    mappings: tuple[ConceptMapping, ...]
    exclusions: tuple[str, ...]
    status: Literal["supported", "experimental", "unsupported"] = "supported"


def _metric(identifier, name, context, concepts, exclusions):
    return MetricDefinition(
        identifier,
        name,
        context,
        ("instant",) if context == "instant" else ("annual", "single_quarter", "year_to_date"),
        "currency",
        ("us-gaap",),
        tuple(
            ConceptMapping(
                "us-gaap",
                concept,
                identifier,
                100,
                context,
                rationale,
                "Observed in frozen SEC Company Facts; no inference of equivalent scope. "
                "Equal priority: coexisting concepts require an explicit conflict.",
            )
            for concept, rationale in concepts
        ),
        exclusions,
    )


REGISTRY = MappingProxyType(
    {
        m.identifier: m
        for m in (
            _metric(
                "revenue",
                "Reported revenue (source scope retained)",
                "duration",
                (
                    (
                        "Revenues",
                        "Aggregate revenue from earning activities; broader than ASC 606.",
                    ),
                    (
                        "RevenueFromContractWithCustomerExcludingAssessedTax",
                        "ASC 606 customer-contract revenue excluding assessed taxes; "
                        "may exclude other revenue.",
                    ),
                    (
                        "SalesRevenueNet",
                        "Reported net sales of goods and services, after returns and discounts.",
                    ),
                ),
                (
                    "Tax-inclusive revenue",
                    "Product/service components",
                    "Interest-only revenue",
                    "No assertion that different revenue scopes are interchangeable",
                ),
            ),
            _metric(
                "net_income",
                "Net income attributable to parent",
                "duration",
                (("NetIncomeLoss", "After-tax profit or loss attributable to the parent."),),
                (
                    "ProfitLoss including noncontrolling interests",
                    "Common-shareholder adjustments",
                    "EPS",
                ),
            ),
            _metric(
                "assets",
                "Total recognized assets",
                "instant",
                (("Assets", "Reported total carrying amount of recognized assets."),),
                ("Current assets alone", "Calculated totals"),
            ),
            _metric(
                "liabilities",
                "Total recognized liabilities",
                "instant",
                (("Liabilities", "Reported total carrying amount of recognized liabilities."),),
                ("Liabilities and equity", "Current liabilities alone", "Assets minus equity"),
            ),
            _metric(
                "cash_and_cash_equivalents",
                "Cash and cash equivalents at carrying value",
                "instant",
                (
                    (
                        "CashAndCashEquivalentsAtCarryingValue",
                        "Reported cash and near-maturity liquid equivalents; "
                        "excludes disposal groups.",
                    ),
                ),
                ("Restricted cash aggregates", "Short-term investments aggregates"),
            ),
            _metric(
                "operating_cash_flow",
                "Net cash from operating activities",
                "duration",
                (
                    (
                        "NetCashProvidedByUsedInOperatingActivities",
                        "Net operating cash inflow/outflow including discontinued operations.",
                    ),
                ),
                ("Continuing operations only", "Quarter subtraction", "Sign inversion"),
            ),
        )
    }
)


def mapping_for(metric: str, taxonomy: str, concept: str) -> ConceptMapping | None:
    definition = REGISTRY.get(metric)
    return (
        next(
            (m for m in definition.mappings if (m.taxonomy, m.concept) == (taxonomy, concept)), None
        )
        if definition
        else None
    )


def unit_status(unit: str) -> str:
    """USD-only scalar support. Other tokens are preserved, never inferred as ISO currencies."""
    return "supported_usd" if unit == "USD" else "unsupported_unit_no_conversion"
