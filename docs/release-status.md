# Current alpha release status

[FinPanel v0.1.0-alpha](https://github.com/finleydoudou/FinPanel/releases/tag/v0.1.0-alpha)
is a published **GitHub pre-release**, not a stable production release.

- Release tag: `v0.1.0-alpha`.
- Exact release commit: `30ffbbe658fbc517ec838ba499859ec05093283b`.
- Python package version: `0.1.0a1`; supported Python minor: **3.12**.
- GitHub wheel, sdist and `SHA256SUMS.txt`: available.
- PyPI publication: **has not occurred**.
- Documentation on `main` may be newer than the unchanged release tag and assets.

## Final release gate

[CI run 37758981406](https://github.com/finleydoudou/FinPanel/actions/runs/37758981406)
validated the exact release commit:

| Platform | Python | Permanent tests | Wheel/sdist builds | Clean installs |
|---|---|---|---|---|
| macOS | 3.12.10 | 814 passed, 0 skipped | PASS | PASS |
| Linux | 3.12.14 | 814 passed, 0 skipped | PASS | PASS |
| Windows | 3.12.10 | 814 passed, 0 skipped | PASS | PASS |

The earlier candidates exposed frozen-evidence newline conversion, a Unix-only
example import and an implicit text-encoding assumption in export tests. Narrow
portability fixes and regression tests resolved those blockers without changing
financial, as-of, revision or provenance semantics. The final release gate passed;
the tag and GitHub pre-release were then created.

Fresh final artifacts passed separate clean installations, offline public API and
example checks, CSV/Parquet/DuckDB round trips, provenance, receipts and replay.
The post-release external-user audit also passed wheel/sdist installation and the
packaged offline workflow; it identified stale release-state and installation
documentation, addressed on `main` without replacing released software assets.

## Installation and scope

Use the [public installation instructions](../README.md#installation) or
[researcher guide](researcher-guide.md#public-release-user--no-checkout-required).

The [historical WP7 validation evidence](release-validation.md) covers a specified
100-issuer ordinary US-GAAP population: 24,000 cells, 255/255 golden expectations,
2,435,238 invariant checks and 500 future-evidence mutations. Zero unexpected
mismatches applies only to that audited population. **69.61% scalar coverage is
not accuracy** and is not evidence of universal-company support.

Banks, insurers, IFRS normalization, segment aggregation and FX normalization are
unsupported. Historical/original-XBRL evidence is incomplete for some issuers;
extension-heavy or dimension-heavy disclosures may remain unresolved. See the
[API/support policy](api-stability.md).

## Historical records

The [original failed gate](release-candidate-gate.md),
[original checklist](release-checklist.md), [pre-publication draft](release-notes-draft.md)
and [WP7 completion report](wp7-completion-report.md) retain their original
candidate-specific findings and task permissions. Their failure/pending-publication
statements describe those past audits, not the current published alpha.
