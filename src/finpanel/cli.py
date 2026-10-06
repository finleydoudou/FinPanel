"""Developer summaries and exact raw exports; no financial interpretation."""

import argparse
import logging
import os
import sys
from collections import Counter
from pathlib import Path

from finpanel import asof, facts, filings, periods, revisions
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
    filing_commands = commands.add_parser("filings").add_subparsers(dest="action", required=True)
    for action in ("timeline", "available-as-of", "coverage", "validate-availability"):
        command = filing_commands.add_parser(action)
        command.add_argument("cik")
        if action == "available-as-of":
            command.add_argument("as_of")
        if action == "validate-availability":
            command.add_argument("accession")
        command.add_argument("--user-agent", default=os.getenv("FINPANEL_SEC_USER_AGENT"))
        command.add_argument("--cache-dir", type=Path, default=Path(".finpanel-cache"))
        command.add_argument("--refresh", action="store_true")
        command.add_argument("--offline", action="store_true")
        command.add_argument("--output", type=Path, help="Save full records, issues and provenance")
        command.add_argument(
            "--limit", type=int, default=20, help="Maximum displayed filing entries"
        )
        command.add_argument(
            "--strict", action="store_true", help="Exit 1 on parsing or coverage issues"
        )
    evidence_commands = commands.add_parser("asof").add_subparsers(dest="action", required=True)
    command = evidence_commands.add_parser("evidence")
    command.add_argument("cik")
    command.add_argument("as_of")
    command.add_argument("--concept")
    command.add_argument("--taxonomy")
    command.add_argument("--user-agent", default=os.getenv("FINPANEL_SEC_USER_AGENT"))
    command.add_argument("--cache-dir", type=Path, default=Path(".finpanel-cache"))
    command.add_argument("--offline", action="store_true")
    command.add_argument("--refresh", action="store_true")
    command.add_argument("--output", type=Path)
    command.add_argument("--limit", type=int, default=10)
    command.add_argument("--strict", action="store_true")
    fact_commands = commands.add_parser("facts").add_subparsers(dest="action", required=True)
    for action in ("inspect", "periods", "revisions"):
        command = fact_commands.add_parser(action)
        command.add_argument("cik")
        command.add_argument("concept")
        command.add_argument("--taxonomy")
        if action == "revisions":
            command.add_argument("--as-of", required=True)
            command.add_argument(
                "--policy", choices=sorted(revisions.POLICIES), default="all_available"
            )
        else:
            command.add_argument(
                "--header-accession",
                action="append",
                default=[],
                help="Explicitly fetch a header for this accession; repeatable",
            )
        command.add_argument("--user-agent", default=os.getenv("FINPANEL_SEC_USER_AGENT"))
        command.add_argument("--cache-dir", type=Path, default=Path(".finpanel-cache"))
        command.add_argument("--offline", action="store_true")
        command.add_argument("--refresh", action="store_true")
        command.add_argument("--output", type=Path)
        command.add_argument("--limit", type=int, default=10)
        command.add_argument(
            "--strict",
            action="store_true",
            help="Exit 1 for source issues or verified inconsistencies",
        )
    args = parser.parse_args(argv)
    if args.command in ("filings", "facts", "asof"):
        if args.limit < 0:
            parser.error("--limit must be nonnegative")
        if args.command == "asof" or (args.command == "facts" and args.action == "revisions"):
            return _asof_command(args)
        if args.command == "facts" and args.action == "periods":
            return _periods_command(args)
        return _facts_command(args) if args.command == "facts" else _filings_command(args)
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


def _filings_command(args: argparse.Namespace) -> int:
    try:
        with SECClient(args.user_agent, cache_dir=args.cache_dir, offline=args.offline) as client:
            if args.action == "validate-availability":
                validation = filings.validate_availability(
                    args.cik, args.accession, client=client, refresh=args.refresh
                )
                if args.output:
                    atomic_write(args.output, dumps(validation).encode())
                print(
                    dumps(
                        {
                            "cik": validation.filing.cik,
                            "accession": args.accession,
                            "comparison_status": validation.comparison_status,
                            "availability": validation.availability,
                            "diagnostics": validation.diagnostics,
                            "headers": [h.provenance for h in validation.headers],
                        }
                    ),
                    end="",
                )
                return (
                    1
                    if args.strict
                    and any(d.category == "verified_inconsistency" for d in validation.diagnostics)
                    else 0
                )
            if args.action == "available-as-of":
                data = filings.available_as_of(
                    args.cik, args.as_of, client=client, refresh=args.refresh
                )
            else:
                data = filings.timeline(args.cik, client=client, refresh=args.refresh)
        if args.output:
            atomic_write(args.output, dumps(data).encode())
        if args.action == "coverage":
            summary = filings.coverage(data)
        else:
            summary = {
                "cik": data.cik,
                "total_filings": len(data),
                "shown": min(args.limit, len(data)),
                "issues": len(data.issues),
                "issue_codes": dict(Counter(i.code for i in data.issues)),
                "historical_files_loaded": data.historical_files_loaded,
                "sources": data.sources,
                "records": [
                    {
                        "accession_number": r.accession_number,
                        "form": r.form,
                        "filing_date": r.filing_date,
                        "availability": r.availability,
                        "is_amendment": r.is_amendment,
                        "conflicts": r.conflicts,
                        "source_records": len(r.source_records),
                    }
                    for r in data.records[: args.limit]
                ],
            }
            if args.action == "available-as-of":
                summary["as_of"] = args.as_of
        print(dumps(summary), end="")
        return 1 if args.strict and data.issues else 0
    except (FinPanelError, OSError) as exc:
        print(f"finpanel: {exc}", file=sys.stderr)
        return 2


def _facts_command(args: argparse.Namespace) -> int:
    try:
        with SECClient(args.user_agent, cache_dir=args.cache_dir, offline=args.offline) as client:
            result = facts.for_concept(
                args.cik,
                args.concept,
                taxonomy=args.taxonomy,
                client=client,
                header_accessions=tuple(args.header_accession),
                refresh=args.refresh,
            )
        if args.output:
            atomic_write(args.output, dumps(result).encode())
        diagnostics = [*result.diagnostics, *(d for r in result.records for d in r.diagnostics)]
        summary = {
            "cik": result.cik,
            "concept": result.concept,
            "observations": len(result.records),
            "shown": min(len(result.records), args.limit),
            "repeated_period_groups": len(result.repeated_periods),
            "diagnostic_counts": dict(Counter(d.code for d in diagnostics)),
            "source_issue_counts": dict(Counter(i.code for i in result.source_issues)),
            "timeline_issue_counts": dict(Counter(i.code for i in result.timeline_issues)),
            "records": [
                {
                    "observation_id": r.observation_id,
                    "taxonomy": r.observation.taxonomy,
                    "value": r.observation.value,
                    "unit": r.observation.unit,
                    "context": r.context,
                    "accession": r.observation.accession_number,
                    "form": r.observation.form,
                    "availability_method": r.availability.method,
                    "availability_precision": r.availability.precision,
                    "availability_timestamp": r.availability.timestamp,
                    "availability_date": r.availability.date,
                    "source": r.observation.provenance,
                    "diagnostics": r.diagnostics,
                }
                for r in result.records[: args.limit]
            ],
        }
        print(dumps(summary), end="")
        bad = (
            result.source_issues
            or result.timeline_issues
            or any(d.category == "verified_inconsistency" for d in diagnostics)
        )
        return 1 if args.strict and bad else 0
    except (FinPanelError, OSError) as exc:
        print(f"finpanel: {exc}", file=sys.stderr)
        return 2


def _periods_command(args: argparse.Namespace) -> int:
    try:
        with SECClient(args.user_agent, cache_dir=args.cache_dir, offline=args.offline) as client:
            inspected = facts.for_concept(
                args.cik,
                args.concept,
                taxonomy=args.taxonomy,
                client=client,
                header_accessions=tuple(args.header_accession),
                refresh=args.refresh,
            )
        result = periods.interpret(inspected)
        if args.output:
            atomic_write(args.output, dumps(result).encode())
        diagnostics = [
            *result.calendar.diagnostics,
            *(d for r in result.records for d in r.period.diagnostics),
        ]
        print(
            dumps(
                {
                    "cik": result.cik,
                    "concept": result.concept,
                    "observations": len(result.records),
                    "shown": min(args.limit, len(result.records)),
                    "period_counts": dict(Counter(r.period.kind for r in result.records)),
                    "mode": result.mode,
                    "diagnostic_counts": dict(Counter(d.code for d in diagnostics)),
                    "source_issue_counts": dict(Counter(i.code for i in inspected.source_issues)),
                    "timeline_issue_counts": dict(
                        Counter(i.code for i in inspected.timeline_issues)
                    ),
                    "calendar": {
                        "policy": result.calendar.policy,
                        "year_windows": len(result.calendar.years),
                        "quarter_boundaries": len(result.calendar.quarters),
                        "ambiguous_years": result.calendar.ambiguous_years,
                        "current_year_end_hints": result.calendar.current_year_end_hints,
                        "diagnostics": result.calendar.diagnostics,
                    },
                    "records": [
                        {
                            "observation_id": r.fact.observation_id,
                            "accession": r.fact.observation.accession_number,
                            "form": r.fact.observation.form,
                            "filed": r.fact.observation.filing_date,
                            "fy": r.fact.observation.fiscal_year,
                            "fp": r.fact.observation.fiscal_period,
                            "frame": r.fact.observation.frame,
                            "value": r.fact.observation.value,
                            "unit": r.fact.observation.unit,
                            "filing_report_date": r.fact.filing.report_date
                            if r.fact.filing
                            else None,
                            "source": r.fact.observation.provenance,
                            "period": {
                                "kind": r.period.kind,
                                "start": r.period.start,
                                "end": r.period.end,
                                "duration_days": r.period.duration_days,
                                "method": r.period.method,
                                "status": r.period.status,
                                "identity": r.period.identity,
                                "is_single_quarter": r.period.is_single_quarter,
                                "is_year_to_date": r.period.is_year_to_date,
                                "diagnostics": r.period.diagnostics,
                            },
                        }
                        for r in result.records[: args.limit]
                    ],
                }
            ),
            end="",
        )
        bad = (
            inspected.source_issues
            or inspected.timeline_issues
            or any(d.category == "verified_inconsistency" for d in diagnostics)
            or any(
                d.category == "verified_inconsistency"
                for r in inspected.records
                for d in r.diagnostics
            )
        )
        return 1 if args.strict and bad else 0
    except (FinPanelError, OSError) as exc:
        print(f"finpanel: {exc}", file=sys.stderr)
        return 2


def _asof_command(args: argparse.Namespace) -> int:
    try:
        with SECClient(args.user_agent, cache_dir=args.cache_dir, offline=args.offline) as client:
            view = asof.view(
                args.cik,
                args.as_of,
                concept=args.concept,
                taxonomy=args.taxonomy,
                client=client,
                refresh=args.refresh,
            )
        result = revisions.analyze(view, policy=args.policy) if args.action == "revisions" else view
        if args.output:
            atomic_write(args.output, dumps(result).encode())
        summary = {
            "cik": view.cik,
            "as_of": view.as_of,
            "mode": view.mode,
            "policy": view.policy,
            "eligible_filings": len(view.filings),
            "eligible_observations": len(view.records),
            "excluded_filings": len(view.excluded_filings),
            "excluded_observations": len(view.excluded_observations),
            "excluded_evidence_reasons": dict(Counter(e.reason for e in view.excluded_evidence)),
            "calendar_years": len(view.calendar.years) if view.calendar else 0,
            "diagnostics": view.diagnostics,
            "source_issue_counts": dict(Counter(i.code for i in view.source_issues)),
            "timeline_issue_counts": dict(Counter(i.code for i in view.timeline_issues)),
        }
        conflicts = False
        if args.action == "revisions":
            conflicts = any(g.status == "conflicted" for g in result.groups)
            summary.update(
                {
                    "revision_policy": result.policy,
                    "revision_status": result.status,
                    "groups": len(result.groups),
                    "conflicted_groups": sum(g.status == "conflicted" for g in result.groups),
                    "records": [
                        {
                            "identity": g.identity,
                            "normalized_period": g.normalized_period,
                            "status": g.status,
                            "conflicts": g.conflicts,
                            "selected_observation_ids": g.selected_observation_ids,
                            "candidates": [
                                {
                                    "observation_id": c.observation.fact.observation_id,
                                    "accession": c.observation.fact.observation.accession_number,
                                    "form": c.observation.fact.observation.form,
                                    "value": c.observation.fact.observation.value,
                                    "availability": c.observation.eligibility.source_availability,
                                    "period_kind": c.observation.period.kind,
                                    "is_amendment": c.is_amendment,
                                    "is_comparative": c.is_comparative,
                                    "candidate_status": c.status,
                                    "source": c.observation.fact.observation.provenance,
                                }
                                for c in g.candidates
                            ],
                        }
                        for g in result.groups[: args.limit]
                    ],
                }
            )
        else:
            summary["filings"] = [
                {"accession": f.filing.accession_number, "eligibility": f.eligibility}
                for f in view.filings[: args.limit]
            ]
            summary["records"] = [
                {
                    "observation_id": r.fact.observation_id,
                    "accession": r.fact.observation.accession_number,
                    "eligibility": r.eligibility,
                    "period_kind": r.period.kind,
                    "period_identity": r.period.identity,
                    "period_diagnostics": r.period.diagnostics,
                    "supporting_evidence": len(r.supporting_evidence),
                }
                for r in view.records[: args.limit]
            ]
        print(dumps(summary), end="")
        bad = (
            conflicts
            or view.source_issues
            or view.timeline_issues
            or any(
                d.category == "verified_inconsistency"
                for r in view.records
                for d in (*r.period.diagnostics, *r.fact.diagnostics)
            )
            or (view.calendar and view.calendar.diagnostics)
        )
        return 1 if args.strict and bad else 0
    except (FinPanelError, OSError) as exc:
        print(f"finpanel: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
