"""Explicit larger-universe workflow; acquisition is separate from offline validation.

First acquire: finpanel validate acquire output/wp6-corpus
Optional originals: finpanel validate acquire output/wp6-corpus --originals
Then run this script with the resulting snapshot ID. Never use live SEC in CI.
"""

import argparse
from pathlib import Path

import duckdb

from finpanel.serialization import dumps
from finpanel.snapshots import EvidenceStore
from finpanel.validation.runner import run

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    report, receipt, performance = run(
        EvidenceStore(args.store), args.snapshot, args.output, limit=args.limit
    )
    # Parquet is already published per issuer/policy, with metadata and provenance.
    # Portable SQL analysis keeps exact monetary text + value_kind, not DOUBLE.
    with duckdb.connect(str(args.output / "research.duckdb")) as db:
        paths = [str(p) for p in sorted(args.output.glob("*/*/panel.parquet"))]
        db.execute("CREATE TABLE panel_rows AS SELECT * FROM read_parquet(?)", [paths])
        db.execute("CREATE VIEW resolved AS SELECT * FROM panel_rows WHERE state LIKE 'resolved_%'")
        db.execute(
            "CREATE VIEW unresolved AS SELECT * FROM panel_rows WHERE state NOT LIKE 'resolved_%'"
        )
        db.execute("CREATE TABLE benchmark_receipt (receipt_json VARCHAR)")
        db.execute("INSERT INTO benchmark_receipt VALUES (?)", [dumps(receipt)])
        print(
            db.execute(
                "SELECT state, count(*) FROM panel_rows GROUP BY state ORDER BY state"
            ).fetchall()
        )
        print(db.execute("SELECT cik, metric, period, reasons FROM unresolved LIMIT 10").fetchall())
    print(dumps({"report": report, "performance": performance}))
    raise SystemExit(bool(report["unexpected_mismatches"]))
