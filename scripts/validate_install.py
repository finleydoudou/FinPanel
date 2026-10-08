"""Check wheel and sdist in separate clean venvs, outside the source checkout.

Usage: python scripts/validate_install.py dist [--wheelhouse PATH]
The optional wheelhouse allows fully offline dependency/build-tool installation.
"""

import argparse
import json
import subprocess
import sys
import tempfile
import venv
from pathlib import Path

CHECK = r"""
import json, sys
from pathlib import Path
import finpanel, httpx, zoneinfo
# Exercise the portable fallback, even on hosts with a system IANA database.
zoneinfo.reset_tzpath(())
zoneinfo.ZoneInfo.clear_cache()
from finpanel import panel
from finpanel.filings import SEC_DAY_ZONE
from datetime import datetime
assert datetime(2024, 1, 1, tzinfo=SEC_DAY_ZONE).utcoffset().total_seconds() == -18000
assert datetime(2024, 7, 1, tzinfo=SEC_DAY_ZONE).utcoffset().total_seconds() == -14400
from finpanel.example import build_example
assert Path(finpanel.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())
assert finpanel.__version__ == '0.1.0a1'
def denied(*args, **kwargs):
    raise AssertionError('Clean example attempted network')
httpx.Client.send = denied
out = Path('example')
result = build_example(out)
assert result['cells'] == 6 and result['resolved'] == 3 and result['replay_verified']
exports = [panel.read_export(out / ('panel.' + ext)) for ext in ('csv','parquet','duckdb')]
assert exports[0] == exports[1] == exports[2]
print(json.dumps(dict(version=finpanel.__version__, cells=result['cells'],
                     replay=True, export_round_trips=3,
                     isolated_import=True, timezone_fallback=True)))
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dist", type=Path)
    parser.add_argument("--wheelhouse", type=Path)
    args = parser.parse_args()
    artifacts = sorted(args.dist.resolve().glob("finpanel-*.whl")) + sorted(
        args.dist.resolve().glob("finpanel-*.tar.gz")
    )
    if len(artifacts) != 2:
        raise SystemExit("Expected exactly one wheel and one source distribution")
    results = []
    for artifact in artifacts:
        with tempfile.TemporaryDirectory(prefix="finpanel-clean-") as directory:
            root = Path(directory)
            env = root / "venv"
            venv.EnvBuilder(with_pip=True).create(env)
            python = env / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
            pip_args = (
                ["--no-index", "--find-links", str(args.wheelhouse.resolve())]
                if args.wheelhouse
                else []
            )
            subprocess.run(
                [str(python), "-m", "pip", "install", *pip_args, str(artifact)],
                cwd=root,
                check=True,
                stdout=subprocess.DEVNULL,
            )
            subprocess.run([str(python), "-m", "pip", "check"], cwd=root, check=True)
            subprocess.run(
                [str(python), "-I", "-m", "finpanel.cli", "--help"],
                cwd=root,
                check=True,
                stdout=subprocess.DEVNULL,
            )
            executable = env / (
                "Scripts/finpanel.exe" if sys.platform == "win32" else "bin/finpanel"
            )
            subprocess.run(
                [str(executable), "--help"], cwd=root, check=True, stdout=subprocess.DEVNULL
            )
            result = subprocess.check_output([str(python), "-I", "-c", CHECK], cwd=root, text=True)
            results.append(dict(artifact=artifact.name, **json.loads(result)))
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
