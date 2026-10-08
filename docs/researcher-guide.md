# Researcher guide

## Public release user — no checkout required

The [v0.1.0-alpha GitHub pre-release](https://github.com/finleydoudou/FinPanel/releases/tag/v0.1.0-alpha)
is available as Python package **0.1.0a1**, for **Python 3.12**. It is not on PyPI.

1. Open the release and download `finpanel-0.1.0a1-py3-none-any.whl`.
2. Optionally download `SHA256SUMS.txt` and verify the wheel (recommended).
   The [README installation section](../README.md#installation) gives macOS,
   Linux and PowerShell commands. Compare the printed hash with the wheel's row;
   verification is not automatic. Stop on a mismatch.
3. Open a terminal in the download folder. Create and activate a clean environment:

```bash
# macOS/Linux
python3.12 -m venv .venv
source .venv/bin/activate
```

```powershell
# Windows PowerShell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

4. Install the downloaded wheel and verify the version:

```bash
python -m pip install ./finpanel-0.1.0a1-py3-none-any.whl
python -c "import finpanel; print(finpanel.__version__)"
python -m finpanel.cli --help
```

Expected version: `0.1.0a1`. Dependency installation may access PyPI; the FinPanel
package is the GitHub asset. If PowerShell activation is unavailable, use
`.\.venv\Scripts\python.exe` in place of `python` without changing execution policy.
Continue with the frozen Quick Start below. No developer checkout or local build
artifacts are required.

## Developer source user

Use this separate workflow only when you intentionally want a source checkout:

```bash
git clone https://github.com/finleydoudou/FinPanel.git
cd FinPanel
```

Create and activate a Python 3.12 environment using the platform commands above,
then run from the cloned repository root:

```bash
python -m pip install .
```

This installs the cloned revision, which may be newer than the published alpha.
To inspect the exact release source, select `v0.1.0-alpha` in the clone before
installing. The public release workflow uses the wheel, not `pip install .`.

## Frozen Quick Start

After either installation workflow, run in your own working directory with a new
destination:

```bash
python -m finpanel.example output/quickstart
```

Bundled HRB SEC JSON responses are imported and verified by hash; no SEC credentials,
HTTP or private Tier B evidence are used. The example writes six FY2022 cells,
three resolved, with all unresolved states retained. It creates CSV, Parquet and
DuckDB exports, provenance sidecars and a reproducibility receipt. Three resolved
cells describe coverage, not accuracy. [Current release status](release-status.md)
records the passing macOS/Linux/Windows release CI; older gate reports are historical.

```python
from pathlib import Path
from finpanel import panel
from finpanel.serialization import loads

rows = panel.read_export("output/quickstart/panel.parquet")
for row in rows:
    print(row["metric"], row["state"], row["value"], row["reasons"])

summary = loads(Path("output/quickstart/summary.json").read_bytes())
provenance = loads(Path("output/quickstart/panel.parquet.provenance.json").read_bytes())
print(provenance[summary["provenance_row"]])
```

## Build a panel

The example store can also be reused for a custom explicit request:

```python
from finpanel import panel
from finpanel.snapshots import EvidenceStore

store = EvidenceStore("output/quickstart/evidence")
request = panel.PanelRequest(
    entities=("12659",),
    metrics=("revenue", "net_income", "operating_cash_flow"),
    fiscal_years=(2022,),
    periods=("FY",),
    as_of=("2022-08-17T12:00:00Z",),
    snapshot_id=summary["snapshot_id"],
    revision_policy="latest_available",
)
result = panel.build(request, store=store)
print(result.coverage())
panel.export(result, "output/custom-panel.parquet")
assert panel.reproduce(result.receipt, store=store).receipt.receipt_id == result.receipt.receipt_id
```

Supply your own explicit `PeriodEnd` dates for instant metrics when asking for fiscal
labels. The date association is a query input, not an inferred historical security
master. A multi-company panel takes more CIKs and a snapshot containing their evidence.
Inspect `state`, `reasons`, `conflicts`, and provenance before using `value`.

## Concepts and time

CIK identifies an SEC reporting entity, not a traded security. Concepts identify
reported XBRL meanings, not freely interchangeable labels. A period has exact dates
and, only when evidence permits, a fiscal label. Original JSON values, SEC `fy`/`fp`,
filing report dates, and inferred period identity remain distinct.

`as_of` is timezone-aware and bounds eligible filings/facts/calendar support before
interpretation. Exact acceptance times are used where available; date-only evidence
is conservatively admitted after the SEC local calendar day. Unknown availability
stays excluded. Retrospective inspection may describe more evidence and must not be
passed off as an earlier point-in-time answer.

A snapshot pins bytes captured at a separate retrieval time. Modern CompanyFacts
captures do not establish historical API delivery time. Later captures can contain
revisions, omissions, or corrections; pinning fixes the evidence universe and makes
those limits explicit. New snapshots never overwrite old ones.

## Revisions and derived quarters

`first_reported` selects earliest eligible temporal candidates; `latest_available`
selects latest eligible candidates; `all_available` retains available history and
reports incompatible values. An amendment form alone does not prove a restatement.
A later changed comparative is a revision observation with cause unknown unless
original narrative establishes more.

`metrics.resolve` remains reported-only. The panel's explicit default source policy
is `reported_then_derived`; use `reported_only` or `derived_only` when needed.
Q2 is YTD-Q2 minus Q1, Q3 is YTD-Q3 minus YTD-Q2, and Q4 is FY minus YTD-Q3. Both
operands must share compatible concept/unit/scope/period and revision evidence.
An unpaired revision cannot be silently mixed into arithmetic. Derived availability
is a computational evidence bound, not an SEC publication timestamp.

## Original XBRL verification

CompanyFacts does not establish complete original context dimensions. Opt-in
`best_effort` records verification limits; `required` prevents a scalar unless the
supported original-source checks succeed. XML contexts, units, precision, and source
provenance are preserved. Unsupported inline-only or dimensional evidence remains
explicit. A narrative amendment is not original numeric XBRL verification.

## Reproducibility and exports

Keep the snapshot store, receipt, and matching software environment. `panel.reproduce`
checks software/contracts, evidence integrity, and semantic identity. CSV, Parquet,
and DuckDB retain exact values as text plus numeric kind. Use `panel.read_export`
with its required metadata/provenance sidecars; do not treat a detached file as a
verified reproducibility bundle. Physical Parquet/DuckDB bytes need not be identical
across library versions, although semantic row hashes must match.

## Larger validation

Read [resumable validation](resumable-validation.md) for offline checkpoints and
[broad validation](broad-validation.md) for the original benchmark contracts. Current
measured coverage and independent correctness appear separately in
[release validation](release-validation.md). Routine CI never acquires live SEC data.

## Troubleshooting and limitations

- **No scalar:** inspect the state. Missing annual anchors, unsupported concepts,
  ambiguous scope, and incompatible revisions are useful conservative outcomes.
- **Same-day absence:** inspect availability precision and timezone; a filing date
  alone is not an exact publication time.
- **Offline cache miss:** import the correct frozen snapshot. Do not turn on live
  fallback to repair a pinned replay.
- **Replay software mismatch:** use the recorded environment. Do not edit a receipt
  hash or silently rebaseline it.
- **Checkpoint incompatibility/corruption:** preserve the artifacts and use the
  original job or a new destination. Never force an incompatible resume.
- **Export exists:** choose a new filename/directory; exports intentionally do not
  clobber existing results.
- **Large memory/time:** use deterministic issuer subsets and separate output jobs;
  one job uses one worker. The broad corpus is not required for onboarding.
- **Live SEC access:** configure a descriptive local `FINPANEL_SEC_USER_AGENT`, comply
  with SEC access requirements, and use the conservative acquisition tool. Never put
  a real contact identity in source, committed logs, or fixture metadata.

Unsupported: banks, insurers, IFRS normalization, segment aggregation, FX, prices,
returns, security-master history, and universal accounting ontology. Validation
supports claims about the audited population only. Neither scalar coverage nor
absence of observed mismatches proves universal accounting truth.
