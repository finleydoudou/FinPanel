"""Offline CLI exposes operands and provenance instead of an unexplained scalar."""

from pathlib import Path

import pytest

from finpanel.cli import main
from finpanel.models import RawResponse
from finpanel.serialization import loads


@pytest.fixture
def cache(historical_cache):
    folder = Path(__file__).parent / "fixtures" / "sec"
    meta = loads((folder / "manifest.json").read_bytes())["files"]["aapl_companyfacts.json"]
    historical_cache.put(
        RawResponse(
            meta["source_url"],
            (folder / "aapl_companyfacts.json").read_bytes(),
            meta["retrieved_at"],
        )
    )
    return historical_cache


def args(cache, action, quarter):
    return [
        "metrics",
        action,
        "320193",
        "revenue",
        "--fiscal-year",
        "2024",
        "--quarter",
        quarter,
        "--as-of",
        "2024-11-15T00:00:00Z",
        "--offline",
        "--cache-dir",
        str(cache.root),
        "--limit",
        "0",
    ]


def test_derive_cli_deterministic_and_provenance_complete(cache, capsys, tmp_path):
    command = args(cache, "derive-quarter", "Q4")
    assert main(command) == 0
    first = capsys.readouterr().out
    r = loads(first)
    assert r["source_type"] == "derived" and r["value"] == 94930000000
    assert r["contract"]["derivation_type"] == "annual_residual"
    assert r["minuend"]["value"] == 391035000000 and r["subtrahend"]["value"] == 296105000000
    for label in ("minuend", "subtrahend"):
        assert r[label]["source_type"] == "reported"
        assert r[label]["selected"][0]["observation"]["fact"]["observation"]["provenance"]
    assert main(command) == 0 and capsys.readouterr().out == first
    assert main(command + ["--strict"]) == 1  # Original history-range issue is preserved.
    capsys.readouterr()
    path = tmp_path / "unsupported.json"
    command[3] = "assets"
    assert main(command + ["--output", str(path)]) == 0
    assert loads(path.read_bytes())["status"] == "ineligible"


def test_compare_cli_and_explicit_source_policy(cache, capsys):
    assert main(args(cache, "compare-quarter", "Q3")) == 0
    r = loads(capsys.readouterr().out)
    assert r["state"] == "equal" and r["difference"] == 0
    assert r["reported"]["source_type"] == "reported" and r["derived"]["source_type"] == "derived"
    command = args(cache, "resolve-quarter", "Q4")
    assert main(command) == 0
    assert loads(capsys.readouterr().out)["value"] is None
    assert main(command + ["--source-policy", "reported_then_derived"]) == 0
    assert loads(capsys.readouterr().out)["source_type"] == "derived"


def test_cli_cache_failures_remain_explicit(tmp_path, capsys):
    command = [
        "metrics",
        "derive-quarter",
        "1",
        "revenue",
        "--fiscal-year",
        "2021",
        "--quarter",
        "Q2",
        "--as-of",
        "2024-01-01T00:00:00Z",
        "--offline",
        "--cache-dir",
        str(tmp_path),
    ]
    assert main(command) == 2 and "Offline cache miss" in capsys.readouterr().err
    assert main(command + ["--refresh"]) == 2
