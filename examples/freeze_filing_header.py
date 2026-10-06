"""Capture one official header using the normal client and local environment identity."""

import argparse
from pathlib import Path

from finpanel.cache.file import atomic_write
from finpanel.sec.client import RateLimiter, SECClient
from finpanel.sec.common import normalize_cik
from finpanel.sec.headers import parse_filing_header
from finpanel.serialization import dumps


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cik")
    parser.add_argument("accession")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    cik = normalize_cik(args.cik)
    if args.output.exists() and (not args.output.is_dir() or any(args.output.iterdir())):
        parser.error("--output must be absent or empty; existing evidence cannot be overwritten")
    with SECClient(limiter=RateLimiter(interval=2.0)) as client:
        source = client.filing_header(cik, args.accession, refresh=True)
    parsed = parse_filing_header(source)
    if parsed.accession_number != args.accession or (parsed.ciks and cik not in parsed.ciks):
        raise ValueError("Header identity does not match the requested filing")
    filename = f"{args.accession}.hdr.sgml"
    atomic_write(args.output / filename, source.body)
    atomic_write(
        args.output / "manifest.json",
        dumps(
            {
                "kind": "official_sec_filing_headers",
                "files": {
                    filename: {
                        "accession": args.accession,
                        "cik": cik,
                        "source_url": source.url,
                        "retrieved_at": source.retrieved_at,
                        "sha256": source.sha256,
                        "raw_format": "text",
                        "raw_unmodified": True,
                        "purpose": "Offline acceptance and filing metadata corroboration; "
                        "no dissemination claim",
                    }
                },
            }
        ).encode(),
    )


if __name__ == "__main__":
    main()
