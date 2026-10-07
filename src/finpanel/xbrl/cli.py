"""Compact offline-capable developer evidence inspection."""

from pathlib import Path

from finpanel.cache.file import atomic_write
from finpanel.errors import FinPanelError, ValidationError
from finpanel.sec import parse_companyfacts, parse_submissions
from finpanel.sec.client import SECClient
from finpanel.serialization import dumps
from finpanel.xbrl import inspect_filing, verify_fact


def add_commands(commands):
    actions = commands.add_parser("xbrl").add_subparsers(dest="action", required=True)
    for action in ("filing", "contexts", "verify-fact"):
        command = actions.add_parser(action)
        command.add_argument("accession")
        command.add_argument("--cik", required=True)
        command.add_argument("--cache-dir", type=Path, default=Path(".finpanel-cache"))
        command.add_argument("--offline", action="store_true")
        command.add_argument("--output", type=Path)
        command.add_argument("--limit", type=int, default=10)
        command.add_argument("--strict", action="store_true")
        if action == "verify-fact":
            command.add_argument("--concept", required=True)
            command.add_argument("--taxonomy", default="us-gaap")
            command.add_argument("--as-of", required=True)
            command.add_argument("--start")
            command.add_argument("--end")
            command.add_argument("--unit", default="USD")


def verification_summary(v):
    return {
        "observation_id": v.observation.observation_id,
        "value": v.observation.value,
        "state": v.state,
        "scope_state": v.scope_state,
        "period_state": v.period_state,
        "diagnostics": v.diagnostics,
        "temporal_contract": v.temporal_contract,
        "matches": [
            {
                "context_id": d.context.context_id,
                "dimensions": d.context.dimensions,
                "unit_id": d.unit.unit_id,
                "unit": d.unit.numerator,
                "decimals": d.fact.numeric.decimals,
                "precision": d.fact.numeric.precision,
                "lexical_value": d.fact.lexical_value,
                "source": d.fact.provenance,
            }
            for d in v.matches
        ],
    }


def run(args):
    try:
        with SECClient(cache_dir=args.cache_dir, offline=args.offline) as client:
            parsed = parse_submissions(client.submissions(args.cik))
            filings = [f for f in parsed.records if f.accession_number == args.accession]
            if len(filings) != 1:
                raise ValidationError("Accession absent or ambiguous in cached recent submissions")
            sources, instances = inspect_filing(filings[0], client=client)
            summary = {
                "accession": args.accession,
                "diagnostics": sources.diagnostics,
                "documents": [i.document for i in instances],
            }
            source_summary = {
                "filing": sources.filing,
                "documents": sources.documents,
                "metadata": [r.provenance("/") for r in sources.metadata],
                "diagnostics": sources.diagnostics,
            }
            failed = bool(sources.diagnostics or not instances)
            if args.action == "filing":
                summary.update(
                    {
                        "mode": "retrospective_inventory",
                        "inventory": sources.documents,
                        "instances": len(instances),
                    }
                )
                full = {"sources": source_summary, "instances": instances}
            elif args.action == "contexts":
                contexts = [c for i in instances for c in i.contexts]
                summary.update(
                    {
                        "mode": "retrospective_inventory",
                        "context_count": len(contexts),
                        "contexts": [
                            {
                                "context_id": c.context_id,
                                "entity": c.entity_identifier,
                                "period_type": c.period_type,
                                "start": c.start,
                                "end": c.end,
                                "dimensions": c.dimensions,
                                "dimension_state": c.dimension_state,
                                "fingerprint": c.fingerprint,
                                "source": c.provenance,
                                "diagnostics": c.diagnostics,
                            }
                            for c in contexts[: args.limit]
                        ],
                    }
                )
                full = {
                    "sources": source_summary,
                    "contexts": contexts,
                    "units": [u for i in instances for u in i.units],
                }
            else:
                observations = [
                    f
                    for f in parse_companyfacts(client.companyfacts(args.cik)).records
                    if f.accession_number == args.accession
                    and f.concept == args.concept
                    and f.taxonomy == args.taxonomy
                    and f.unit == args.unit
                    and (args.start is None or str(f.period_start) == args.start)
                    and (args.end is None or str(f.period_end) == args.end)
                ]
                verified = [
                    verify_fact(f, instances=instances, as_of=args.as_of) for f in observations
                ]
                summary = {
                    "accession": args.accession,
                    "as_of": args.as_of,
                    "count": len(verified),
                    "verifications": [verification_summary(v) for v in verified[: args.limit]],
                }
                full = verified
                failed = not verified or any(not v.state.startswith("verified") for v in verified)
        if args.output:
            atomic_write(args.output, dumps(full).encode())
        print(dumps(summary), end="")
        return 1 if args.strict and failed else 0
    except FinPanelError as exc:
        import sys

        print(str(exc), file=sys.stderr)
        return 1
