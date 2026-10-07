import subprocess
import sys

from test_panel_engine import pinned

from finpanel import panel
from finpanel.cli import main
from finpanel.serialization import dumps, loads


def test_offline_cli_build_and_module_replay(tmp_path, capsys):
    store, req = pinned(tmp_path / "store")
    request_file = tmp_path / "request.json"
    request_file.write_text(dumps(req))
    out = tmp_path / "panel.parquet"
    assert (
        main(
            ["panel", "build", str(request_file), "--store", str(store.root), "--output", str(out)]
        )
        == 0
    )
    assert loads(capsys.readouterr().out.encode())["coverage"]["requested_cells"] == 4
    meta = loads((tmp_path / "panel.parquet.metadata.json").read_bytes())
    receipt_file = tmp_path / "receipt.json"
    receipt_file.write_text(dumps(meta["receipt"]))
    replay = tmp_path / "replay.csv"
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "finpanel.cli",
            "panel",
            "replay",
            str(receipt_file),
            "--store",
            str(store.root),
            "--output",
            str(replay),
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert panel.read_export(out) == panel.read_export(replay)


def test_cli_rejects_invalid_request(tmp_path, capsys):
    p = tmp_path / "bad.json"
    p.write_text("{}")
    assert main(["panel", "build", str(p), "--output", str(tmp_path / "out.csv")]) == 1
    assert "Panel failed" in capsys.readouterr().out
