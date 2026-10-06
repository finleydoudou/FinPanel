"""Seed Apple provenance fixtures and inspect one concept without SEC access."""

import argparse
from pathlib import Path

from finpanel import facts, filings
from finpanel.cache import FileCache
from finpanel.models import RawResponse
from finpanel.sec.client import SECClient
from finpanel.serialization import dumps, loads


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, default=Path("output/offline-provenance-cache"))
    args = parser.parse_args()
    fixtures = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
    cache = FileCache(args.cache_dir)
    for folder in (fixtures / "sec", fixtures / "history", fixtures / "headers"):
        for filename, meta in loads((folder / "manifest.json").read_bytes())["files"].items():
            if meta["cik"] != "0000320193":
                continue
            source = RawResponse(
                meta["source_url"],
                (folder / filename).read_bytes(),
                meta["retrieved_at"],
                raw_format=meta.get("raw_format", "json"),
            )
            if source.sha256 != meta["sha256"]:
                raise ValueError(f"Fixture hash mismatch: {filename}")
            cache.put(source)
    with SECClient(cache=cache, offline=True) as client:
        checked = filings.validate_availability(320193, "0000320193-24-000123", client=client)
        result = facts.for_concept(
            320193,
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            client=client,
            header_accessions=("0000320193-24-000123",),
        )
    print(
        dumps(
            {
                "header_comparison": checked.comparison_status,
                "observations": len(result.records),
                "repeated_period_groups": len(result.repeated_periods),
                "timeline_issue_codes": [i.code for i in result.timeline_issues],
            }
        ),
        end="",
    )


if __name__ == "__main__":
    main()
