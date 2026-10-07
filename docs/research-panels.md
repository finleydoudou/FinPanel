# Research panels (Work Package 5)

`finpanel.panel` builds an explicit long-form research dataset. CIK is its primary
entity identity. Names and tickers are convenience metadata from supplied evidence,
not historical security identifiers. No metric ontology was added: revenue, net
income, assets, liabilities, cash and cash equivalents, and operating cash flow use
the existing mappings and correctness contracts.

## Request and execution

```python
from finpanel import panel
from finpanel.snapshots import EvidenceStore

store = EvidenceStore("output/evidence")
# Select an actual snapshot ID from this store explicitly.
snapshot_id = store.list()[0].snapshot_id
request = panel.PanelRequest(
    entities=("0000320193", "0000789019"),
    metrics=("revenue", "net_income", "assets"),
    fiscal_years=(2024,),
    periods=("FY",),
    as_of=("2024-11-15T00:00:00Z",),
    snapshot_id=snapshot_id,
    period_ends=(
        panel.PeriodEnd("0000320193", 2024, "FY", "2024-09-28"),
        panel.PeriodEnd("0000789019", 2024, "FY", "2024-06-30"),
    ),
)
result = panel.build(request, store=store)
print(result.coverage()["states"])
```

The Cartesian product is explicit; no as-of dates are invented. Identical entries
are deduplicated. Unsupported metrics/periods/policies and timezone-naive cutoffs
are rejected. Ordering is CIK, UTC cutoff, year, normalized period, metric, with
period order FY, Q1, Q2, Q3, Q4, YTD-Q2, YTD-Q3. Missing rows remain in that order.
`panel.build(**request_fields)` is equivalent to constructing the typed request.

**Instant metrics require caller-supplied `PeriodEnd` associations.** Fiscal labels
alone cannot establish a safe instant date in the existing resolver. Omission
produces `unsupported / explicit_instant_end_required`, never a guessed calendar
end. These dates select exact observations and do not override filing/fact cutoff
eligibility. The caller owns the fiscal-label/date association; the builder does
not certify it from future calendar evidence. Q4 and FY can intentionally point
to the same balance-sheet date.

`revision_policy` accepts `first_reported`, `latest_available` (default), or
`all_available`. The existing revision engine determines conflicts; the panel
does not choose a convenient scalar from disagreeing candidates.

`source_policy` accepts `reported_only`, `reported_then_derived` (panel default),
or `derived_only`. Existing metric APIs retain their reported-only defaults.
Quarter fallback delegates to WP2; conflicting or ambiguous reported evidence
is never bypassed by arithmetic. Q2/Q3 differences and Q4 annual residuals remain
explicitly derived, with both original operands and their eligibility evidence.
No new financial formulas exist here.

`source_verification` accepts `off` (default), `best_effort`, or `required`, using
WP3 unchanged. Required verification withholds an unverified scalar. Best effort
keeps the existing resolver's value and explicitly exposes the source limitation.
Original sources retrieved later cannot silently become historical as-of evidence.

`errors="collect"` retains source failures and unresolved decisions as rows;
`errors="raise"` fails on the first unresolved cell or source error. Invalid
requests and invalid/corrupt selected snapshots fail before building any rows.
Unexpected programming exceptions are not suppressed.

The default `timeline_scope="complete"` uses the established timeline loader and
requires all referenced history. A missing history object becomes an explicit
missing-evidence row. `timeline_scope="recent_only"` is an opt-in limited scope:
it uses only the snapshot's recent submissions, preserves discovery references,
and annotates every result with `timeline_recent_only`. It never falls back to
this scope after a failed complete load. Facts without eligible linked filings
remain excluded. This option is used in the four-issuer example because the frozen
fixtures do not contain every issuer's full referenced history.

## Evidence and replay

A pinned build requires one exact snapshot ID and an `EvidenceStore`. External
clients are rejected in that mode. Every issuer and derivation operand uses that
manifest, including missing evidence; no latest pointers or live requests are
consulted. A newer snapshot in the same store cannot affect the build.

The snapshot is a **retrieval vintage**, while `as_of` is an information-eligibility
cutoff. A snapshot collected in 2026 does not prove the aggregate Company Facts
payload existed in the same form in 2024. These axes remain distinct.

Unpinned builds use an explicit client or the existing live/cache client. They
are marked `unsnapshotted_within_build`; they cannot claim exact pinned replay.
For offline unpinned work pass `SECClient(..., offline=True)`. All reuse is local
to one build: raw responses, issuer timelines, candidate reports per
CIK/metric/cutoff, and XBRL inspections per accession. No global result cache exists.

```python
from pathlib import Path
from finpanel.serialization import dumps, loads

Path("output/panel-receipt.json").write_text(dumps(result.receipt))
receipt = panel.PanelReceipt(**loads(Path("output/panel-receipt.json").read_bytes()))
replayed = panel.reproduce(receipt, store=store)
assert replayed.receipt.receipt_id == result.receipt.receipt_id
```

The receipt binds the normalized grid, policies (including timeline scope), schema,
row hash, row evidence receipts, used capture/object identities, missing requests,
snapshot completeness, and WP4 software/contract identity. Creation time and
performance measurements are outside semantic identity. Source-code or contract
changes require the matching software version for exact replay. Missing/corrupt
manifest objects, tampered receipts, and changed replay results fail explicitly.
A reproducible unresolved row remains unresolved; replay is not a coverage claim.

## Long-form schema and diagnostics

Schema `finpanel-long-panel-v1` has 26 logical fields, plus exported `value_kind`:

| Group | Fields |
|---|---|
| Cell identity | row_id, cik, metric, fiscal_year, period, as_of |
| Convenience metadata | entity_name, ticker |
| Represented interval | period_start, period_end |
| Policies and decision | revision_policy, source_policy, state, value, unit, source_type |
| Source identity | source_concepts, source_taxonomies, accessions, filing_availability |
| Audit | verification_state, snapshot_id, evidence_mode, receipt_id, reasons, conflicts |

The exact field list is exported as `metadata.columns`; `row_id` identifies the
query cell, while `receipt_id` identifies that row's evidence decision. Compare
build receipts when policies/evidence differ; a row ID alone is not a dataset ID.

States are `resolved_reported`, `resolved_derived`, `unavailable`, `conflicted`,
`ambiguous_period`, `unsupported`, `insufficient_evidence`, and
`source_verification_failed`. Only resolved rows expose scalar values. Source
fields can be absent on unresolved rows; a missing scalar never becomes zero.

`result.coverage()` returns requested cells, state counts, reason counts, per-issuer,
metric, fiscal-year, period and cutoff/state aggregates, plus every cell's detail.
Reason counts can exceed row counts because one decision can have several causes.
Reasons retain existing resolver diagnostics and distinguish missing pinned
objects, unavailable sources, period ambiguity, revision/scope conflicts,
insufficient cumulative operands, and strict source-verification failure.

```python
row = next(r for r in result.rows if r.state.startswith("resolved_"))
detail = result.inspect(row.row_id)
# detail: row, canonical_result (or WP3 verification envelope), compact evidence,
# and build_receipt. No raw SEC payload is duplicated into the receipt.
```

Selected/considered/rejected observations, source URL/hash/pointer, temporal
eligibility, calendar evidence, revision groups, derivation contract and XBRL
verification evidence connect the row to original SEC artifacts. The receipt's
capture IDs map source hashes to the selected immutable snapshot. Collected source
errors expose their category rather than pretending there was a canonical result.

## Exports

```python
panel.export(result, "output/panel.csv")
panel.export(result, "output/panel.parquet")
panel.export(result, "output/panel.duckdb")
rows = panel.read_export("output/panel.parquet")
```

Every format includes `.metadata.json` and `.provenance.json` sidecars. Keep these
with the data. Exports refuse existing destinations or sidecars; publication uses
no-clobber local files. `read_export` verifies row, receipt and provenance hashes.
It returns the canonical portable representation: value text and explicit
`integer`/`decimal` kind, reversible with `int(text)` or `Decimal(text)`.

| Format | Exact values | Dates and nulls | Audit |
|---|---|---|---|
| CSV | Base-10 text + value_kind; never float | ISO UTC/time/date, `\N` null; leading backslashes escaped | Stable UTF-8 columns/rows and JSON sidecars |
| Parquet | UTF-8 exact text + value_kind; no bounded DECIMAL overflow | date32, UTC timestamp(us), nullable fields | Typed stable schema and sidecars |
| DuckDB | VARCHAR exact text + value_kind | DATE, TIMESTAMPTZ, SQL NULL | panel_rows, resolved_rows, diagnostics, provenance, build_metadata |

Arrays are reversible JSON objects with an `items` list in all flat formats.
CSV escaping preserves a literal `\N` string separately from null. The arbitrary
precision representation preserves large integers, Decimal scale and signed zero.
Do not cast to DOUBLE for exact arithmetic. DuckDB numeric casts are a researcher
choice after checking the precision/range required by the data.

```python
import duckdb

with duckdb.connect("output/panel.duckdb", read_only=True) as db:
    print(db.execute("SELECT state, count(*) FROM panel_rows GROUP BY state").fetchall())
    # Or query the preferred analytical interchange directly:
    print(
        db.execute(
            "SELECT cik, metric, value, value_kind, state FROM "
            "read_parquet('output/panel.parquet') LIMIT 5"
        ).fetchall()
    )
```

Equivalent pinned builds give identical CSV bytes and semantic row hashes across
all three formats. Container bytes and creation metadata are not promised identical.
Performance and timestamps do not enter the semantic hash. Exact source values do.

## Reproducible offline example and CLI

From the source checkout:

```bash
python examples/build_research_panel.py --output-dir output/research-panel
finpanel panel build request.json --store output/research-panel/evidence --output output/new.parquet
finpanel panel replay output/research-panel/receipt.json --store output/research-panel/evidence --output output/replayed.csv
python -m finpanel.cli panel --help
```

`request.json` contains the serialized `PanelRequest` fields (write with
`finpanel.serialization.dumps(request)`). The panel CLI is always offline; it also
supports an unpinned request with `--cache-dir`. Existing SEC-fetch commands are
unchanged. CLI errors return nonzero, collected unresolved rows are successful
builds whose coverage must be inspected.

The example verifies unchanged authentic hashes, imports the existing evidence,
builds 480 requested cells (4 issuers × 6 metrics × 2 years × 5 periods × 2 cutoffs),
audits literal expected values and raw pointers, round-trips all exports, replays
the pinned dataset and demonstrates strict/best-effort source limitations. It saves
coverage, a row inspection, receipt, deterministic validation, and separate machine
performance measurements. It uses `recent_only` explicitly. All 655 earlier tests
and fixtures are preserved; new synthetic mutations are clearly test-only.

This is architecture validation on four issuers, not universal coverage or an
accuracy score. Remaining limitations include sparse original XBRL, incomplete
filing histories, explicit researcher-owned instant dates, memory use for retained
candidate/provenance objects, serial execution, and exact replay tied to software
identity. A future work package could expand audited evidence coverage and profile
larger panels; no new metrics, security master or trading features are implemented.
