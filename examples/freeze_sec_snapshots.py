"""Opt-in genuine fixture capture. Never part of ordinary unit tests."""

import argparse
import sys
from pathlib import Path

from finpanel.cache.file import atomic_write
from finpanel.errors import FinPanelError
from finpanel.sec import parse_companyfacts, parse_submissions
from finpanel.sec.client import SECClient
from finpanel.serialization import dumps


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    manifest = {"kind": "official_sec_snapshots", "files": {}}
    companies = {"aapl": 320193, "msft": 789019, "wmt": 104169, "nvda": 1045810}
    try:
        if args.output.exists() and (not args.output.is_dir() or any(args.output.iterdir())):
            parser.error(
                "Snapshot destination must be empty; existing evidence is never overwritten"
            )
        with SECClient() as client:
            for ticker, cik in companies.items():
                for endpoint, parse in [
                    ("submissions", parse_submissions),
                    ("companyfacts", parse_companyfacts),
                ]:
                    response = getattr(client, endpoint)(cik, refresh=True)
                    result = parse(response)
                    filename = f"{ticker}_{endpoint}.json"
                    atomic_write(args.output / filename, response.body)
                    manifest["files"][filename] = {
                        "cik": str(cik).zfill(10),
                        "source_url": response.url,
                        "sha256": response.sha256,
                        "retrieved_at": response.retrieved_at,
                        "raw_unmodified": True,
                        "purpose": "Offline Phase 0A parsing and raw-provenance acceptance",
                        "records": len(result.records),
                        "issues": len(result.issues),
                    }
                    # A partial capture remains auditable and fails the eight-file acceptance gate.
                    atomic_write(args.output / "manifest.json", dumps(manifest).encode())
    except (FinPanelError, OSError) as exc:
        print(f"Snapshot capture failed: {exc}", file=sys.stderr)
        return 2
    print(f"Saved {len(manifest['files'])} official snapshots to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
