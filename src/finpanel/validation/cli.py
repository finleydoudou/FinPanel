"""Explicit acquisition and offline broad/golden validation, separate from routine CI."""

from dataclasses import fields
from pathlib import Path

from finpanel.errors import FinPanelError
from finpanel.serialization import dumps, loads
from finpanel.snapshots import EvidenceStore
from finpanel.validation.acquisition import acquire, acquire_originals
from finpanel.validation.goldens import validate_goldens
from finpanel.validation.runner import BenchmarkConfig, run
from finpanel.validation.universe import universe


def add_commands(commands):
    sub = commands.add_parser("validate").add_subparsers(dest="action", required=True)
    p = sub.add_parser("universe")
    p.add_argument("--output", type=Path)
    p = sub.add_parser("acquire")
    p.add_argument("destination", type=Path)
    p.add_argument("--originals", action="store_true")
    p.add_argument("--tier", choices=["A", "B"], default="B")
    p.add_argument("--limit", type=int)
    p.add_argument("--universe", type=Path)
    for action in ["broad", "goldens"]:
        p = sub.add_parser(action)
        p.add_argument("--store", type=Path, required=True)
        p.add_argument("--snapshot", required=True)
        p.add_argument("--output", type=Path, required=True)
        if action == "broad":
            p.add_argument("--resume", action="store_true")
            p.add_argument("--checkpoint", type=Path)
            p.add_argument("--issuer", action="append", dest="subset")
            p.add_argument("--workers", type=int, default=1)
            p.add_argument("--config", type=Path)
            p.add_argument("--universe", type=Path)
            p.add_argument("--tier", choices=["A", "B"], default="B")
            p.add_argument("--limit", type=int)
        else:
            p.add_argument("--goldens", type=Path, required=True)


def command(args):
    try:
        if args.action == "universe":
            data = universe()
            if args.output:
                with args.output.open("x") as f:
                    f.write(dumps(data))
            else:
                print(dumps(data))
            return 0
        if args.action == "acquire":
            manifest = loads(args.universe.read_bytes()) if args.universe else None
            if args.originals:
                result = acquire_originals(args.destination, manifest=manifest)
            else:
                result = acquire(
                    args.destination, manifest=manifest, tier=args.tier, limit=args.limit
                )
            print(
                dumps(
                    {
                        "snapshot_id": result["snapshot_id"],
                        "acquisition_failures": result["failures"],
                        "original_failures": result.get("original_failures", {}),
                    }
                )
            )
            return int(bool(result["failures"] or result.get("original_failures")))
        store = EvidenceStore(args.store)
        if args.action == "goldens":
            result = validate_goldens(store, args.snapshot, args.goldens, output=args.output)
        else:
            config = loads(args.config.read_bytes()) if args.config else {}
            if set(config) - {f.name for f in fields(BenchmarkConfig)}:
                raise ValueError("Unknown benchmark configuration key")
            result, _, performance = run(
                store,
                args.snapshot,
                args.output,
                config=BenchmarkConfig(**config),
                manifest=loads(args.universe.read_bytes()) if args.universe else None,
                tier=args.tier,
                limit=args.limit,
                resume=args.resume,
                checkpoint=args.checkpoint,
                subset=args.subset,
                workers=args.workers,
            )
            print(dumps({"performance": performance}))
        print(dumps({k: v for k, v in result.items() if k not in {"findings", "receipts"}}))
        return int(bool(result["unexpected_mismatches"]))
    except (FinPanelError, OSError, ValueError, TypeError) as exc:
        print("Validation failed: " + str(exc))
        return 1
