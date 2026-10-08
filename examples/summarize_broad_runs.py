"""Consolidate disjoint, verified offline benchmark shards without dropping cells."""

import argparse
from collections import Counter
from datetime import date
from pathlib import Path

from finpanel.errors import ValidationError
from finpanel.serialization import dumps, loads
from finpanel.snapshots import EvidenceStore
from finpanel.snapshots.pipeline import software_identity
from finpanel.snapshots.store import digest
from finpanel.validation.checkpoints import Checkpoint
from finpanel.validation.runner import coverage_breakdown
from finpanel.validation.universe import selection, universe_hash


def require(condition, message):
    if not condition:
        raise ValidationError(message)


def calendar_cohorts(store, snapshot, cells, cutoff):
    """Descriptive raw-context cohorts; never an input to historical resolution."""
    groups = {}
    evidence = []
    cutoff_day = date.fromisoformat(cutoff[:10])
    for artifact in snapshot.manifest["artifacts"]:
        if artifact["source_family"] != "companyfacts":
            continue
        cik = artifact["cik"]
        raw = store.raw(store._artifact(artifact)).json()["facts"].get("us-gaap", {})
        windows = set()
        for concept in ("NetIncomeLoss", "NetCashProvidedByUsedInOperatingActivities"):
            for row in raw.get(concept, {}).get("units", {}).get("USD", []):
                if (
                    not row.get("start")
                    or row.get("form") not in {"10-K", "10-K/A"}
                    or row.get("fp") != "FY"
                    or not row.get("filed")
                ):
                    continue
                start, end = date.fromisoformat(row["start"]), date.fromisoformat(row["end"])
                days = (end - start).days + 1
                if (
                    date(2022, 1, 1) <= end < cutoff_day
                    and date.fromisoformat(row["filed"]) < cutoff_day
                    and 350 <= days <= 378
                ):
                    windows.add((start.isoformat(), end.isoformat(), days))
        lengths = {w[2] for w in windows}
        cohort = (
            "53_week_observed"
            if 371 in lengths
            else "52_week_observed"
            if 364 in lengths
            else "unknown_annual_context"
            if not windows
            else "calendar_year"
            if all(w[1].endswith("12-31") for w in windows)
            else "noncalendar_annual"
        )
        groups[cik] = cohort
        evidence.append(
            dict(cik=cik, cohort=cohort, source_sha256=artifact["sha256"], windows=sorted(windows))
        )
    buckets = {}
    for row in cells:
        counts = buckets.setdefault(groups[row["cik"]], Counter())
        counts[row["state"]] += 1
    return dict(
        method=(
            "Retrospective descriptive cohorts from raw annual-duration contexts "
            "ending in the benchmark era and filed before the final cutoff; "
            "not fiscal labels or accuracy claims."
        ),
        states={k: dict(v) for k, v in sorted(buckets.items())},
        evidence=evidence,
    )


def summarize(folders, store, manifest):
    reports, receipts, performance, cells = [], [], [], []
    seen = set()
    common = None
    for folder in folders:
        folder = Path(folder)
        saved = loads((folder / "checkpoint.json").read_bytes())
        job = saved["job"]
        Checkpoint(folder, None, job, resume=True)
        identity = {k: v for k, v in job.items() if k != "issuers"}
        if common is None:
            common = identity
            snapshot = store.select(snapshot_id=job["snapshot_id"])
            require(
                digest(snapshot.manifest) == job["source_manifest_hash"], "Snapshot hash mismatch"
            )
        require(
            identity == common and job["software"] == software_identity(), "Incompatible shards"
        )
        require(job["universe_hash"] == universe_hash(manifest), "Universe mismatch")
        require(not seen.intersection(job["issuers"]), "Overlapping shards")
        require(set(saved["completed"]) == set(job["issuers"]), "Incomplete shard")
        seen.update(job["issuers"])
        report = loads((folder / "report.json").read_bytes())
        receipt = loads((folder / "receipt.json").read_bytes())
        require(digest(report) == receipt["report_hash"], "Report hash mismatch")
        require(receipt["job_id"] == saved["job_id"], "Job mismatch")
        require(
            digest(saved["state"]["cells"]) == receipt["semantic_dataset_hash"], "Row hash mismatch"
        )
        reports.append(report)
        receipts.append(receipt)
        performance.append(loads((folder / "performance.json").read_bytes()))
        cells.extend(saved["state"]["cells"])
    issuers = [i for i in selection(manifest) if i["cik"] in seen]
    require(seen == {i["cik"] for i in selection(manifest)}, "Incomplete universe")
    cells.sort(
        key=lambda r: (
            r["cik"],
            r["revision_policy"],
            r["as_of"],
            r["fiscal_year"],
            r["period"],
            r["metric"],
        )
    )
    counters = {}
    for name in (
        "states",
        "findings_by_kind",
        "failure_categories",
        "source_verification_states",
        "category_distribution",
    ):
        counts = Counter()
        for report in reports:
            counts.update(report[name])
        counters[name] = dict(sorted(counts.items()))
    totals = {
        name: sum(r[name] for r in reports)
        for name in (
            "requested_cells",
            "observed_cells",
            "invariant_checks",
            "successful_replays",
            "unexpected_mismatches",
            "source_verification_queries",
        )
    }
    return dict(
        format="finpanel-release-scale-summary-v1",
        snapshot_id=common["snapshot_id"],
        universe_hash=common["universe_hash"],
        software=common["software"],
        query=common["query"],
        issuer_count=len(seen),
        category_count=len(counters["category_distribution"]),
        **totals,
        **counters,
        coverage_by=coverage_breakdown(cells, issuers),
        observed_calendar_cohorts=calendar_cohorts(
            store, snapshot, cells, max(common["query"]["as_of"])
        ),
        semantic_dataset_hash=digest(cells),
        shards=[
            dict(
                job_id=r["job_id"],
                report_hash=r["report_hash"],
                semantic_dataset_hash=r["semantic_dataset_hash"],
            )
            for r in receipts
        ],
        measurements=performance,
        timing_context=(
            "Two independent serial jobs ran concurrently, alongside regression and "
            "mutation checks; shard wall times are not an isolated speed benchmark."
        ),
        coverage_meaning=(
            "Scalar availability in this purposive population, "
            "not correctness or market-wide accuracy."
        ),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folders", type=Path, nargs="+")
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--universe", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = summarize(args.folders, EvidenceStore(args.store), loads(args.universe.read_bytes()))
    args.output.write_text(dumps(report), encoding="utf-8")
    print(
        dumps(
            {
                k: report[k]
                for k in (
                    "issuer_count",
                    "observed_cells",
                    "invariant_checks",
                    "successful_replays",
                    "unexpected_mismatches",
                )
            }
        )
    )
    raise SystemExit(bool(report["unexpected_mismatches"]))


if __name__ == "__main__":
    main()
