"""Offline future-observation mutations over a declared validation universe.

Mutated records are synthetic in-memory transformations, never authentic fixtures.
Absence of a future observation is reported as unexercised, not a passing mutation.
"""

import argparse
from dataclasses import replace
from datetime import date
from pathlib import Path

from finpanel import asof, facts, revisions
from finpanel.sec.client import SECClient
from finpanel.serialization import dumps, loads
from finpanel.snapshots import EvidenceStore
from finpanel.snapshots.pipeline import _PinnedCache
from finpanel.snapshots.store import digest
from finpanel.validation.universe import selection


def audit_issuer(store, snapshot, cik, cutoff="2024-08-15T00:00:00Z"):
    day = date.fromisoformat(cutoff[:10])
    for concept in ("NetIncomeLoss", "NetCashProvidedByUsedInOperatingActivities"):
        with SECClient(cache=_PinnedCache(store, snapshot), offline=True) as client:
            original = facts.for_concept(cik, concept, taxonomy="us-gaap", client=client)
        count = sum(
            bool(r.observation.filing_date and r.observation.filing_date > day)
            for r in original.records
        )
        if not count:
            continue
        altered = replace(
            original,
            records=tuple(
                replace(r, observation=replace(r.observation, value=999999999999, fiscal_year=1900))
                if r.observation.filing_date and r.observation.filing_date > day
                else r
                for r in original.records
            ),
        )
        before, after = (asof.from_inspection(i, cutoff) for i in (original, altered))
        checks = dict(
            records=digest(before.records) == digest(after.records),
            calendar=digest(before.calendar) == digest(after.calendar),
        )
        for policy in ("first_reported", "latest_available", "all_available"):
            checks[policy] = digest(revisions.analyze(before, policy=policy).groups) == digest(
                revisions.analyze(after, policy=policy).groups
            )
        return dict(
            cik=cik,
            concept=concept,
            cutoff=cutoff,
            mutated_future_observations=count,
            checks=len(checks),
            outcomes=checks,
            passed=all(checks.values()),
            exercised=True,
        )
    return dict(
        cik=cik,
        checks=0,
        mutated_future_observations=0,
        passed=None,
        exercised=False,
        reason="no_future_observations_for_declared_duration_concepts",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--universe", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    store = EvidenceStore(args.store)
    snapshot = store.select(snapshot_id=args.snapshot)
    manifest = loads(args.universe.read_bytes())
    results = [audit_issuer(store, snapshot, i["cik"]) for i in selection(manifest)]
    report = dict(
        snapshot_id=snapshot.snapshot_id,
        universe_hash=digest(manifest),
        issuer_count=len(results),
        checks=sum(r["checks"] for r in results),
        failed=sum(r["passed"] is False for r in results),
        unexercised=sum(not r["exercised"] for r in results),
        results=results,
    )
    args.output.write_text(dumps(report), encoding="utf-8")
    print(dumps({k: v for k, v in report.items() if k != "results"}))
    raise SystemExit(bool(report["failed"]))


if __name__ == "__main__":
    main()
