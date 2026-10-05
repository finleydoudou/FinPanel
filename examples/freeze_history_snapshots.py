"""Capture only history files referenced by an existing, hashed submissions fixture."""

import argparse
import sys
from pathlib import Path

from finpanel.cache.file import atomic_write
from finpanel.errors import FinPanelError
from finpanel.models import RawResponse
from finpanel.sec.client import RateLimiter, SECClient
from finpanel.sec.submissions import discover_historical_submissions, parse_historical_submissions
from finpanel.serialization import dumps, loads


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parent", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.output.exists() and (not args.output.is_dir() or any(args.output.iterdir())):
            parser.error("Destination must be absent or empty")
        parent_meta = loads((args.parent.parent / "manifest.json").read_bytes())["files"][
            args.parent.name
        ]
        parent = RawResponse(
            parent_meta["source_url"], args.parent.read_bytes(), parent_meta["retrieved_at"]
        )
        if parent.sha256 != parent_meta["sha256"]:
            parser.error("Parent fixture hash does not match its manifest")
        discovery = discover_historical_submissions(parent)
        if discovery.issues:
            parser.error("Parent historical references contain issues; inspect before capturing")
        manifest = {
            "kind": "official_sec_historical_snapshots",
            "parent_file": args.parent.name,
            "parent_sha256": parent.sha256,
            "parent_source_url": parent.url,
            "files": {},
        }
        with SECClient(limiter=RateLimiter(interval=2.0)) as client:
            for ref in sorted(
                {r.name: r for r in discovery.records}.values(), key=lambda r: r.name
            ):
                source = client.historical_submissions(ref.cik, ref.name, refresh=True)
                result = parse_historical_submissions(source, cik=ref.cik)
                atomic_write(args.output / ref.name, source.body)
                manifest["files"][ref.name] = {
                    "cik": ref.cik,
                    "source_url": source.url,
                    "retrieved_at": source.retrieved_at,
                    "sha256": source.sha256,
                    "raw_unmodified": True,
                    "purpose": "Offline historical submissions and filing timeline acceptance",
                    "records": len(result.records),
                    "issues": len(result.issues),
                }
                atomic_write(args.output / "manifest.json", dumps(manifest).encode())
        print(f"Captured {len(manifest['files'])} historical SEC files")
        return 0
    except (FinPanelError, OSError, KeyError) as exc:
        print(f"Historical snapshot capture failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
