"""Exercise every XBRL command with frozen cache only, including full exports."""

import json
import runpy
from pathlib import Path

import pytest

from finpanel.cache import FileCache
from finpanel.cli import main

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def cache(tmp_path_factory):
    folder = tmp_path_factory.mktemp("xbrl-cli")
    runpy.run_path(str(ROOT / "examples/validate_xbrl.py"))["seed_cache"](FileCache(folder))
    return folder


@pytest.mark.parametrize("action", ["filing", "contexts", "verify-fact"])
def test_offline_commands_and_exports(cache, tmp_path, capsys, action):
    output = tmp_path / "export.json"
    args = [
        "xbrl",
        action,
        "0000320193-24-000069",
        "--cik",
        "320193",
        "--offline",
        "--cache-dir",
        str(cache),
        "--limit",
        "1",
        "--output",
        str(output),
    ]
    if action == "verify-fact":
        args += [
            "--concept",
            "Assets",
            "--end",
            "2024-03-30",
            "--as-of",
            "2026-10-08T00:00:00Z",
            "--strict",
        ]
    assert main(args) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["accession"] == "0000320193-24-000069"
    assert output.exists() and json.loads(output.read_text(encoding="utf-8"))
    if action == "verify-fact":
        assert result["verifications"][0]["state"] == "verified_unique"
    if action == "contexts":
        assert len(result["contexts"]) == 1 and "raw_xml" not in result["contexts"][0]


@pytest.mark.parametrize("action", ["filing", "verify-fact"])
def test_exports_with_windows_default_encoding(cache, tmp_path, capsys, monkeypatch, action):
    read_text = Path.read_text

    def windows_read_text(path, encoding=None, errors=None):
        return read_text(path, encoding=encoding or "cp1252", errors=errors)

    # Exercise the real export assertions under Windows' non-UTF-8 default.
    monkeypatch.setattr(Path, "read_text", windows_read_text)
    test_offline_commands_and_exports(cache, tmp_path, capsys, action)
    raw = (tmp_path / "export.json").read_bytes()
    assert json.loads(raw.decode("utf-8"))
    # Authentic narrative text makes this a non-vacuous encoding regression.
    with pytest.raises(UnicodeDecodeError):
        raw.decode("cp1252")


def test_ambiguous_strict_exit(cache, capsys):
    assert (
        main(
            [
                "xbrl",
                "verify-fact",
                "0000320193-24-000069",
                "--cik",
                "320193",
                "--offline",
                "--cache-dir",
                str(cache),
                "--concept",
                "NetIncomeLoss",
                "--as-of",
                "2026-10-08T00:00:00Z",
                "--strict",
            ]
        )
        == 1
    )
    data = json.loads(capsys.readouterr().out)
    assert all(v["state"] == "ambiguous_match" for v in data["verifications"])


def test_future_evidence_not_exposed_by_verification_cli(cache, capsys):
    assert (
        main(
            [
                "xbrl",
                "verify-fact",
                "0000320193-24-000069",
                "--cik",
                "320193",
                "--offline",
                "--cache-dir",
                str(cache),
                "--concept",
                "Assets",
                "--as-of",
                "2024-05-05T00:00:00Z",
            ]
        )
        == 0
    )
    data = json.loads(capsys.readouterr().out)
    assert all(
        v["state"] == "instance_unavailable" and not v["matches"] for v in data["verifications"]
    )
    assert "documents" not in data


def test_missing_cache_explicit(tmp_path, capsys):
    assert (
        main(
            [
                "xbrl",
                "filing",
                "0000320193-24-000069",
                "--cik",
                "320193",
                "--offline",
                "--cache-dir",
                str(tmp_path),
            ]
        )
        == 1
    )
    assert "Offline cache miss" in capsys.readouterr().err
