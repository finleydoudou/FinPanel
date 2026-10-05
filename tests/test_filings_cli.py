import subprocess
import sys

import pytest

from finpanel.cli import main
from finpanel.serialization import loads


@pytest.mark.parametrize("action", ["timeline", "coverage", "available-as-of"])
def test_offline_cli_authentic(historical_cache, tmp_path, action):
    output = tmp_path / "timeline.json"
    args = [sys.executable, "-m", "finpanel.cli", "filings", action, "320193"]
    if action == "available-as-of":
        args.append("2020-06-30T15:00:00Z")
    args.extend(
        [
            "--offline",
            "--cache-dir",
            str(historical_cache.root),
            "--output",
            str(output),
            "--limit",
            "2",
        ]
    )
    first = subprocess.run(args, capture_output=True, check=False)
    second = subprocess.run(args, capture_output=True, check=False)
    assert first.returncode == second.returncode == 0, first.stderr.decode()
    assert first.stdout == second.stdout
    summary = loads(first.stdout)
    full = loads(output.read_bytes())
    assert full["cik"] == "0000320193"
    assert len(full["sources"]) == 2
    assert "history_range_mismatch" in {i["code"] for i in full["issues"]}
    if action == "coverage":
        assert summary["total_filings"] == 2260
        assert summary["historical_files_loaded"] == 1
    else:
        assert len(summary["records"]) == 2
        assert summary["total_filings"] == len(full["records"])
        assert summary["issues"] == 1


def test_cli_strict_coverage_issue(historical_cache, capsys):
    assert (
        main(
            [
                "filings",
                "coverage",
                "320193",
                "--offline",
                "--cache-dir",
                str(historical_cache.root),
                "--strict",
            ]
        )
        == 1
    )
    assert "history_range_mismatch" in capsys.readouterr().out


def test_cli_offline_missing(tmp_path, capsys):
    assert main(["filings", "timeline", "1", "--offline", "--cache-dir", str(tmp_path)]) == 2
    assert "Offline cache miss" in capsys.readouterr().err


def test_cli_negative_limit():
    with pytest.raises(SystemExit) as exc:
        main(["filings", "timeline", "1", "--limit", "-1"])
    assert exc.value.code == 2
