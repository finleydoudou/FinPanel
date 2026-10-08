"""Packaged authentic onboarding example: offline export and exact replay."""

from pathlib import Path

import pytest

from finpanel import __version__, panel
from finpanel.errors import ValidationError
from finpanel.example import build_example
from finpanel.serialization import loads


def test_packaged_example_is_offline_and_replayable(tmp_path, monkeypatch):
    # An HTTP attempt is a failure, even if a developer has live credentials.
    import httpx

    def denied(*args, **kwargs):
        raise AssertionError("Example must not use HTTP")

    monkeypatch.setattr(httpx.Client, "send", denied)
    out = tmp_path / "example"
    result = build_example(out)
    assert result["cells"] == 6 and result["resolved"] == 3
    assert result["replay_verified"]
    for extension in ("csv", "parquet", "duckdb"):
        assert (out / ("panel." + extension)).is_file()
    assert (
        loads((out / "receipt.json").read_bytes())["semantic"]["snapshot_id"]
        == result["snapshot_id"]
    )
    with pytest.raises(ValidationError, match="new directory"):
        build_example(out)


def test_version_and_release_metadata_agree():
    import tomllib

    data = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())
    assert __version__ == data["project"]["version"] == "0.1.0a2"
    assert data["project"]["requires-python"] == ">=3.12,<3.13"
    assert set(panel.__all__) >= {"PanelRequest", "PeriodEnd", "build", "export", "reproduce"}


def test_timezone_fallback_without_system_database():
    import subprocess
    import sys

    subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            "import zoneinfo; zoneinfo.reset_tzpath(()); "
            "from finpanel.filings import SEC_DAY_ZONE; "
            "from datetime import datetime; "
            "assert datetime(2024,1,1,tzinfo=SEC_DAY_ZONE).utcoffset().total_seconds() == -18000; "
            "assert datetime(2024,7,1,tzinfo=SEC_DAY_ZONE).utcoffset().total_seconds() == -14400",
        ],
        check=True,
    )
