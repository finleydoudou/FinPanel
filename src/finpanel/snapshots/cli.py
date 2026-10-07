"""Local-only snapshot inspection, pinned queries and replay."""

from pathlib import Path

from finpanel.errors import FinPanelError
from finpanel.serialization import dumps
from finpanel.snapshots import EvidenceStore, read_receipt, reproduce, run


def add_commands(commands):
    sub = commands.add_parser("snapshots").add_subparsers(dest="action", required=True)
    for action in ("list", "inspect", "verify", "query"):
        p = sub.add_parser(action)
        p.add_argument("--store", type=Path, required=True)
        if action != "list":
            p.add_argument("snapshot_id")
        if action == "query":
            p.add_argument(
                "--operation", choices=("resolve", "derive_quarter", "verify_fact"), required=True
            )
            p.add_argument("--cik", required=True)
            p.add_argument("--metric")
            p.add_argument("--as-of", required=True)
            p.add_argument("--receipt", type=Path, required=True)
            p.add_argument("--fiscal-year", type=int)
            p.add_argument("--period")
            p.add_argument("--quarter")
            p.add_argument("--start")
            p.add_argument("--end")
            p.add_argument("--accession")
            p.add_argument("--concept")
            p.add_argument("--revision-policy", default="latest_available")
            p.add_argument(
                "--source-verification", choices=("off", "best_effort", "required"), default="off"
            )
    p = commands.add_parser("reproduce")
    p.add_argument("receipt", type=Path)
    p.add_argument("--store", type=Path, required=True)


def command(args):
    try:
        store = EvidenceStore(args.store)
        if args.command == "reproduce":
            result = reproduce(read_receipt(args.receipt), store=store)
            print(dumps(result), end="")
            return 0 if result.verified else 1
        if args.action == "list":
            print(
                dumps(
                    {
                        "snapshots": [
                            {
                                "snapshot_id": s.snapshot_id,
                                "scope": s.manifest["scope"],
                                "captured_through": s.manifest["captured_through"],
                                "completeness": s.manifest["completeness"],
                            }
                            for s in store.list()
                        ]
                    }
                ),
                end="",
            )
        elif args.action == "inspect":
            print(dumps(store.load(args.snapshot_id)), end="")
        elif args.action == "verify":
            result = store.verify(args.snapshot_id)
            print(dumps(result), end="")
            return 0 if result.valid else 1
        else:
            names = {
                "resolve": ("fiscal_year", "period", "start", "end", "revision_policy"),
                "derive_quarter": ("fiscal_year", "quarter", "revision_policy"),
                "verify_fact": ("accession", "concept", "start", "end"),
            }[args.operation]
            parameters = {k: getattr(args, k) for k in names if getattr(args, k) is not None}
            result = run(
                store,
                snapshot_id=args.snapshot_id,
                operation=args.operation,
                cik=args.cik,
                metric=args.metric,
                as_of=args.as_of,
                parameters=parameters,
                source_verification=args.source_verification,
            )
            from finpanel.snapshots.store import _publish

            _publish(args.receipt, dumps(result.reproducibility).encode())
            print(
                dumps(
                    {
                        "snapshot_id": result.snapshot_id,
                        "receipt_id": result.reproducibility.receipt_id,
                        "evidence_mode": result.evidence_mode,
                        **result.reproducibility.semantic["result"],
                    }
                ),
                end="",
            )
        return 0
    except (FinPanelError, OSError, TypeError) as exc:
        import sys

        print(str(exc), file=sys.stderr)
        return 1
