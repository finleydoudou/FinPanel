"""Portable, deterministic long-form exports with reversible exact-value strings."""

import csv
import os
from dataclasses import fields
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from finpanel.errors import ValidationError
from finpanel.panel.engine import row_record
from finpanel.panel.models import SCHEMA, PanelRow
from finpanel.serialization import dumps, loads
from finpanel.snapshots.store import digest

COLUMNS = tuple(f.name for f in fields(PanelRow)) + ("value_kind",)
JSON_COLUMNS = {
    "source_concepts",
    "source_taxonomies",
    "accessions",
    "filing_availability",
    "reasons",
    "conflicts",
}
DATE_COLUMNS = {"period_start", "period_end"}
NULL = "\\N"


def records(result):
    """Flat records; JSON fields are explicit reversible strings in all three formats."""
    output = []
    for row in result.rows:
        record = row_record(row)
        for name in JSON_COLUMNS:
            record[name] = dumps({"items": record[name]}).strip()
        output.append(record)
    return output


def decode(record):
    """Decode a read-back flat export record to the canonical semantic representation."""
    record = dict(record)
    for name in JSON_COLUMNS:
        record[name] = loads(record[name].encode())["items"]
    for name in DATE_COLUMNS:
        if isinstance(record[name], str):
            record[name] = date.fromisoformat(record[name])
    if isinstance(record["as_of"], str):
        record["as_of"] = datetime.fromisoformat(record["as_of"])
    record["as_of"] = record["as_of"].astimezone(UTC)
    record["fiscal_year"] = int(record["fiscal_year"])
    if record["value"] is not None:
        constructor = {"integer": int, "decimal": Decimal}.get(record["value_kind"])
        if constructor is None:
            raise ValidationError("Unknown exported exact-value kind")
        value = constructor(record["value"])
        record["value"] = str(value)
    elif record["value_kind"] is not None:
        raise ValidationError("Null value has a number kind")
    return record


def metadata(result):
    coverage = result.coverage()
    return {
        "schema": SCHEMA,
        "request": result.request,
        "finpanel_version": result.receipt.semantic["software"]["finpanel"],
        "evidence_mode": result.receipt.semantic["evidence_mode"],
        "snapshot_id": result.request.snapshot_id,
        "receipt": result.receipt,
        "semantic_dataset_hash": result.receipt.semantic["row_hash"],
        "row_count": len(result.rows),
        "result_state_counts": coverage["states"],
        "issuer_count": len(result.request.entities),
        "metric_count": len(result.request.metrics),
        "as_of": result.request.as_of,
        "created_at": result.receipt.created_at,
        "value_representation": "base-10 text plus integer/decimal kind; never float",
        "csv_null": NULL,
        "columns": COLUMNS,
        "entity_metadata": "Names/tickers describe supplied evidence, not historical identity",
    }


def _arrow(result):
    import pyarrow as pa

    schema = pa.schema(
        [
            (
                c,
                pa.int32()
                if c == "fiscal_year"
                else pa.date32()
                if c in DATE_COLUMNS
                else pa.timestamp("us", tz="UTC")
                if c == "as_of"
                else pa.string(),
            )
            for c in COLUMNS
        ],
        metadata={
            b"finpanel_schema": SCHEMA.encode(),
            b"exact_value": b"UTF-8 decimal text + value_kind",
        },
    )
    return pa.Table.from_pylist(records(result), schema=schema)


def export(result, destination, *, format=None):
    """Create a new export and required metadata/provenance sidecars; never overwrite.

    CSV bytes are stable for equal semantic rows. Container bytes are not promised;
    the row hash is independent of container and creation time.
    """
    path = Path(destination)
    format = format or path.suffix.lstrip(".")
    if format not in {"csv", "parquet", "duckdb"}:
        raise ValidationError("Export format must be csv, parquet or duckdb")
    meta = Path(str(path) + ".metadata.json")
    prov = Path(str(path) + ".provenance.json")
    if any(p.exists() for p in (path, meta, prov)):
        raise ValidationError("Export destination or sidecar already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    final_paths = (path, meta, prov)
    staging = TemporaryDirectory(prefix=".finpanel-export-", dir=path.parent)
    path, meta, prov = (Path(staging.name) / p.name for p in final_paths)
    created = []
    try:
        with path.open("xb"):
            pass
        if format == "csv":
            with path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=COLUMNS, lineterminator="\n")
                writer.writeheader()
                for record in records(result):
                    # Escape the null marker in arbitrary user/source strings reversibly.
                    writer.writerow(
                        {
                            k: NULL
                            if v is None
                            else "\\" + v
                            if isinstance(v, str) and v.startswith("\\")
                            else v
                            for k, v in record.items()
                        }
                    )
        elif format == "parquet":
            import pyarrow.parquet as pq

            pq.write_table(_arrow(result), path, compression="zstd")
        else:
            import duckdb

            # DuckDB requires a nonexistent path, not an empty reserved file.
            path.unlink()
            with duckdb.connect(str(path)) as db:
                table = _arrow(result)
                db.register("input_rows", table)
                db.execute("CREATE TABLE panel_rows AS SELECT * FROM input_rows")
                db.execute(
                    "CREATE VIEW resolved_rows AS SELECT * FROM panel_rows "
                    "WHERE state IN ('resolved_reported', 'resolved_derived')"
                )
                db.execute(
                    "CREATE TABLE diagnostics AS SELECT row_id, cik, metric, fiscal_year, "
                    "period, as_of, state, reasons, conflicts FROM panel_rows"
                )
                db.execute(
                    "CREATE TABLE provenance (row_id VARCHAR, receipt_id VARCHAR, "
                    "evidence_json VARCHAR)"
                )
                db.executemany(
                    "INSERT INTO provenance VALUES (?, ?, ?)",
                    [
                        (r.row_id, r.receipt_id, dumps(result.provenance[r.row_id]))
                        for r in result.rows
                    ],
                )
                db.execute("CREATE TABLE build_metadata (metadata_json VARCHAR)")
                db.execute("INSERT INTO build_metadata VALUES (?)", [dumps(metadata(result))])
                db.execute("CHECKPOINT")
        for file, content in ((meta, metadata(result)), (prov, result.provenance)):
            with file.open("x", encoding="utf-8") as f:
                f.write(dumps(content))
        # Atomic no-clobber publication; only our own links are rolled back.
        for source, target in zip((path, meta, prov), final_paths, strict=True):
            os.link(source, target)
            created.append(target)
        return final_paths[0]
    except Exception:
        for file in reversed(created):
            file.unlink(missing_ok=True)
        raise
    finally:
        staging.cleanup()


def read_export(path, *, format=None):
    """Read and verify semantic rows against the mandatory metadata sidecar."""
    path = Path(path)
    format = format or path.suffix.lstrip(".")
    if format == "csv":
        with path.open(encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if tuple(reader.fieldnames or ()) != COLUMNS:
                raise ValidationError("CSV schema mismatch")
            raw = list(reader)
        for r in raw:
            for k, v in r.items():
                if v == NULL:
                    r[k] = None
                elif v.startswith("\\\\"):
                    r[k] = v[1:]
    elif format == "parquet":
        import pyarrow.parquet as pq

        raw = pq.read_table(path).to_pylist()
    elif format == "duckdb":
        import duckdb

        with duckdb.connect(str(path), read_only=True) as db:
            cursor = db.execute(
                "SELECT * FROM panel_rows ORDER BY cik, as_of, fiscal_year, "
                "CASE period WHEN 'FY' THEN 0 WHEN 'Q1' THEN 1 WHEN 'Q2' THEN 2 "
                "WHEN 'Q3' THEN 3 WHEN 'Q4' THEN 4 WHEN 'YTD-Q2' THEN 5 ELSE 6 END, metric"
            )
            raw = cursor.to_arrow_table().to_pylist()
    else:
        raise ValidationError("Unknown export format")
    result = [decode(r) for r in raw]
    meta = loads(Path(str(path) + ".metadata.json").read_bytes())
    receipt = meta["receipt"]
    if digest(receipt["semantic"]) != receipt["receipt_id"]:
        raise ValidationError("Export receipt hash mismatch")
    if (
        meta["schema"] != SCHEMA
        or len(result) != meta["row_count"]
        or meta["semantic_dataset_hash"] != receipt["semantic"]["row_hash"]
    ):
        raise ValidationError("Export metadata mismatch")
    provenance = loads(Path(str(path) + ".provenance.json").read_bytes())
    if (
        set(provenance) != {r["row_id"] for r in result}
        or [r["receipt_id"] for r in result] != receipt["semantic"]["row_receipts"]
        or any(digest(provenance[r["row_id"]]) != r["receipt_id"] for r in result)
    ):
        raise ValidationError("Export provenance hash mismatch")
    if digest(result) != meta["semantic_dataset_hash"]:
        raise ValidationError("Export semantic hash mismatch")
    return result
