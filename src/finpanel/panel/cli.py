"""Offline panel build, coverage and pinned replay entry points."""

from pathlib import Path

from finpanel.errors import FinPanelError, ValidationError
from finpanel.panel import PanelReceipt, PanelRequest, build, export, reproduce
from finpanel.sec.client import SECClient
from finpanel.serialization import dumps, loads
from finpanel.snapshots import EvidenceStore


def add_commands(commands):
    sub = commands.add_parser("panel").add_subparsers(dest="action", required=True)
    for action in ("build", "replay"):
        command = sub.add_parser(action)
        command.add_argument("input", type=Path, help="Request JSON or panel receipt JSON")
        command.add_argument("--store", type=Path)
        command.add_argument("--output", type=Path, required=True, help=".csv, .parquet or .duckdb")
        if action == "build":
            command.add_argument("--cache-dir", type=Path, default=Path(".finpanel-cache"))


def command(args):
    try:
        data = loads(args.input.read_bytes())
        store = EvidenceStore(args.store) if args.store else None
        if args.action == "replay":
            if store is None:
                raise ValidationError("Replay requires --store")
            result = reproduce(PanelReceipt(**data), store=store)
        else:
            request = PanelRequest(**data)
            if request.snapshot_id:
                result = build(request, store=store)
            else:
                if store is not None:
                    raise ValidationError("Store requires a pinned request")
                with SECClient(cache_dir=args.cache_dir, offline=True) as client:
                    result = build(request, client=client)
        export(result, args.output)
        print(dumps({"receipt_id": result.receipt.receipt_id, "coverage": result.coverage()}))
        return 0
    except (FinPanelError, OSError, ValueError, TypeError) as exc:
        print(f"Panel failed: {exc}")
        return 1
