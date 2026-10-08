"""Offline four-issuer research workflow. Run from a source checkout, not live SEC.

Fiscal labels for instant dates are explicit researcher inputs below. The raw Assets
observations independently confirm the dates exist; they do not establish a historical
security master. Annual value and arithmetic expectations reuse previously audited
literal goldens, never the panel output. No fixture is edited or fabricated.
"""

import argparse
import runpy
from dataclasses import replace
from pathlib import Path

import duckdb

from finpanel import metrics, panel
from finpanel.serialization import dumps, loads
from finpanel.snapshots import EvidenceStore
from finpanel.snapshots.store import digest
from finpanel.validation.runner import peak_memory

ROOT = Path(__file__).resolve().parents[1]
ISSUERS = {"aapl": "0000320193", "msft": "0000789019", "wmt": "0000104169", "nvda": "0001045810"}
# Ordered Q1/Q2/Q3/FY end dates, chosen from the frozen raw Assets observations.
ENDS = {
    "aapl": {
        2023: ("2022-12-31", "2023-04-01", "2023-07-01", "2023-09-30"),
        2024: ("2023-12-30", "2024-03-30", "2024-06-29", "2024-09-28"),
    },
    "msft": {
        2023: ("2022-09-30", "2022-12-31", "2023-03-31", "2023-06-30"),
        2024: ("2023-09-30", "2023-12-31", "2024-03-31", "2024-06-30"),
    },
    "wmt": {
        2023: ("2022-04-30", "2022-07-31", "2022-10-31", "2023-01-31"),
        2024: ("2023-04-30", "2023-07-31", "2023-10-31", "2024-01-31"),
    },
    "nvda": {
        2023: ("2022-05-01", "2022-07-31", "2022-10-30", "2023-01-29"),
        2024: ("2023-04-30", "2023-07-30", "2023-10-29", "2024-01-28"),
    },
}


def request(snapshot_id):
    ends = [
        panel.PeriodEnd(ISSUERS[issuer], year, period, dates[i])
        for issuer, years in ENDS.items()
        for year, dates in years.items()
        for period, i in [("FY", 3), ("Q1", 0), ("Q2", 1), ("Q3", 2), ("Q4", 3)]
    ]
    return panel.PanelRequest(
        entities=tuple(ISSUERS.values()),
        metrics=tuple(metrics.REGISTRY),
        fiscal_years=(2023, 2024),
        periods=("FY", "Q1", "Q2", "Q3", "Q4"),
        as_of=("2024-08-15T00:00:00Z", "2024-11-15T00:00:00Z"),
        source_policy="reported_then_derived",
        snapshot_id=snapshot_id,
        period_ends=tuple(ends),
        timeline_scope="recent_only",
    )


def raw_at(data, pointer):
    for key in pointer.split("/")[1:]:
        data = data[int(key)] if isinstance(data, list) else data[key]
    return data


def expected_checks(result):
    raw = {
        issuer: loads((ROOT / f"tests/fixtures/sec/{issuer}_companyfacts.json").read_bytes())
        for issuer in ISSUERS
    }
    checks = []

    def check(name, actual, expected):
        checks.append({"case": name, "passed": actual == expected})

    for issuer, years in ENDS.items():
        observed = {r["end"] for r in raw[issuer]["facts"]["us-gaap"]["Assets"]["units"]["USD"]}
        check(
            issuer + "-explicit-end-dates",
            all(d in observed for ds in years.values() for d in ds),
            True,
        )
    lookup = {(r.cik, r.fiscal_year, r.period, r.metric, r.as_of.month): r for r in result.rows}
    golden = loads((ROOT / "tests/golden/canonical.json").read_bytes())["cases"]
    for case in golden[:24]:
        # Existing literals remain the independent expected annual values at Nov 15.
        row = lookup[ISSUERS[case["issuer"]], 2024, "FY", case["metric"], 11]
        state = (
            "resolved_reported" if case["expected_state"] == "resolved" else case["expected_state"]
        )
        check(case["id"], (row.state, row.value), (state, case["expected_value"]))
        for source in case["expected_sources"]:
            check(
                case["id"] + source["pointer"],
                raw_at(raw[case["issuer"]], source["pointer"])["val"],
                source["value"],
            )
    check(
        "reported-quarter",
        (
            lookup[ISSUERS["aapl"], 2024, "Q3", "revenue", 11].state,
            lookup[ISSUERS["aapl"], 2024, "Q3", "revenue", 11].value,
        ),
        ("resolved_reported", 85777000000),
    )
    derivations = loads((ROOT / "tests/golden/derived_quarters.json").read_bytes())[
        "authentic_cases"
    ]
    for case in derivations:
        if case["id"] not in {
            "aapl-operating_cash_flow-Q2-2024",
            "aapl-operating_cash_flow-Q3-2024",
            "aapl-operating_cash_flow-Q4-2024",
            "aapl-revenue-Q4-2024",
        }:
            continue
        row = lookup[ISSUERS[case["issuer"]], 2024, case["quarter"], case["metric"], 11]
        check(case["id"], (row.state, row.value), ("resolved_derived", case["expected_value"]))
        for source in case["minuend_sources"] + case["subtrahend_sources"]:
            check(
                case["id"] + source["pointer"],
                raw_at(raw[case["issuer"]], source["pointer"])["val"],
                source["value"],
            )
    check(
        "before-annual-availability",
        lookup[ISSUERS["aapl"], 2024, "FY", "revenue", 8].state,
        "unavailable",
    )
    check(
        "before-calendar-anchor",
        lookup[ISSUERS["aapl"], 2024, "Q3", "revenue", 8].state,
        "ambiguous_period",
    )
    check("one-pinned-snapshot", {r.snapshot_id for r in result.rows}, {result.request.snapshot_id})
    return checks


def benchmark(destination):
    destination = Path(destination)
    store = EvidenceStore(destination / "evidence")
    snapshot = runpy.run_path(str(ROOT / "examples/validate_snapshots.py"))["import_authentic"](
        store
    )
    result = panel.build(request(snapshot.snapshot_id), store=store)
    performance = dict(result.performance)
    performance["rows"] = len(result.rows)
    # Process high-water mark, not an isolated allocation measurement.
    # Unavailable on Windows; absence is not zero usage or a failed financial audit.
    performance["process_peak_rss_mib"] = peak_memory()
    checks = expected_checks(result)
    round_trips = {}
    for fmt in ("csv", "parquet", "duckdb"):
        path = panel.export(result, destination / ("panel." + fmt))
        round_trips[fmt] = digest(panel.read_export(path)) == result.receipt.semantic["row_hash"]
    with duckdb.connect(str(destination / "panel.duckdb"), read_only=True) as db:
        counts = dict(
            db.execute("SELECT state, count(*) FROM panel_rows GROUP BY state").fetchall()
        )
    replay = panel.reproduce(result.receipt, store=store)
    replay_ok = replay.receipt.receipt_id == result.receipt.receipt_id
    strict = panel.build(
        panel.PanelRequest(
            entities=(ISSUERS["aapl"],),
            metrics=("revenue",),
            fiscal_years=(2024,),
            periods=("FY",),
            as_of=("2024-11-15T00:00:00Z",),
            source_verification="required",
            snapshot_id=snapshot.snapshot_id,
            timeline_scope="recent_only",
        ),
        store=store,
    )
    checks.append(
        {
            "case": "historical-original-source-limitation",
            "passed": strict.rows[0].state == "source_verification_failed"
            and strict.rows[0].value is None,
        }
    )
    best = panel.build(replace(strict.request, source_verification="best_effort"), store=store)
    checks.append(
        {
            "case": "best-effort-preserves-explicit-source-limitation",
            "passed": best.rows[0].value == 391035000000
            and best.rows[0].verification_state != "off",
        }
    )
    selected = next(r for r in result.rows if r.state == "resolved_derived")
    # Compact row inspection; complete canonical objects remain available in memory.
    detail = result.inspect(selected.row_id)
    (destination / "row-inspection.json").write_text(
        dumps({"row": detail["row"], "evidence": detail["evidence"]})
    )
    (destination / "receipt.json").write_text(dumps(result.receipt))
    (destination / "coverage.json").write_text(dumps(result.coverage()))
    report = {
        "population": "AAPL/MSFT/WMT/NVDA; architecture validation, not market-wide accuracy",
        "timeline_scope": "recent_only; missing referenced history is not silently loaded",
        "metrics": sorted(metrics.REGISTRY),
        "fiscal_years": [2023, 2024],
        "as_of": result.request.as_of,
        "requested_cells": len(result.rows),
        "states": result.coverage()["states"],
        "checks": checks,
        "export_round_trips": round_trips,
        "duckdb_counts_match": counts == result.coverage()["states"],
        "replay_cases": 1,
        "successful_replays": int(replay_ok),
        "authentic_artifacts": len(snapshot.manifest["artifacts"]),
        "unexpected_mismatches": sum(not c["passed"] for c in checks)
        + sum(not v for v in round_trips.values())
        + int(not replay_ok)
        + int(counts != result.coverage()["states"]),
    }
    # Wall time / memory stay outside the deterministic validation report and hashes.
    (destination / "validation.json").write_text(dumps(report))
    (destination / "performance.json").write_text(dumps(performance))
    return loads(dumps(report).encode()), performance


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True, help="New local output directory")
    args = parser.parse_args()
    report, performance = benchmark(args.output_dir)
    print(dumps({"validation": report, "performance": performance}))
    raise SystemExit(bool(report["unexpected_mismatches"]))
