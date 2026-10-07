"""Exact arithmetic and explicitly different source representations."""

from decimal import Decimal, localcontext

import pytest
from test_metric_candidates import report, revenue

from finpanel.errors import ValidationError
from finpanel.metrics.derivation_models import DERIVABLE_METRICS, FORMULAS, exact_subtract
from finpanel.metrics.resolver import resolve_candidates
from finpanel.serialization import dumps, loads


def test_only_explicit_duration_formulas():
    assert DERIVABLE_METRICS == {"revenue", "net_income", "operating_cash_flow"}
    assert set(FORMULAS) == {"Q2", "Q3", "Q4"}
    assert FORMULAS["Q4"].derivation_type == "annual_residual"
    assert FORMULAS["Q2"].subtrahend_period == "Q1"
    with pytest.raises(TypeError):
        FORMULAS["Q1"] = FORMULAS["Q2"]


@pytest.mark.parametrize(
    "a,b,expected",
    [
        (100, 30, 70),
        (30, 100, -70),
        (-30, -100, 70),
        (0, 0, 0),
        (10**80, 1, 10**80 - 1),
        (Decimal("0.30"), Decimal("0.10"), Decimal("0.20")),
        (Decimal("1E+40"), Decimal("0.01"), Decimal("9999999999999999999999999999999999999999.99")),
        (Decimal("0.000000001"), Decimal("0.000000002"), Decimal("-0.000000001")),
    ],
)
def test_exact_subtraction_independent_of_decimal_context(a, b, expected):
    with localcontext() as ctx:
        ctx.prec = 2
        result = exact_subtract(a, b)
    assert result == expected
    if isinstance(a, Decimal):
        assert isinstance(result, Decimal)
    assert loads(dumps({"value": result}))["value"] == expected


@pytest.mark.parametrize("value", [1.2, True, "100", Decimal("NaN"), Decimal("Infinity")])
def test_unsafe_numbers_rejected(value):
    with pytest.raises(ValidationError):
        exact_subtract(value, 0)


def test_reported_resolution_remains_reported():
    result = resolve_candidates(report(revenue()), fiscal_year=2021, period="FY")
    assert result.value == 100 and result.source_type == "reported"
    assert loads(dumps(result))["source_type"] == "reported"
