# API and package stability policy

This is a pre-release compatibility commitment within the existing research scope,
not a v1 promise that all importable Python names are public. Existing WP1–WP6
calls and default behavior are retained. No namespace was removed or renamed.

## Intended supported research surface

| Surface | Entry points / return models | Contract |
|---|---|---|
| Raw SEC | `SECClient`, `submissions`, `companyfacts`, raw response/parse models | Explicit CIK; online identity required; offline cache misses fail |
| Filing/fact inspection | `filings.timeline`, `filings.available_as_of`, `facts.for_concept`, typed filing/fact records | Original raw fields and precision retained |
| Bounded interpretation | `asof.view`, `asof.revisions`, `periods.for_concept`, `revisions.analyze` | Explicit as-of versus retrospective mode; exact concept groups |
| Canonical metrics | Exports in `metrics.__all__`, especially `candidates`, `resolve`, `derive_quarter`, `resolve_quarter`, `compare_quarter` | Six declared metrics; reported-only `resolve`; explicit quarter policies |
| Snapshots | `EvidenceStore`, `Artifact`, `Snapshot`, `Integrity`, `run`, `reproduce`, `read_receipt`, `export_bundle` | Immutable byte captures; explicit version selection; fail-closed replay |
| Panels | `PanelRequest`, `PeriodEnd`, `PanelRow`, `PanelResult`, `PanelReceipt`, `build`, `export`, `read_export`, `reproduce` | Complete explicit grid, state/provenance per row, lossless semantic exports |
| Original XBRL | `xbrl.__all__`, including `inspect_filing`, `verify_fact`, `verify_metric`, `verify_derivation` | Supported XML only; retrieval-bounded verification; no fabricated dimensions |

Dataclass return models distinguish absence, ambiguity, unsupported scope, conflict,
and usable scalar results. `PanelRequest` normalizes query dimensions and validates
policies. Monetary values remain `int`/`Decimal`; portable exports carry exact decimal
text and number kind. JSON serialization uses `finpanel.serialization.dumps/loads`;
plain `json.dumps` is not a replacement for exact Decimal/model serialization.

Public metric entry points and models already carry type annotations. WP7 adds
annotations to panel build/replay/export/read-back arguments and returns and a
reported-only resolver docstring. Dynamic provenance dictionaries are intentional;
the whole package is not advertised as fully statically type-checked. Named states
remain strings validated by contracts rather than a new breaking enum conversion.

### Errors

`FinPanelError` is the shared expected-operation base. `ValidationError` also inherits
`ValueError`; cache failures use `CacheError`/`CacheMissError`, transport failures use
`SECRequestError`/`SECTimeoutError`, snapshot/replay uses `SnapshotError`, and strict
panel builds use `PanelBuildError`. Transport errors expose URL, attempt count, and
status where available, not credentials. Parse issues and unresolved financial
states normally appear in returned evidence/results; they are not automatically
exceptions. `errors="raise"` is the explicit strict panel option.

### Experimental and private

`validation.*` (universe, acquisition, historical diagnostics, benchmark reports,
checkpoints, and goldens), the `validate` CLI namespace, and `finpanel.example` are
experimental research tooling. Their formats are versioned and incompatible resumes
fail explicitly. Model/candidate construction helpers are advanced inspection APIs,
not permission to bypass cutoff or scope validation.

Leading-underscore helpers, `_reuse`, `_PinnedCache`, `_publish`, parser internals,
CLI dispatch implementation, fixture transport details, and benchmark aggregation
internals are private. Importability alone gives no stability guarantee. Keep raw
artifacts and receipts rather than depending on those implementation details.

## Version and replay

The prepared PEP 440 version is `0.1.0a1`; a corresponding future SemVer prerelease
tag is `v0.1.0-alpha`. This is an explicit project mapping to the first Python alpha
`0.1.0a1`; packaging tools must use the latter. No tag/publication is authorized. Receipt identity
includes the package version, source hash, Python patch version, and exact relevant
JSON/transport dependency versions. An older WP6 receipt intentionally requires its
original matching software for exact replay. Updating the package does not silently
upgrade an old receipt or rewrite its evidence.

## Dependencies and platforms

| Dependency | Kind | Declared minimum | Version used in local validation |
|---|---|---:|---:|
| httpx | Runtime HTTP transport | 0.28 | 0.28.1 |
| simplejson | Runtime exact JSON | 3.19 | 4.2.0 |
| pyarrow | Runtime Parquet/Arrow | 18 | 23.0.1 |
| duckdb | Runtime analytical export | 1.5 | 1.5.6 |
| tzdata | Runtime IANA timezone fallback | 2024.1 | 2026.5 |
| setuptools | Build backend only | 77 | 84.0.0 |
| build | Development build tool | 1 | 1.6.1 |
| pytest | Development tests | 8 | 9.1.1 |
| Ruff | Development lint/format | 0.11 | 0.16.10 |

These ranges are dependency constraints, not a claim that minimum-version matrices
were executed. HTTPX/simplejson are used by core ingestion/serialization; Arrow and
DuckDB support promised export formats, so none is an unused dependency. WP7 adds first-party `tzdata` for Windows and other
installations without an IANA system database. Clean-install checks disable system
timezone lookup and exercise winter/summer SEC offsets and the full example. Binary
wheels and architecture availability matter for Arrow and DuckDB.

Python **3.12 only** is declared for this alpha (`>=3.12,<3.13`); local validation uses
3.12.14 on macOS arm64. Other Python minors are not claimed. The CI matrix defines
Python 3.12 on macOS, Linux, and Windows with permanent offline tests, builds, and
clean artifact installs. The exact WP7 release-candidate run passed macOS and Linux but failed
Windows on checkout byte conversion and a Unix-only example import. The release gate
records each platform's final status; local fixes are not a Windows pass. There is
no platform-specific accounting fork.

`scripts/validate_install.py` installs wheel and sdist into separate new virtual
environments, runs outside the checkout with isolated Python imports, checks the
installed CLI/module, executes the bundled offline example, verifies replay, and
compares all three export round trips. It cannot fall back to the developer editable
installation. Dependency downloads may use PyPI; SEC access remains disabled.

The timezone-data fallback follows the [Python zoneinfo recommendation](https://docs.python.org/3.12/library/zoneinfo.html#data-sources). Local broad validation used the host database; clean installs also verify the packaged fallback. Receipts fail closed on semantic differences; the OS timezone database itself is not yet a separately pinned receipt component.
