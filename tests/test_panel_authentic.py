"""Intact authentic sources, hand-audited literals, offline exports and exact replay."""

import runpy
from pathlib import Path

import pytest

from finpanel.serialization import loads

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def benchmark(tmp_path_factory):
    runner = runpy.run_path(str(ROOT / "examples/build_research_panel.py"))
    return runner["benchmark"](tmp_path_factory.mktemp("authentic-panel"))


def test_authentic_four_issuer_panel_expected_states(benchmark):
    report, _ = benchmark
    assert report["requested_cells"] == 480
    assert report["unexpected_mismatches"] == 0
    assert all(c["passed"] for c in report["checks"])
    assert len(report["metrics"]) == 6 and len(report["fiscal_years"]) == 2
    assert sum(report["states"].values()) == 480
    assert {
        "resolved_reported",
        "resolved_derived",
        "conflicted",
        "unavailable",
        "ambiguous_period",
    } <= report["states"].keys()
    assert report["authentic_artifacts"] == 25
    assert report == loads((ROOT / "docs/panel-validation.json").read_bytes())


def test_authentic_exports_and_pinned_replay(benchmark):
    report, _ = benchmark
    assert report["export_round_trips"] == {"csv": True, "parquet": True, "duckdb": True}
    assert report["duckdb_counts_match"]
    assert report["successful_replays"] == report["replay_cases"] == 1


def test_authentic_reuse_measurement(benchmark):
    _, performance = benchmark
    assert performance["candidate_builds"] == 48
    assert performance["candidate_reuses"] == 432
    assert performance["rows"] == 480
    assert performance["wall_seconds"] > 0
