"""Offline reproducibility mechanics using intact authentic SEC fixtures."""

import argparse
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from finpanel.models import RawResponse
from finpanel.serialization import dumps, loads
from finpanel.snapshots import EvidenceStore, reproduce, run

ROOT = Path(__file__).resolve().parents[1]


def import_authentic(store):
    artifacts = []
    for name in ("sec", "history", "headers", "xbrl"):
        folder = ROOT / "tests/fixtures" / name
        for filename, meta in loads((folder / "manifest.json").read_bytes())["files"].items():
            raw = RawResponse(
                meta["source_url"],
                (folder / filename).read_bytes(),
                meta["retrieved_at"],
                raw_format=meta.get("raw_format", "json"),
            )
            if raw.sha256 != meta["sha256"]:
                raise ValueError("Authentic raw artifact hash mismatch")
            family = (
                ("companyfacts" if "companyfacts" in filename else "submissions")
                if name == "sec"
                else (
                    "historical_submissions"
                    if name == "history"
                    else "filing_header"
                    if name == "headers"
                    else "xbrl_instance"
                    if meta["document_type"] == "instance"
                    else "filing_directory"
                )
            )
            artifacts.append(
                store.capture(
                    raw,
                    source_family=family,
                    cik=meta["cik"],
                    accession=meta.get("accession"),
                    authenticity="authentic",
                )
            )
    relations = []
    for a in artifacts:
        if a.source_family == "filing_directory":
            for b in artifacts:
                if b.cik == a.cik and b.source_family == "companyfacts":
                    relations.append(
                        {
                            "from": b.capture_id,
                            "to": a.capture_id,
                            "relation": "accession_directory_evidence",
                        }
                    )
        if a.source_family == "xbrl_instance":
            for b in artifacts:
                if b.cik == a.cik and (
                    b.source_family == "companyfacts"
                    or (b.accession == a.accession and b.source_family == "filing_directory")
                ):
                    relations.append(
                        {
                            "from": b.capture_id,
                            "to": a.capture_id,
                            "relation": "accession_source_evidence",
                        }
                    )
    return store.create(
        artifacts,
        scope="existing four-issuer frozen validation evidence",
        relationships=relations,
        incompleteness=("Only supplied frozen artifacts; not complete SEC history",),
    )


def benchmark(root):
    store = EvidenceStore(root)
    a = import_authentic(store)
    cases = [
        dict(
            operation="resolve",
            cik="320193",
            metric="revenue",
            as_of="2024-11-15T00:00:00Z",
            parameters={"fiscal_year": 2024, "period": "FY"},
        ),
        dict(
            operation="derive_quarter",
            cik="320193",
            metric="revenue",
            as_of="2024-11-15T00:00:00Z",
            parameters={"fiscal_year": 2024, "quarter": "Q4"},
        ),
        dict(
            operation="verify_fact",
            cik="320193",
            as_of="2026-10-08T00:00:00Z",
            parameters={
                "accession": "0000320193-24-000069",
                "concept": "Assets",
                "end": "2024-03-30",
            },
        ),
    ]
    expected = [391035000000, 94930000000, 337411000000]
    results = [run(store, snapshot_id=a.snapshot_id, **query) for query in cases]
    mismatch = sum(
        r.reproducibility.semantic["result"]["value"] != v
        for r, v in zip(results, expected, strict=True)
    )
    replays = [reproduce(r.reproducibility, store=store).verified for r in results]
    artifacts = [store._artifact(d) for d in a.manifest["artifacts"]]
    target = next(
        x for x in artifacts if x.source_family == "companyfacts" and x.cik == "0000320193"
    )
    raw = store.raw(target)
    data = raw.json()
    # Explicit SYNTHETIC correction of one authentic aggregate field, not an SEC event.
    rows = data["facts"]["us-gaap"]["RevenueFromContractWithCustomerExcludingAssessedTax"]["units"][
        "USD"
    ]
    for row in rows:
        if row.get("start") == "2023-10-01" and row["end"] == "2024-09-28":
            row["val"] += 1
    changed = replace(raw, body=dumps(data).encode(), retrieved_at="2026-11-01T00:00:00Z")
    later = store.capture(
        changed, source_family="companyfacts", cik=target.cik, authenticity="synthetic"
    )
    b = store.create(
        [later if x == target else x for x in artifacts],
        scope=a.manifest["scope"],
        notes=("Controlled synthetic aggregate correction; not observed at SEC",),
        incompleteness=a.manifest["incompleteness"],
    )
    old_again = run(store, snapshot_id=a.snapshot_id, **cases[0])
    new = run(store, snapshot_id=b.snapshot_id, **cases[0])
    pinned = old_again.reproducibility.receipt_id == results[0].reproducibility.receipt_id
    changed_result = new.reproducibility.semantic["result"]["value"] == expected[0] + 1
    # Independent corruption check uses a temporary self-contained export.
    from finpanel.snapshots import export_bundle

    export_bundle(
        results[0].reproducibility,
        store=store,
        destination=Path(root) / "corruption",
        include_raw=True,
    )
    corrupt = EvidenceStore(Path(root) / "corruption")
    (corrupt.root / target.locator).write_bytes(b"controlled corruption")
    detected = not reproduce(results[0].reproducibility, store=corrupt).verified
    return {
        "population": (
            "Existing authentic fixtures plus one explicitly synthetic aggregate correction; "
            "reproducibility mechanics only"
        ),
        "snapshots": 2,
        "authentic_source_artifacts": len(artifacts),
        "source_capture_records": len(artifacts) + 1,
        "deduplicated_objects": len(list((store.root / "objects").iterdir())),
        "manifest_verification": all(store.verify(s.snapshot_id).valid for s in (a, b)),
        "replay_cases": len(replays),
        "successful_replays": sum(replays),
        "corruption_detected": detected,
        "pinned_old_unchanged": pinned,
        "same_as_of_new_snapshot_changed": changed_result,
        "unexpected_mismatches": mismatch
        + sum(not x for x in replays)
        + int(not pinned)
        + int(not changed_result)
        + int(not detected),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with TemporaryDirectory() as folder:
        report = benchmark(folder)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(dumps(report))
    print(dumps(report))
    raise SystemExit(bool(report["unexpected_mismatches"]))
