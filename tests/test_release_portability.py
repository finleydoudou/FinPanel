"""Regression checks for the Windows release-candidate failures."""

import runpy
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_research_example_imports_without_unix_resource(monkeypatch):
    monkeypatch.setitem(sys.modules, "resource", None)
    example = runpy.run_path(str(ROOT / "examples/build_research_panel.py"))
    assert example["peak_memory"]() is None
    assert callable(example["benchmark"])


def test_frozen_evidence_checkout_preserves_bytes_with_autocrlf(tmp_path):
    # A disposable index exercises real Git conversion; no commit/ref is created.
    repo = tmp_path / "checkout"
    repo.mkdir()

    def git(*args):
        return subprocess.check_output(
            ["git", "-c", "core.autocrlf=true", "-c", "core.eol=crlf", *args], cwd=repo
        )

    git("init", "--quiet")
    (repo / ".gitattributes").write_bytes((ROOT / ".gitattributes").read_bytes())
    paths = (
        "tests/fixtures/aapl_companyfacts.json",
        "tests/fixtures/xbrl/aapl-0000320193-24-000006-0000320193-24-000006-index.html",
        "src/finpanel/example_data/manifest.json",
    )
    expected = {}
    for name in paths:
        target = repo / name
        target.parent.mkdir(parents=True, exist_ok=True)
        expected[name] = (ROOT / name).read_bytes()
        target.write_bytes(expected[name])
    git("add", ".gitattributes", *paths)
    for name in paths:
        (repo / name).unlink()
    git("checkout-index", "--all")
    for name in paths:
        assert (repo / name).read_bytes() == expected[name], name
