from finpanel.cli import main
from finpanel.serialization import loads


def test_universe_cli(capsys):
    assert main(["validate", "universe"]) == 0
    assert len(loads(capsys.readouterr().out.encode())["issuers"]) == 55


def test_invalid_benchmark_config_is_not_silently_ignored(tmp_path, capsys):
    p = tmp_path / "bad.json"
    p.write_text('{"guess_values":true}')
    assert (
        main(
            [
                "validate",
                "broad",
                "--store",
                str(tmp_path),
                "--snapshot",
                "0" * 64,
                "--output",
                str(tmp_path / "out"),
                "--config",
                str(p),
            ]
        )
        == 1
    )
    assert "Unknown benchmark configuration key" in capsys.readouterr().out
