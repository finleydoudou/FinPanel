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

**Alpha.2:** this source tree builds package **0.1.0a2**, with Git label
`v0.1.0-alpha.2`. Python **3.12** is required. Check the
[release list](https://github.com/finleydoudou/FinPanel/releases) and
[PyPI project](https://pypi.org/project/finpanel/) for publication availability;
source preparation alone does not imply that a release has been published.
The existing [a1 GitHub pre-release](https://github.com/finleydoudou/FinPanel/releases/tag/v0.1.0-alpha)
(package `0.1.0a1`) remains unchanged.
See [validation evidence](https://github.com/finleydoudou/FinPanel/blob/main/docs/release-validation.md)
and [release notes](https://github.com/finleydoudou/FinPanel/blob/main/docs/release-a2-notes.md).
This is experimental research software, not a stable production release.

## Installation

Once version `0.1.0a2` is available on production PyPI, install that exact version
in a clean Python 3.12 environment with `python -m pip install finpanel==0.1.0a2`.
Before publication, use only a verified candidate wheel supplied with its
`SHA256SUMS.txt`. Do not substitute an a1 artifact or rename its wheel.
For published a1 users, follow the
[a1 installation instructions](https://github.com/finleydoudou/FinPanel/blob/07f3e16fcf18019b16e5ac25d575e646d126c570/README.md#installation).

The verified-wheel workflow below also works for a2 GitHub release assets when
available. Maintainers build fresh artifacts from the exact authorized source;
the a2 wheel is named `finpanel-0.1.0a2-py3-none-any.whl`.

In the artifact folder, print the wheel hash:

```bash
# macOS
shasum -a 256 finpanel-0.1.0a2-py3-none-any.whl
# Linux
sha256sum finpanel-0.1.0a2-py3-none-any.whl
```

```powershell
# Windows PowerShell
Get-FileHash finpanel-0.1.0a2-py3-none-any.whl -Algorithm SHA256
```

Manually compare the printed hash with the wheel's row in the supplied checksum
file (case-insensitively); stop on a mismatch. Comparison is not automatic.

Create and activate a clean Python 3.12 environment:

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

Then install the candidate and verify:

```bash
python -m pip install ./finpanel-0.1.0a2-py3-none-any.whl
python -c "import finpanel; print(finpanel.__version__)"
python -m finpanel.cli --help
```

Expected candidate version: `0.1.0a2`. Dependencies may download from PyPI; the
FinPanel package comes from the supplied wheel. The example below is offline.
If PowerShell activation is unavailable, invoke `.\.venv\Scripts\python.exe`
in place of `python` without changing execution policy.

For an intentional source clone, see the
[developer/source workflow](https://github.com/finleydoudou/FinPanel/blob/main/docs/researcher-guide.md#developer-source-user).

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

See the [researcher guide](https://github.com/finleydoudou/FinPanel/blob/main/docs/researcher-guide.md) for a custom panel, historical
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

- Alpha.2 package: **0.1.0a2**, Git label **v0.1.0-alpha.2**. Check the release list for publication availability.
- Existing public GitHub release: [a1](https://github.com/finleydoudou/FinPanel/releases/tag/v0.1.0-alpha), package **0.1.0a1**, unchanged.
- Production PyPI: **not published**. TestPyPI rehearsal is conditional on gates and account setup; it is not a production release.
- Supported Python: **3.12**. [A2 software CI](https://github.com/finleydoudou/FinPanel/actions/runs/37799312175) passed macOS/Linux/Windows with **814 tests / 0 skipped** each on the TestPyPI-tested software candidate. Final release-only documentation/workflow changes additionally require successful CI on the exact final commit before publication.

The audited population contains 100 ordinary US-GAAP operating companies and
24,000 financial cells. **69.61% scalar coverage is not accuracy**. All 255
independently audited golden expectations, 2,435,238 invariant checks and 500
future-evidence mutation checks passed, with zero unexpected mismatches **within
that specified audited population**. This is not a universal accuracy or
market-wide support claim.

Read the [validation evidence](https://github.com/finleydoudou/FinPanel/blob/main/docs/release-validation.md),
[API/support policy](https://github.com/finleydoudou/FinPanel/blob/main/docs/api-stability.md), and [current release status](https://github.com/finleydoudou/FinPanel/blob/main/docs/release-status.md).
The [earlier gate](https://github.com/finleydoudou/FinPanel/blob/main/docs/release-candidate-gate.md) and
[earlier checklist](https://github.com/finleydoudou/FinPanel/blob/main/docs/release-checklist.md) are explicitly historical records;
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

Detailed references: [accounting/API workflows](https://github.com/finleydoudou/FinPanel/blob/main/docs/technical-reference.md),
[panels](https://github.com/finleydoudou/FinPanel/blob/main/docs/research-panels.md), [broad validation](https://github.com/finleydoudou/FinPanel/blob/main/docs/broad-validation.md),
[historical/revision audit](https://github.com/finleydoudou/FinPanel/blob/main/docs/historical-audit.md),
[resume](https://github.com/finleydoudou/FinPanel/blob/main/docs/resumable-validation.md), [changelog](https://github.com/finleydoudou/FinPanel/blob/main/CHANGELOG.md),
[third-party notices](https://github.com/finleydoudou/FinPanel/blob/main/THIRD_PARTY_NOTICES.md), and [MIT license](https://github.com/finleydoudou/FinPanel/blob/main/LICENSE).
