"""Execute the researcher workflow on an explicit small offline snapshot."""

import runpy
import sys
from pathlib import Path

import duckdb
import pytest
from test_panel_engine import pinned
from test_validation_acquisition import manifest

from finpanel.validation import runner


def test_example_exports_queryable_duckdb_with_receipt(tmp_path, monkeypatch):
    store, request = pinned(tmp_path / "evidence")
    original = runner.run

    def small_run(*args, **kwargs):
        return original(
            *args,
            **kwargs,
            manifest=manifest(),
            config=runner.BenchmarkConfig(
                fiscal_years=(2021,),
                periods=("FY", "Q1", "Q2"),
                as_of=("2025-01-01T00:00:00Z",),
                revision_policies=("latest_available",),
            ),
        )

    monkeypatch.setattr(runner, "run", small_run)
    out = tmp_path / "example"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "build_broad_panel.py",
            "--store",
            str(store.root),
            "--snapshot",
            request.snapshot_id,
            "--output",
            str(out),
        ],
    )
    with pytest.raises(SystemExit) as exit_status:
        runpy.run_path(
            str(Path(__file__).parents[1] / "examples/build_broad_panel.py"), run_name="__main__"
        )
    assert exit_status.value.code == 0
    with duckdb.connect(str(out / "research.duckdb"), read_only=True) as db:
        assert db.execute("SELECT count(*) FROM panel_rows").fetchone()[0] == 18
        assert db.execute("SELECT count(*) FROM resolved").fetchone()[0] == 3
        assert db.execute("SELECT count(*) FROM unresolved").fetchone()[0] == 15
        assert db.execute("SELECT count(*) FROM benchmark_receipt").fetchone()[0] == 1
