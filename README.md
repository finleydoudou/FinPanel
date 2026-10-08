# FinPanel

Research infrastructure for reproducible point-in-time SEC fundamentals.

FinPanel builds financial research panels from SEC filings and XBRL facts while
preserving which evidence supports each result. Choose a historical cutoff, pin
the captured evidence, and replay the result later. Unavailable or conflicting
facts remain explicit states instead of silently becoming numbers.

The alpha candidate supports six metrics for ordinary US-GAAP operating companies:
revenue, net income, assets, liabilities, cash and cash equivalents, and operating
cash flow. It supports reported periods and conservative Q2/Q3/Q4 derivations.
Banks, insurers, IFRS, segment aggregation, FX, prices, and returns are outside scope.

## Try it without SEC credentials

Python **3.12** is the supported minor version. From this repository:

```bash
python3.12 -m venv .venv
# macOS/Linux:
source .venv/bin/activate
# Windows PowerShell instead: .venv\Scripts\Activate.ps1
python -m pip install .
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

## Evidence, limits, and release status

WP7 expands historical calendar and authentic revision audits and adds verified
issuer-boundary benchmark resume. Read the [validation evidence](docs/release-validation.md),
[API/support policy](docs/api-stability.md), and [release checklist](docs/release-checklist.md)
for measured results and remaining limits. Validation is a purposive sample, not
proof of universal SEC correctness or market-wide support.

The prepared package version is **0.1.0a1**, corresponding to a prospective
`v0.1.0-alpha` tag. The release label maps explicitly to Python package version
`0.1.0a1` (first alpha); it is not an alternate version string for packaging tools.
The [release-candidate gate](docs/release-candidate-gate.md) currently blocks tagging
until the Windows fixes pass CI. No package, tag, or GitHub Release is published.
Install from the checkout or a locally built artifact; PyPI availability is not claimed.

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
