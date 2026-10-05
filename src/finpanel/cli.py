"""Developer summaries and exact raw exports; no financial interpretation."""

import argparse
import logging
import os
import sys
from collections import Counter
from pathlib import Path

from finpanel.cache.file import atomic_write
from finpanel.errors import FinPanelError
from finpanel.sec import parse_companyfacts, parse_submissions
from finpanel.sec.client import SECClient
from finpanel.serialization import dumps


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="finpanel")
    commands = parser.add_subparsers(dest="command", required=True)
    sec = commands.add_parser("sec")
    endpoints = sec.add_subparsers(dest="endpoint", required=True)
    for name in ("submissions", "companyfacts"):
        command = endpoints.add_parser(name)
        command.add_argument("cik")
        command.add_argument("--user-agent", default=os.getenv("FINPANEL_SEC_USER_AGENT"))
        command.add_argument("--cache-dir", type=Path, default=Path(".finpanel-cache"))
        command.add_argument("--refresh", action="store_true")
        command.add_argument("--raw-output", type=Path)
        command.add_argument("--normalized-output", type=Path)
        command.add_argument(
            "--strict", action="store_true", help="Exit 1 if parser issues are present"
        )
        command.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)
    if args.raw_output and args.normalized_output:
        same_path = args.raw_output.resolve() == args.normalized_output.resolve()
        same_file = (
            args.raw_output.exists()
            and args.normalized_output.exists()
            and args.raw_output.samefile(args.normalized_output)
        )
        if same_path or same_file:
            parser.error("--raw-output and --normalized-output must refer to different files")
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING)
    try:
        with SECClient(args.user_agent, cache_dir=args.cache_dir) as client:
            response = getattr(client, args.endpoint)(args.cik, refresh=args.refresh)
        if args.raw_output:
            atomic_write(args.raw_output, response.body)
        parse = parse_submissions if args.endpoint == "submissions" else parse_companyfacts
        result = parse(response)
        if args.normalized_output:
            atomic_write(args.normalized_output, dumps(result).encode())
        summary = {
            "endpoint": args.endpoint,
            "records": len(result.records),
            "issues": len(result.issues),
            "issue_codes": dict(Counter(i.code for i in result.issues)),
            "sha256": response.sha256,
            "source_url": response.url,
            "retrieved_at": response.retrieved_at,
            "from_cache": response.from_cache,
        }
        if args.endpoint == "submissions":
            summary["forms"] = dict(Counter(r.form or "(missing)" for r in result.records))
            summary["scope"] = "recent_only"
            summary["history_files"] = result.metadata["history_files"]
        else:
            summary["concepts"] = len({(r.taxonomy, r.concept) for r in result.records})
            summary["units"] = dict(Counter(r.unit for r in result.records))
        print(dumps(summary), end="")
        return 1 if args.strict and result.issues else 0
    except (FinPanelError, OSError) as exc:
        print(f"finpanel: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
