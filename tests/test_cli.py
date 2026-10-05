import subprocess
import sys
from dataclasses import replace
from hashlib import sha256

import pytest

from finpanel.cache import FileCache
from finpanel.cli import main
from finpanel.serialization import loads


@pytest.mark.parametrize("endpoint", ["companyfacts", "submissions"])
def test_installed_cli_cached_export(tmp_path, raw, endpoint):
    prefix = "api/xbrl/companyfacts" if endpoint == "companyfacts" else "submissions"
    source = replace(raw(endpoint), url=f"https://data.sec.gov/{prefix}/CIK0000320193.json")
    FileCache(tmp_path / "cache").put(source)
    output = tmp_path / "raw.json"
    normalized = tmp_path / "normalized.json"
    command = [
        sys.executable,
        "-m",
        "finpanel.cli",
        "sec",
        endpoint,
        "320193",
        "--user-agent",
        "FinPanel test contact@example.com",
        "--cache-dir",
        str(tmp_path / "cache"),
        "--raw-output",
        str(output),
        "--normalized-output",
        str(normalized),
        "--strict",
    ]
    process = subprocess.run(command, capture_output=True, check=False)
    assert process.returncode == 0, process.stderr.decode()
    summary = loads(process.stdout)
    assert summary["from_cache"]
    assert summary["issues"] == 0
    assert summary["sha256"] == sha256(source.body).hexdigest()
    assert output.read_bytes() == source.body
    assert len(loads(normalized.read_bytes())["records"]) == summary["records"]


def test_cli_missing_user_agent(monkeypatch, capsys):
    monkeypatch.delenv("FINPANEL_SEC_USER_AGENT", raising=False)
    assert main(["sec", "submissions", "1"]) == 2
    assert "User-Agent" in capsys.readouterr().err


def test_cli_strict_issues(tmp_path, raw, capsys):
    source = replace(
        raw(data={"cik": 1, "facts": {"x": None}}),
        url="https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json",
    )
    FileCache(tmp_path).put(source)
    assert (
        main(
            [
                "sec",
                "companyfacts",
                "1",
                "--user-agent",
                "test",
                "--cache-dir",
                str(tmp_path),
                "--strict",
            ]
        )
        == 1
    )
    assert loads(capsys.readouterr().out.encode())["issues"] == 1


def test_no_fixture_manifest_drift():
    from pathlib import Path

    root = Path(__file__).parent / "fixtures"
    manifest = loads((root / "manifest.json").read_bytes())
    assert manifest["kind"] == "synthetic_schema_fixtures"
    for filename, meta in manifest["files"].items():
        assert sha256((root / filename).read_bytes()).hexdigest() == meta["sha256"]
        assert meta["source_url"] is None


@pytest.mark.parametrize("alias", ["identical", "symlink", "hardlink"])
def test_export_collision_rejected_before_request(tmp_path, alias, capsys):
    original = tmp_path / "raw.json"
    original.write_bytes(b"preserve evidence")
    other = tmp_path / "normalized.json"
    if alias == "identical":
        other = original
    elif alias == "symlink":
        other.symlink_to(original)
    else:
        other.hardlink_to(original)
    with pytest.raises(SystemExit) as exc:
        main(
            [
                "sec",
                "submissions",
                "1",
                "--raw-output",
                str(original),
                "--normalized-output",
                str(other),
            ]
        )
    assert exc.value.code == 2
    assert "different files" in capsys.readouterr().err
    assert original.read_bytes() == b"preserve evidence"
