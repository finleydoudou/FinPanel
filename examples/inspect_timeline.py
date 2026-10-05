"""Seed a local offline cache with the committed Apple timeline fixtures."""

import argparse
from pathlib import Path

from finpanel import filings
from finpanel.cache import FileCache
from finpanel.models import RawResponse
from finpanel.sec.client import SECClient
from finpanel.serialization import dumps, loads


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, default=Path("output/offline-cache"))
    args = parser.parse_args()
    fixtures = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
    cache = FileCache(args.cache_dir)
    for folder in (fixtures / "sec", fixtures / "history"):
        manifest = loads((folder / "manifest.json").read_bytes())
        for filename, meta in manifest["files"].items():
            if meta["cik"] != "0000320193" or "companyfacts" in filename:
                continue
            source = RawResponse(
                meta["source_url"], (folder / filename).read_bytes(), meta["retrieved_at"]
            )
            if source.sha256 != meta["sha256"]:
                raise ValueError(f"Fixture hash mismatch: {filename}")
            cache.put(source)
    with SECClient(cache=cache, offline=True) as client:
        print(dumps(filings.coverage("0000320193", client=client)), end="")


if __name__ == "__main__":
    main()
