"""Synthetic pipeline replay and controlled aggregate correction scenarios."""

from dataclasses import replace

import pytest
from test_derivation_scope import annual_records
from test_metric_candidates import report

from finpanel import metrics
from finpanel.models import RawResponse
from finpanel.serialization import dumps, loads
from finpanel.snapshots import EvidenceStore, SnapshotError, export_bundle, reproduce, run
from finpanel.snapshots.store import digest


def sources(value=100, retrieved="2026-01-01T00:00:00Z"):
    rows = []
    acc = []
    ends = []
    for i, (fp, end, v) in enumerate(
        [("Q1", "2021-03-31", value), ("Q2", "2021-06-30", 250), ("FY", "2021-12-31", 600)], 1
    ):
        accession = f"0000000001-22-{i:06d}"
        rows.append(
            {
                "start": "2021-01-01",
                "end": end,
                "val": v,
                "accn": accession,
                "fy": 2021,
                "fp": fp,
                "form": "10-K" if fp == "FY" else "10-Q",
                "filed": "2022-02-01",
            }
        )
        acc.append(accession)
        ends.append(end)
    return [
        RawResponse(
            "https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json",
            dumps(
                {"cik": 1, "facts": {"us-gaap": {"Revenues": {"units": {"USD": rows}}}}}
            ).encode(),
            retrieved,
        ),
        RawResponse(
            "https://data.sec.gov/submissions/CIK0000000001.json",
            dumps(
                {
                    "cik": 1,
                    "filings": {
                        "recent": {
                            "accessionNumber": acc,
                            "reportDate": ends,
                            "form": ["10-Q", "10-Q", "10-K"],
                            "filingDate": ["2022-02-01"] * 3,
                            "acceptanceDateTime": ["2022-02-01T15:00:00Z"] * 3,
                        }
                    },
                }
            ).encode(),
            retrieved,
        ),
    ]


def snapshot(store, value=100, retrieved="2026-01-01T00:00:00Z"):
    artifacts = [
        store.capture(raw, source_family=family, cik="0000000001", authenticity="synthetic")
        for raw, family in zip(
            sources(value, retrieved), ("companyfacts", "submissions"), strict=True
        )
    ]
    return store.create(artifacts, scope="synthetic three filings")


def query(store, sid, **kwargs):
    return run(
        store,
        snapshot_id=sid,
        operation="resolve",
        cik=1,
        metric="revenue",
        as_of=kwargs.pop("as_of", "2023-01-01T00:00:00Z"),
        parameters={"fiscal_year": 2021, "period": "Q1"},
        **kwargs,
    )


def test_pinned_old_new_and_time_axes(tmp_path):
    s = EvidenceStore(tmp_path)
    a = snapshot(s)
    first = query(s, a.snapshot_id)
    b = snapshot(s, 101, "2026-02-01T00:00:00Z")
    assert first.result.value == query(s, a.snapshot_id).result.value == 100
    assert query(s, b.snapshot_id).result.value == 101
    assert reproduce(first.reproducibility, store=s).verified
    assert first.reproducibility.semantic["captured_through"].startswith("2026")
    assert first.reproducibility.semantic["query"]["as_of"].startswith("2023")
    assert query(s, a.snapshot_id, as_of="2021-01-01T00:00:00Z").result.value is None


def test_semantic_hash_excludes_execution_time(tmp_path):
    s = EvidenceStore(tmp_path)
    a = snapshot(s)
    x = query(s, a.snapshot_id, executed_at="2026-03-01T00:00:00Z")
    y = query(s, a.snapshot_id, executed_at="2026-04-01T00:00:00Z")
    assert x.reproducibility.receipt_id == y.reproducibility.receipt_id
    assert x.reproducibility.executed_at != y.reproducibility.executed_at


def test_derived_one_snapshot_no_external_operands(tmp_path):
    s = EvidenceStore(tmp_path)
    a = snapshot(s)
    result = run(
        s,
        snapshot_id=a.snapshot_id,
        operation="derive_quarter",
        cik=1,
        metric="revenue",
        as_of="2023-01-01T00:00:00Z",
        parameters={"fiscal_year": 2021, "quarter": "Q2"},
    )
    assert result.result.value == 150
    assert result.operand_snapshot_ids == (a.snapshot_id, a.snapshot_id)
    assert reproduce(result.reproducibility, store=s).verified
    with pytest.raises(SnapshotError):
        run(
            s,
            snapshot_id=a.snapshot_id,
            operation="derive_quarter",
            cik=1,
            metric="revenue",
            as_of="2023-01-01T00:00:00Z",
            parameters={"minuend": "foreign"},
        )


@pytest.mark.parametrize(
    "failure",
    ["missing_snapshot", "missing_object", "corrupt", "manifest", "format", "contract", "result"],
)
def test_replay_explicit_failure(tmp_path, failure):
    s = EvidenceStore(tmp_path)
    a = snapshot(s)
    receipt = query(s, a.snapshot_id).reproducibility
    path = tmp_path / "snapshots" / (a.snapshot_id + ".json")
    if failure == "missing_snapshot":
        path.unlink()
    if failure == "missing_object":
        next((tmp_path / "objects").iterdir()).unlink()
    if failure == "corrupt":
        next((tmp_path / "objects").iterdir()).write_bytes(b"bad")
    if failure in {"manifest", "format"}:
        data = loads(path.read_bytes())
        data["scope"] = "changed"
        if failure == "format":
            data["format"] = "unsupported"
        path.write_text(dumps(data))
    if failure in {"contract", "result"}:
        semantic = loads(dumps(receipt.semantic).encode())
        if failure == "contract":
            semantic["contracts"]["canonical"] = "wrong"
        else:
            semantic["result"]["value"] = 123
        receipt = replace(receipt, semantic=semantic, receipt_id=digest(semantic))
    replay = reproduce(receipt, store=s)
    assert not replay.verified and replay.reason


def test_bundle_self_contained_and_manifest_only(tmp_path):
    s = EvidenceStore(tmp_path / "store")
    a = snapshot(s)
    receipt = query(s, a.snapshot_id).reproducibility
    export_bundle(receipt, store=s, destination=tmp_path / "full", include_raw=True)
    assert reproduce(receipt, store=EvidenceStore(tmp_path / "full")).verified
    export_bundle(receipt, store=s, destination=tmp_path / "metadata")
    assert not reproduce(receipt, store=EvidenceStore(tmp_path / "metadata")).verified
    assert loads((tmp_path / "metadata/bundle.json").read_bytes())["kind"] == "manifest-only bundle"


def test_legacy_default_is_explicitly_unsnapshotted():
    r = metrics.resolve_candidates(report(*annual_records()), fiscal_year=2021, period="Q1")
    assert r.value == 100 and r.evidence_mode == "unsnapshotted_explicit_inputs"


def test_receipt_unknown_software_is_not_recreated(tmp_path):
    s = EvidenceStore(tmp_path)
    a = snapshot(s)
    receipt = query(s, a.snapshot_id).reproducibility
    semantic = loads(dumps(receipt.semantic).encode())
    semantic["software"]["code_sha256"] = "different"
    changed = replace(receipt, semantic=semantic, receipt_id=digest(semantic))
    assert "Incompatible software" in reproduce(changed, store=s).reason


def test_query_default_and_explicit_revision_policy_have_same_receipt(tmp_path):
    s = EvidenceStore(tmp_path)
    a = snapshot(s)
    first = query(s, a.snapshot_id)
    other = run(
        s,
        snapshot_id=a.snapshot_id,
        operation="resolve",
        cik="0000000001",
        metric="revenue",
        as_of="2023-01-01T00:00:00+00:00",
        parameters={"fiscal_year": 2021, "period": "Q1", "revision_policy": "latest_available"},
    )
    assert first.reproducibility.receipt_id == other.reproducibility.receipt_id


def test_post_acceptance_correction_preserves_both_captures(tmp_path):
    s = EvidenceStore(tmp_path)
    a = snapshot(s, 100)
    b = snapshot(s, 999, "2026-02-01T00:00:00Z")
    av = next(x for x in a.manifest["artifacts"] if x["source_family"] == "companyfacts")
    bv = next(x for x in b.manifest["artifacts"] if x["source_family"] == "companyfacts")
    assert av["sha256"] != bv["sha256"] and a.snapshot_id != b.snapshot_id
    assert (
        query(s, a.snapshot_id).result.selected[0].observation.fact.observation.filing_date
        == query(s, b.snapshot_id).result.selected[0].observation.fact.observation.filing_date
    )


def test_required_source_mode_cannot_substitute_missing_instances(tmp_path):
    s = EvidenceStore(tmp_path)
    a = snapshot(s)
    result = query(s, a.snapshot_id, source_verification="required")
    assert result.result.value is None
    assert result.reproducibility.semantic["source_limitations"]
    assert reproduce(result.reproducibility, store=s).verified


def test_wrong_source_family_is_not_substituted(tmp_path):
    s = EvidenceStore(tmp_path)
    a = s.create(
        [
            s.capture(raw, source_family="bulk_archive", authenticity="synthetic")
            for raw in sources()
        ],
        scope="wrong family",
    )
    with pytest.raises(SnapshotError, match="Source family"):
        query(s, a.snapshot_id)


def test_malformed_receipt_is_explicit_failure(tmp_path):
    from finpanel.snapshots import Receipt, read_receipt

    receipt = Receipt(digest(1), 1, "2026-01-01T00:00:00Z")
    assert not reproduce(receipt, store=EvidenceStore(tmp_path)).verified
    path = tmp_path / "receipt.json"
    path.write_text(dumps(receipt))
    with pytest.raises(SnapshotError):
        read_receipt(path)
