# First-alpha release candidate gate

RELEASE GATE: FAIL — BLOCKERS REMAIN

The inspected commit is `ce97d41378f2a11db711023db1aa8caf9978d054`.
It must not be tagged as accepted while its Windows gate is failing. The local
fixes described below are uncommitted and have not run on GitHub. No automatic
commit, push, tag, GitHub Release or package publication is part of this audit.

## Exact-commit platform results

[GitHub Actions run 37732279353](https://github.com/finleydoudou/FinPanel/actions/runs/37732279353)
ran against that exact SHA. [Structured results](release-gate-ci.json) retain job URLs.

| Platform | Python | Result | Permanent tests | Build / clean installs |
|---|---|---|---|---|
| macOS | 3.12.10 | PASS | 810 passed, 0 skipped | PASS |
| Linux | 3.12.14 | PASS | 810 passed, 0 skipped | PASS |
| Windows | 3.12.10 | FAIL | 771 passed, 2 failed, 37 setup errors, 0 skipped | Not reached |

The clean local baseline separately passed 810 tests, 0 skipped, on Python 3.12.14
macOS arm64 in 279.10 seconds. Python support remains limited to the 3.12 minor.
No Windows support claim is inferred from a successful local simulation.

## Failure classification and narrow fixes

1. **Checkout/file-byte portability:** Windows Git line-ending conversion changed
   raw frozen JSON/HTML/XML. The synthetic CompanyFacts hash after local LF→CRLF
   conversion exactly reproduces the Windows failure. This is not a changed SEC
   fact or a reason to relax hashes. New `.gitattributes` marks frozen fixture and
   installed-example evidence `-text`, preserving original bytes in either direction.
   The source distribution includes this policy. No raw fixture was edited.
2. **Unix-only example dependency:** `examples/build_research_panel.py` imported
   `resource` at module import, causing three setup errors. It now reuses the existing
   portable `peak_memory()` helper: unavailable telemetry is `None`, not zero.
   Panel computation and expected accounting results remain unchanged.

Two new permanent regression tests exercise a real disposable Git index with
`core.autocrlf=true` and import the example with the `resource` module unavailable.
No test is skipped, no hash expectation is weakened, and no financial selection,
revision, as-of, snapshot or provenance rule is changed. The relevant 90 tests pass.
The full post-fix local suite passed **812 tests, 0 skipped**, in 477.55 seconds.
Build, installation and content checks are recorded in the checklist.

A rerun of the original Windows job would execute the same defective commit, not
these fixes. Fixed-candidate Windows CI is **BLOCKED** until a separately authorized
commit/push. The existing workflow needs no unrelated change.

## Packaging, API and reproducibility scope

Fresh wheel/sdist builds and isolated installations are audited for this gate,
including package metadata and private-data exclusions. Installed public APIs are
exercised for filing timeline, bounded as-of evidence, canonical resolution,
derived-quarter resolution, original XML inspection, snapshot integrity, panel
build, provenance inspection, exports and replay. The workflow disables HTTP and
uses hash-verified frozen inputs. Two independent clean environments compare full
semantic receipts/rows and CSV bytes; Parquet/DuckDB are compared semantically.
The final checklist records completion, without treating old WP7 artifact files as
new final distributions. Detailed local diagnostic artifacts remain ignored.

## Version and claim consistency

Intended public Git tag: **`v0.1.0-alpha`**. Python package metadata remains
**`0.1.0a1`**, explicitly designated as the first alpha. These are project-mapped
labels; users must use `0.1.0a1` in Python dependency specifications. The previous
prospective `alpha.1` tag wording is replaced, not created as an additional release.

Historical WP7 benchmark claims remain 100 audited ordinary US-GAAP issuers,
24,000 cells, 255 independent golden expectations and zero unexpected mismatches
within that defined population. **69.61% is scalar coverage, not accuracy**.
No universal-company, bank, insurer, IFRS, full-original-XBRL or market-wide
zero-error claim is introduced. WP7 completion reports retain their historical
context and point to this gate for current acceptance status.

## Release decision

Review the local portability and documentation changes, then explicitly authorize
Git finalization in a later task. Run the entire three-platform workflow on the
resulting new commit, including Windows build/clean installs. Only after that new
candidate passes should tagging be considered. The original SHA has a recorded
Windows failure; successful macOS/Linux jobs cannot override it.

The [release checklist](release-checklist.md) distinguishes passed checks from this
blocking platform requirement. Existing third-party notices record source provenance;
review the issuer-authored narrative distribution context before actual publication.
This audit does not claim legal clearance or authorize publication.
