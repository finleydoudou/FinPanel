import csv
from dataclasses import replace
from decimal import Decimal

import pytest
from test_panel_contract import request
from test_panel_engine import pinned
from test_snapshots_pipeline import sources

from finpanel import panel
from finpanel.errors import ValidationError
from finpanel.panel.engine import row_record
from finpanel.panel.export import COLUMNS
from finpanel.serialization import loads
from finpanel.snapshots import EvidenceStore
from finpanel.snapshots.store import digest


@pytest.mark.parametrize("fmt", ["csv", "parquet", "duckdb"])
def test_round_trip_rows_states_metadata_and_receipts(tmp_path, fmt):
    store, req = pinned(tmp_path / "store")
    result = panel.build(req, store=store)
    path = panel.export(result, tmp_path / ("panel." + fmt))
    read = panel.read_export(path)
    assert digest(read) == result.receipt.semantic["row_hash"]
    assert [r["state"] for r in read] == [r.state for r in result.rows]
    assert read[-1]["value"] is None
    meta = loads(path.with_name(path.name + ".metadata.json").read_bytes())
    assert meta["row_count"] == 4 and meta["receipt"]["receipt_id"] == result.receipt.receipt_id
    with pytest.raises(ValidationError):
        panel.export(result, path)
    if fmt == "parquet":
        import pyarrow.parquet as pq

        assert str(pq.read_schema(path).field("value").type) == "string"
        assert str(pq.read_schema(path).field("period_end").type) == "date32[day]"
    if fmt == "duckdb":
        import duckdb

        with duckdb.connect(str(path), read_only=True) as db:
            assert db.execute("SELECT count(*) FROM diagnostics").fetchone()[0] == 4
            assert db.execute("SELECT count(*) FROM provenance").fetchone()[0] == 4
            assert db.execute("SELECT count(*) FROM resolved_rows").fetchone()[0] == 3


@pytest.mark.parametrize(
    "value",
    [
        10**50 + 1,
        Decimal("123456789012345678901234567890.000000000012300"),
        Decimal("-0.000"),
        Decimal("1E+50"),
    ],
)
@pytest.mark.parametrize("fmt", ["csv", "parquet", "duckdb"])
def test_exact_numeric_roundtrip(tmp_path, value, fmt):
    store = EvidenceStore(tmp_path / "store")
    raws = sources(value)
    # Preserve type/scale from literal SEC-style JSON fixture in the canonical engine.
    snap = store.create(
        [
            store.capture(raw, source_family=f, cik=1, authenticity="synthetic")
            for raw, f in zip(raws, ("companyfacts", "submissions"), strict=True)
        ],
        scope="exact",
    )
    r = panel.build(
        request(fiscal_years=[2021], periods=["Q1"], snapshot_id=snap.snapshot_id), store=store
    )
    row = r.rows[0]
    assert row.value == value
    read = panel.read_export(panel.export(r, tmp_path / ("exact." + fmt)))[0]
    assert read["value"] == str(row.value)
    assert read["value_kind"] == ("decimal" if isinstance(row.value, Decimal) else "integer")


def test_csv_bytes_schema_null_and_tamper(tmp_path):
    store, req = pinned(tmp_path / "store")
    a, b = panel.build(req, store=store), panel.build(req, store=store)
    p = panel.export(a, tmp_path / "a.csv")
    q = panel.export(b, tmp_path / "b.csv")
    assert p.read_bytes() == q.read_bytes()
    with p.open() as f:
        assert next(csv.reader(f)) == list(COLUMNS)
    assert "\\N" in p.read_text()
    p.write_text(p.read_text().replace("resolved_reported", "unavailable"))
    with pytest.raises(ValidationError, match="hash"):
        panel.read_export(p)


def test_literal_null_marker_in_metadata(tmp_path):
    store, req = pinned(tmp_path / "store")
    r = panel.build(req, store=store)
    rows = tuple(replace(x, entity_name="\\N", ticker="\\literal") for x in r.rows)
    semantic = dict(r.receipt.semantic, row_hash=digest([row_record(x) for x in rows]))
    r = replace(
        r, rows=rows, receipt=replace(r.receipt, semantic=semantic, receipt_id=digest(semantic))
    )
    read = panel.read_export(panel.export(r, tmp_path / "escape.csv"))
    assert read[0]["entity_name"] == "\\N" and read[0]["ticker"] == "\\literal"


@pytest.mark.parametrize("sidecar", ["metadata", "provenance"])
def test_export_audit_tampering_detected(tmp_path, sidecar):
    store, req = pinned(tmp_path / "store")
    r = panel.build(req, store=store)
    path = panel.export(r, tmp_path / "tamper.parquet")
    target = path.with_name(path.name + "." + sidecar + ".json")
    text = target.read_text()
    target.write_text(text.replace("latest_available", "first_reported"))
    with pytest.raises(ValidationError, match="hash"):
        panel.read_export(path)


def test_export_publication_failure_preserves_existing_and_cleans_own_files(tmp_path, monkeypatch):
    from importlib import import_module

    module = import_module("finpanel.panel.export")
    store, req = pinned(tmp_path / "store")
    r = panel.build(req, store=store)
    path = tmp_path / "race.csv"
    original = module.os.link
    calls = []

    def race(source, target):
        calls.append(target)
        if len(calls) == 2:
            target.write_text("another writer")
        return original(source, target)

    monkeypatch.setattr(module.os, "link", race)
    with pytest.raises(FileExistsError):
        panel.export(r, path)
    assert not path.exists()
    assert path.with_name(path.name + ".metadata.json").read_text() == "another writer"
    assert not list(tmp_path.glob(".finpanel-export-*"))
