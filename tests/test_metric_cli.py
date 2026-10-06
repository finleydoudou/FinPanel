"""Public offline CLI, complete exports and honest failures."""

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


def test_resolve_offline_cli(cache, capsys):
    args = [
        "metrics",
        "resolve",
        "320193",
        "revenue",
        "--as-of",
        "2024-11-15T00:00:00Z",
        "--fiscal-year",
        "2024",
        "--period",
        "FY",
        "--offline",
        "--cache-dir",
        str(cache.root),
    ]
    assert main(args) == 0
    first = capsys.readouterr().out
    r = loads(first)
    assert r["state"] == "resolved" and r["value"] == 391035000000 and r["unit"] == "USD"
    assert r["sources"][0]["concept"] == "RevenueFromContractWithCustomerExcludingAssessedTax"
    assert r["sources"][0]["accession"] == "0000320193-24-000123"
    assert r["sources"][0]["availability"] and r["sources"][0]["provenance"]
    assert main(args) == 0 and capsys.readouterr().out == first
    assert main(args + ["--strict"]) == 1  # Preserved authentic history range issue.
    assert "history_range_mismatch" in capsys.readouterr().out


def test_candidates_offline_export_and_explicit_inspection(cache, capsys, tmp_path):
    output = tmp_path / "candidates.json"
    args = [
        "metrics",
        "candidates",
        "320193",
        "assets",
        "--as-of",
        "2024-11-15T00:00:00Z",
        "--offline",
        "--cache-dir",
        str(cache.root),
        "--limit",
        "1",
        "--output",
        str(output),
        "--inspect-concept",
        "AssetsCurrent",
    ]
    assert main(args) == 0
    result = loads(capsys.readouterr().out)
    assert len(result["records"]) == 1 and result["candidate_count"] > 1
    full = loads(output.read_bytes())
    assert len(full["records"]) == result["candidate_count"]
    assert any(
        "unsupported_concept" in r["reasons"]
        and r["fact"]["observation"]["concept"] == "AssetsCurrent"
        for r in full["rejected"]
    )
    assert full["evidence"] and full["revision_groups"]


def test_cache_miss_refresh_and_unknown_metric(tmp_path, capsys):
    args = [
        "metrics",
        "candidates",
        "320193",
        "revenue",
        "--as-of",
        "2024-01-01T00:00:00Z",
        "--offline",
        "--cache-dir",
        str(tmp_path),
    ]
    assert main(args) == 2 and "Offline cache miss" in capsys.readouterr().err
    assert main(args + ["--refresh"]) == 2
    capsys.readouterr()
    args[3] = "made_up"
    assert main(args) == 0 and loads(capsys.readouterr().out)["state"] == "unsupported"
    assert main(args + ["--strict"]) == 1
