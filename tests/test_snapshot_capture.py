"""Capture workflow uses mocked HTTP; these tests never download SEC data."""

import runpy
from pathlib import Path

import httpx
import pytest

from finpanel.sec.client import SECClient
from finpanel.serialization import loads


@pytest.fixture
def capture():
    path = Path(__file__).parents[1] / "examples" / "freeze_sec_snapshots.py"
    return runpy.run_path(str(path))["main"]


def test_capture_preserves_bytes_and_manifest(capture, monkeypatch, tmp_path, limiter, raw):
    monkeypatch.setenv("FINPANEL_SEC_USER_AGENT", "Research contact@example.org")
    bodies = {}
    tickers = {
        "0000320193": "aapl",
        "0000789019": "msft",
        "0000104169": "wmt",
        "0001045810": "nvda",
    }

    def handler(request):
        cik = request.url.path.rsplit("CIK", 1)[1].removesuffix(".json")
        endpoint = "companyfacts" if "companyfacts" in request.url.path else "submissions"
        body = raw(endpoint, tickers[cik]).body
        bodies[f"{tickers[cik]}_{endpoint}.json"] = body
        return httpx.Response(200, content=body)

    monkeypatch.setitem(
        capture.__globals__,
        "SECClient",
        lambda: SECClient(
            cache_dir=tmp_path / "cache", limiter=limiter, transport=httpx.MockTransport(handler)
        ),
    )
    output = tmp_path / "snapshots"
    assert capture(["--output", str(output)]) == 0
    manifest = loads((output / "manifest.json").read_bytes())
    assert len(manifest["files"]) == 8
    for filename, meta in manifest["files"].items():
        assert (output / filename).read_bytes() == bodies[filename]
        assert meta["raw_unmodified"] is True
        assert meta["purpose"]
        assert "User-Agent" not in meta


def test_capture_refuses_existing_evidence(capture, tmp_path):
    evidence = tmp_path / "existing.json"
    evidence.write_bytes(b"untouched")
    with pytest.raises(SystemExit) as exc:
        capture(["--output", str(tmp_path)])
    assert exc.value.code == 2
    assert evidence.read_bytes() == b"untouched"


def test_capture_failure_retains_partial_manifest(capture, monkeypatch, tmp_path, limiter, raw):
    calls = []

    def handler(request):
        calls.append(request)
        return (
            httpx.Response(200, content=raw("submissions").body)
            if len(calls) == 1
            else httpx.Response(403)
        )

    monkeypatch.setitem(
        capture.__globals__,
        "SECClient",
        lambda: SECClient(
            "test",
            cache_dir=tmp_path / "cache",
            limiter=limiter,
            transport=httpx.MockTransport(handler),
        ),
    )
    output = tmp_path / "snapshots"
    assert capture(["--output", str(output)]) == 2
    manifest = loads((output / "manifest.json").read_bytes())
    assert set(manifest["files"]) == {"aapl_submissions.json"}
    assert len(calls) == 2
    assert (output / "aapl_submissions.json").read_bytes() == raw("submissions").body


def test_capture_missing_identity_is_clear(capture, tmp_path, capsys):
    assert capture(["--output", str(tmp_path / "snapshots")]) == 2
    assert "FINPANEL_SEC_USER_AGENT" in capsys.readouterr().err
    assert not (tmp_path / "snapshots").exists()
