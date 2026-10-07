from datetime import date
from decimal import Decimal

import pytest

from finpanel.errors import ValidationError
from finpanel.panel import PanelRequest, PanelRow, PeriodEnd


def request(**changes):
    return PanelRequest(
        **(
            dict(
                entities=[1],
                metrics=["revenue"],
                fiscal_years=[2024],
                periods=["FY"],
                as_of=["2025-01-01T00:00:00Z"],
            )
            | changes
        )
    )


def test_grid_normalized_deduplicated_and_ordered():
    r = request(
        entities=[2, "0000000001", 1],
        metrics=["revenue", "assets", "revenue"],
        periods=["Q2", "FY", "Q1"],
        as_of=["2025-01-01T00:00:00Z", "2024-01-01T00:00:00Z"],
    )
    assert len(list(r.grid())) == 24
    assert next(r.grid())[0] == "0000000001"
    assert r.periods == ("FY", "Q1", "Q2")
    assert request(as_of=["2025-01-01T01:00:00+01:00"]) == request()


@pytest.mark.parametrize(
    "change",
    [
        dict(metrics=["ebitda"]),
        dict(periods=["TTM"]),
        dict(entities=[]),
        dict(as_of=["2025-01-01"]),
        dict(fiscal_years=[True]),
        dict(source_policy="guess"),
        dict(errors="ignore"),
        dict(snapshot_id="latest"),
        dict(source_verification="trust"),
        dict(entities="AAPL"),
        dict(as_of=[]),
    ],
)
def test_invalid_requests(change):
    with pytest.raises(ValidationError):
        request(**change)


def test_explicit_instant_date_no_invention():
    r = request(period_ends=[dict(cik=1, fiscal_year=2024, period="FY", end="2024-12-31")])
    assert r.instant_end("0000000001", 2024, "FY") == date(2024, 12, 31)
    assert request().instant_end("0000000001", 2024, "FY") is None
    with pytest.raises(ValidationError):
        request(
            period_ends=[
                PeriodEnd(1, 2024, "FY", date(2024, 1, 1)),
                PeriodEnd(1, 2024, "FY", date(2024, 12, 31)),
            ]
        )


def test_row_exact_contract():
    from dataclasses import replace

    row = PanelRow(
        "id",
        "0000000001",
        None,
        None,
        "revenue",
        2024,
        "FY",
        None,
        None,
        request().as_of[0],
        "latest_available",
        "reported_only",
        "unavailable",
        None,
        None,
        None,
        (),
        (),
        (),
        (),
        "off",
        None,
        "unsnapshotted",
        "receipt",
        ("no_eligible_filing",),
        (),
    )
    assert row.value is None
    exact = Decimal("123456789012345678901234567890.123456789")
    assert replace(row, state="resolved_reported", value=exact).value == exact
    with pytest.raises(ValidationError):
        replace(row, state="resolved_reported", value=1.5)
