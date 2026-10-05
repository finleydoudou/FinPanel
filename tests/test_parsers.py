from dataclasses import replace
from datetime import date
from decimal import Decimal
from hashlib import sha256

import pytest

from finpanel.errors import ValidationError
from finpanel.sec import normalize_cik, parse_companyfacts, parse_submissions
from finpanel.serialization import dumps, loads


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (320193, "0000320193"),
        ("0000320193", "0000320193"),
        (" 1 ", "0000000001"),
        (9999999999, "9999999999"),
    ],
)
def test_cik(value, expected):
    assert normalize_cik(value) == expected


@pytest.mark.parametrize(
    "value", [0, -1, True, None, 1.2, "", "AAPL", "CIK320193", "1.0", "12345678901", "１２３"]
)
def test_bad_cik(value):
    with pytest.raises(ValidationError):
        normalize_cik(value)


@pytest.mark.parametrize("ticker", ["aapl", "msft", "wmt", "nvda"])
def test_submissions(raw, ticker):
    source = raw("submissions", ticker)
    result = parse_submissions(source)
    assert not result.issues
    assert len(result.records) == 3
    assert [r.form for r in result.records] == ["10-Q", "10-Q/A", "10-K/A"]
    assert result.records[0].acceptance_datetime.utcoffset().total_seconds() == 0
    assert result.records[2].report_date is None
    assert result.records[0].raw["isXBRL"] == 1
    assert result.records[0].fiscal_year_end == source.json()["fiscalYearEnd"]
    assert result.metadata["scope"] == "recent_only"
    assert len(result.metadata["history_files"]) == 1


@pytest.mark.parametrize("ticker", ["aapl", "msft", "wmt", "nvda"])
def test_companyfacts(raw, ticker):
    result = parse_companyfacts(raw(ticker=ticker))
    assert len(result.records) == 8
    assert not result.issues
    assert {r.unit for r in result.records} == {"USD", "EUR", "shares", "USD/shares"}
    assets = [r for r in result.records if r.concept == "Assets"]
    assert len(assets) == 3
    assert assets[0].raw == assets[1].raw
    assert assets[0].provenance.pointer != assets[1].provenance.pointer
    assert assets[2].form == "10-Q/A"
    assert assets[0].period_start is None
    revenues = [r for r in result.records if r.concept == "Revenues" and r.unit == "USD"]
    assert {r.fiscal_period for r in revenues} == {"Q3"}
    assert {r.period_start for r in revenues} == {date(2023, 10, 1), date(2024, 4, 1)}
    assert all(r.report_date is None for r in result.records)
    assert all(r.label is None for r in revenues)


def test_source_pointer_and_hash(raw):
    source = raw()
    for record in parse_companyfacts(source).records:
        target = source.json()
        for token in record.provenance.pointer.split("/")[1:]:
            token = token.replace("~1", "/").replace("~0", "~")
            target = target[int(token)] if isinstance(target, list) else target[token]
        assert target == record.raw
        assert record.provenance.response_sha256 == sha256(source.body).hexdigest()


@pytest.mark.parametrize("row", [None, [], 5, {"val": "123"}, {"val": True}, {}])
def test_invalid_observation_reported(raw, row):
    data = {"cik": 1, "facts": {"t": {"c": {"units": {"USD": [row, {"val": 3}]}}}}}
    result = parse_companyfacts(raw(data=data))
    assert len(result.records) == 1
    assert len(result.issues) == 1
    assert result.issues[0].raw == row
    assert result.issues[0].code == "invalid_record"


def test_bad_optional_fields(raw):
    data = {
        "cik": 1,
        "facts": {
            "t": {
                "c": {
                    "units": {
                        "USD": [
                            {
                                "val": 3,
                                "filed": "yesterday",
                                "fy": "2024",
                                "fp": 3,
                                "start": "2024-09-01",
                                "end": "2024-01-01",
                            }
                        ]
                    }
                }
            }
        },
    }
    result = parse_companyfacts(raw(data=data))
    assert len(result.records) == 1
    assert len(result.issues) == 4
    assert result.records[0].filing_date is None
    assert result.records[0].raw["fy"] == "2024"


@pytest.mark.parametrize(
    "facts",
    [
        None,
        [],
        {"t": None},
        {"t": {"c": None}},
        {"t": {"c": {"units": []}}},
        {"t": {"c": {"units": {"USD": {}}}}},
    ],
)
def test_bad_containers(raw, facts):
    result = parse_companyfacts(raw(data={"cik": 1, "facts": facts}))
    assert result.issues
    assert not result.records


def test_uneven_columns_not_truncated(raw):
    data = {
        "cik": 1,
        "filings": {
            "recent": {
                "accessionNumber": ["a"],
                "form": ["10-K", "10-K/A"],
                "filingDate": "invalid",
            }
        },
    }
    result = parse_submissions(raw(data=data))
    assert len(result.records) == 1
    assert {i.code for i in result.issues} == {"column_length", "invalid_record", "invalid_field"}
    assert result.issues[-1].raw == {"form": "10-K/A"}


def test_missing_optional_filing_fields(raw):
    result = parse_submissions(
        raw(data={"cik": 1, "filings": {"recent": {"accessionNumber": ["a"]}}})
    )
    assert len(result.records) == 1
    assert not result.issues
    assert result.records[0].form is None


def test_malformed_filing_dates(raw):
    result = parse_submissions(
        raw(
            data={
                "cik": 1,
                "filings": {
                    "recent": {
                        "accessionNumber": ["a"],
                        "filingDate": ["2024-02-30"],
                        "acceptanceDateTime": ["2024-01-01"],
                    }
                },
            }
        )
    )
    assert len(result.issues) == 2
    assert result.issues[0].provenance.pointer == "/filings/recent/filingDate/0"


def test_exact_decimal_and_determinism(raw):
    body = b'{"cik":1,"facts":{"t":{"c":{"units":{"USD":[{"val":0.1234567890123456789012345}]}}}}}'
    source = replace(raw(), body=body)
    result = parse_companyfacts(source)
    assert result.records[0].value == Decimal("0.1234567890123456789012345")
    assert dumps(result) == dumps(parse_companyfacts(source))
    assert "0.1234567890123456789012345" in dumps(result)
    assert dumps({"b": 1, "a": 2}) == dumps({"a": 2, "b": 1})


@pytest.mark.parametrize("body", [b"[]", b"null", b"{", b'{"a":1,"a":2}', b'{"a":NaN}', b"\xff"])
def test_invalid_json(body):
    with pytest.raises(ValidationError):
        loads(body)
