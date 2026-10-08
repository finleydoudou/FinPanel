# FinPanel

Research infrastructure for reproducible point-in-time SEC fundamentals.

FinPanel builds financial research panels from SEC filings and XBRL facts while
preserving which evidence supports each result. Choose a historical cutoff, pin
the captured evidence, and replay the result later. Unavailable or conflicting
facts remain explicit states instead of silently becoming numbers.

The alpha pre-release supports six metrics for ordinary US-GAAP operating companies:
revenue, net income, assets, liabilities, cash and cash equivalents, and operating
cash flow. It supports reported periods and conservative Q2/Q3/Q4 derivations.
Banks, insurers, IFRS normalization, segment aggregation, FX normalization, prices,
and returns are outside scope. Historical/original-XBRL evidence is incomplete for
some issuers; extension-heavy or dimension-heavy disclosures may remain unresolved.

**Current alpha:** [v0.1.0-alpha](https://github.com/finleydoudou/FinPanel/releases/tag/v0.1.0-alpha)
(package `0.1.0a1`, Python **3.12**). GitHub assets are available; **not published
to PyPI**. See [validation evidence](docs/release-validation.md) and
[current release status](docs/release-status.md). This is not a stable production release.

## Installation

### Option A — Install the published wheel (recommended)

No repository checkout is needed. Open the
[v0.1.0-alpha GitHub Release](https://github.com/finleydoudou/FinPanel/releases/tag/v0.1.0-alpha)
and download `finpanel-0.1.0a1-py3-none-any.whl`. Also download `SHA256SUMS.txt`
if you want to verify the published checksum (recommended).

Open a terminal in the folder containing the downloads. To verify the wheel:

```bash
# macOS
shasum -a 256 finpanel-0.1.0a1-py3-none-any.whl
# Linux
sha256sum finpanel-0.1.0a1-py3-none-any.whl
```

```powershell
# Windows PowerShell
Get-FileHash finpanel-0.1.0a1-py3-none-any.whl -Algorithm SHA256
```

Compare the printed SHA-256 with the **wheel's row** in `SHA256SUMS.txt`
(case-insensitively). Stop if they differ. These commands print a hash; they do
**not** perform the comparison automatically. The checksum file also lists the
sdist, which you do not need for the wheel workflow.

Create and activate a fresh Python 3.12 environment:

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

Then install and verify, using the activated environment on either platform:

```bash
python -m pip install ./finpanel-0.1.0a1-py3-none-any.whl
python -c "import finpanel; print(finpanel.__version__)"
python -m finpanel.cli --help
```

Expected version: `0.1.0a1`. Installation may download dependencies from PyPI;
FinPanel itself comes from the downloaded GitHub wheel. FinPanel is not on PyPI
and the example below needs no live SEC access. If PowerShell activation is
unavailable, use `.\.venv\Scripts\python.exe` instead of `python` without
changing your execution policy.

### Option B — Install from source

For an intentional clone and source installation, see the
[developer/source workflow](docs/researcher-guide.md#developer-source-user).

## Quick Start — no SEC credentials

After installation, run this from your own working directory. Choose a fresh
output directory each time:

```bash
python -m finpanel.example output/quickstart
```

This uses bundled, hash-verified H&R Block SEC captures. It creates six FY2022
cells, CSV/Parquet/DuckDB exports, provenance sidecars, and a replay receipt. Three
cells resolve under the example's cutoff and conservative contracts; three remain
unresolved. That is **coverage**, not an accuracy percentage. No network access or
large corpus download is needed. Choose a fresh output directory each time.

```python
from finpanel import panel

rows = panel.read_export("output/quickstart/panel.parquet")
for row in rows:
    print(row["metric"], row["state"], row["value"])
```

See the [researcher guide](docs/researcher-guide.md) for a custom panel, historical
cutoffs, original XBRL verification, pinned replay, and troubleshooting.

## What reproducibility means here

- A filing-availability proxy limits facts, filings, and calendar anchors before
  interpretation. Today's fiscal-year-end cannot explain all historical years.
- `first_reported` and `latest_available` choose temporal candidates within exact
  source identities. Different concepts or incompatible scopes are not merged.
- Derived quarters retain both cumulative operands. Incompatible revision states
  produce a conflict rather than plausible arithmetic.
- CompanyFacts is a captured aggregate feed. Filing-time eligibility does **not**
  establish when that aggregate feed first delivered a fact. Snapshot capture time
  and historical information cutoff are different dimensions.
- Exact replay requires the original snapshot and matching software/contracts.
  CSV semantic rows are deterministic; container bytes and performance timing are
  not cross-platform reproducibility promises.

## Validation and release status

- Current public release: [v0.1.0-alpha](https://github.com/finleydoudou/FinPanel/releases/tag/v0.1.0-alpha), explicitly an **alpha / pre-release**.
- Python package version: **0.1.0a1**; supported Python: **3.12**.
- GitHub Release: **available**. PyPI: **not published yet**.
- [Release CI](https://github.com/finleydoudou/FinPanel/actions/runs/37758981406): **macOS PASS, Linux PASS, Windows PASS**, each with **814 passed / 0 skipped**, builds and clean installations.

The audited population contains 100 ordinary US-GAAP operating companies and
24,000 financial cells. **69.61% scalar coverage is not accuracy**. All 255
independently audited golden expectations, 2,435,238 invariant checks and 500
future-evidence mutation checks passed, with zero unexpected mismatches **within
that specified audited population**. This is not a universal accuracy or
market-wide support claim.

Read the [validation evidence](docs/release-validation.md),
[API/support policy](docs/api-stability.md), and [current release status](docs/release-status.md).
The [earlier gate](docs/release-candidate-gate.md) and
[earlier checklist](docs/release-checklist.md) are explicitly historical records;
their original Windows failures are preserved, not current release blockers.

## Development

```bash
python -m pip install -e '.[dev]'
pytest
ruff check .
ruff format --check .
python -m build
python scripts/validate_install.py dist
```

Routine tests and the clean-install example use frozen evidence. Live SEC
acquisition is a separate, explicitly configured operation. Never commit an SEC
contact identity, credentials, or the local Tier B corpus.

Detailed references: [accounting/API workflows](docs/technical-reference.md),
[panels](docs/research-panels.md), [broad validation](docs/broad-validation.md),
[historical/revision audit](docs/historical-audit.md),
[resume](docs/resumable-validation.md), [changelog](CHANGELOG.md),
[third-party notices](THIRD_PARTY_NOTICES.md), and [MIT license](LICENSE).
