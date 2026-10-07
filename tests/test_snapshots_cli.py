import json

import pytest
from test_snapshots_pipeline import snapshot

from finpanel.cli import main
from finpanel.snapshots import EvidenceStore


@pytest.mark.parametrize("action", ["list", "inspect", "verify"])
def test_local_snapshot_commands(tmp_path, capsys, action):
    store = EvidenceStore(tmp_path)
    s = snapshot(store)
    args = ["snapshots", action, "--store", str(tmp_path)]
    if action != "list":
        args.append(s.snapshot_id)
    assert main(args) == 0
    assert json.loads(capsys.readouterr().out)


def test_query_receipt_and_replay_command(tmp_path, capsys):
    store = EvidenceStore(tmp_path / "store")
    s = snapshot(store)
    receipt = tmp_path / "receipt.json"
    assert (
        main(
            [
                "snapshots",
                "query",
                s.snapshot_id,
                "--store",
                str(store.root),
                "--operation",
                "resolve",
                "--cik",
                "1",
                "--metric",
                "revenue",
                "--as-of",
                "2023-01-01T00:00:00Z",
                "--fiscal-year",
                "2021",
                "--period",
                "Q1",
                "--receipt",
                str(receipt),
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["value"] == 100
    assert main(["reproduce", str(receipt), "--store", str(store.root)]) == 0
    assert json.loads(capsys.readouterr().out)["verified"]
    assert main(["reproduce", str(receipt), "--store", str(tmp_path / "missing")]) == 1
    assert not json.loads(capsys.readouterr().out)["verified"]


def test_invalid_manifest_nonzero(tmp_path, capsys):
    assert main(["snapshots", "verify", "a" * 64, "--store", str(tmp_path)]) == 1
    assert not json.loads(capsys.readouterr().out)["valid"]
