"""Authentic fixture import and explicit synthetic changes; never live SEC access."""

import runpy
from dataclasses import replace
from pathlib import Path

import pytest

from finpanel import metrics
from finpanel.errors import ValidationError
from finpanel.snapshots import EvidenceStore, reproduce, run

MODULE = runpy.run_path(str(Path(__file__).resolve().parents[1] / "examples/validate_snapshots.py"))


@pytest.fixture(scope="module")
def frozen(tmp_path_factory):
    store = EvidenceStore(tmp_path_factory.mktemp("versioned-authentic"))
    return store, MODULE["import_authentic"](store)


def test_import_preserves_all_raw_authentic_hashes(frozen):
    store, snapshot = frozen
    assert len(snapshot.manifest["artifacts"]) == 25
    assert snapshot.manifest["completeness"] == "partial"
    assert snapshot.manifest["relationships"]
    assert store.verify(snapshot.snapshot_id).valid
    assert all(a["authenticity"] == "authentic" for a in snapshot.manifest["artifacts"])


def test_pinned_original_instance_and_future_retrieval(frozen):
    store, snapshot = frozen
    query = dict(
        operation="verify_fact",
        cik="320193",
        as_of="2026-10-08T00:00:00Z",
        parameters={"accession": "0000320193-24-000069", "concept": "Assets", "end": "2024-03-30"},
    )
    first = run(store, snapshot_id=snapshot.snapshot_id, **query)
    assert first.result.state == "verified_unique"
    assert first.result.evidence_snapshot_id == snapshot.snapshot_id
    artifacts = [store._artifact(d) for d in snapshot.manifest["artifacts"]]
    instance = next(
        a
        for a in artifacts
        if a.source_family == "xbrl_instance" and a.accession == "0000320193-24-000069"
    )
    raw = store.raw(instance)
    later = store.capture(
        replace(raw, body=raw.body + b"\n", retrieved_at="2026-11-01T00:00:00Z"),
        source_family="xbrl_instance",
        cik=instance.cik,
        accession=instance.accession,
        authenticity="synthetic",
    )
    changed = store.create(
        [later if a == instance else a for a in artifacts], scope="controlled later XBRL"
    )
    assert (
        run(store, snapshot_id=changed.snapshot_id, **query).result.state == "instance_unavailable"
    )
    again = run(store, snapshot_id=snapshot.snapshot_id, **query)
    assert first.reproducibility.receipt_id == again.reproducibility.receipt_id
    assert reproduce(first.reproducibility, store=store).verified


def test_authentic_metric_and_derived_same_snapshot(frozen):
    store, snapshot = frozen
    query = dict(cik="320193", metric="revenue", as_of="2024-11-15T00:00:00Z")
    a = run(
        store,
        snapshot_id=snapshot.snapshot_id,
        operation="resolve",
        parameters={"fiscal_year": 2024, "period": "FY"},
        **query,
    )
    d = run(
        store,
        snapshot_id=snapshot.snapshot_id,
        operation="derive_quarter",
        parameters={"fiscal_year": 2024, "quarter": "Q4"},
        **query,
    )
    assert a.result.value == 391035000000 and d.result.value == 94930000000
    assert (
        d.result.minuend.evidence_snapshot_id
        == d.result.subtrahend.evidence_snapshot_id
        == snapshot.snapshot_id
    )
    with pytest.raises(ValidationError, match="same evidence snapshot"):
        metrics.derive_operands(
            d.result.minuend,
            replace(d.result.subtrahend, evidence_snapshot_id="foreign"),
            fiscal_year=2024,
            quarter="Q4",
        )
    same = metrics.derive_operands(
        d.result.minuend, d.result.subtrahend, fiscal_year=2024, quarter="Q4"
    )
    assert same.value == d.result.value and same.evidence_snapshot_id == snapshot.snapshot_id


def test_capture_time_does_not_admit_future_facts_or_calendar(frozen):
    store, snapshot = frozen
    query = dict(
        cik="320193",
        metric="revenue",
        operation="resolve",
        parameters={"fiscal_year": 2024, "period": "FY"},
    )
    early = run(store, snapshot_id=snapshot.snapshot_id, as_of="2024-01-01T00:00:00Z", **query)
    late = run(store, snapshot_id=snapshot.snapshot_id, as_of="2024-11-15T00:00:00Z", **query)
    assert early.result.value is None and late.result.value == 391035000000
    assert (
        early.reproducibility.semantic["captured_through"]
        == late.reproducibility.semantic["captured_through"]
    )


def test_benchmark(tmp_path):
    result = MODULE["benchmark"](tmp_path)
    assert result["unexpected_mismatches"] == 0
    assert result["snapshots"] == 2 and result["successful_replays"] == 3
    assert result["corruption_detected"] and result["pinned_old_unchanged"]
