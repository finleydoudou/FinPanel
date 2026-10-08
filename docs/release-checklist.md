# Historical record — First-alpha release checklist

> **Historical, superseded record.** The original audit/draft below predates
> publication and retains its original failures and pending actions.
> [Current release status](release-status.md): `v0.1.0-alpha` is published on
> GitHub at `30ffbbe658fbc517ec838ba499859ec05093283b`; final macOS/Linux/Windows
> CI passed with 814 tests and 0 skipped on each platform. PyPI is not published.
> The statements below are not current release blockers or installation guidance.

Candidate baseline: `ce97d41378f2a11db711023db1aa8caf9978d054`.
This checklist records the release-candidate gate, not automatic publication approval.
See [the failure report](release-candidate-gate.md) and [exact CI evidence](release-gate-ci.json).

| Item | State | Evidence / limit |
|---|---|---|
| Clean starting baseline | PASS | `main == origin/main == ce97d413...`; initially clean; no tag/release |
| Prior contracts preserved | PASS | All 810 existing tests unchanged; no core financial/source changes |
| Clean baseline permanent suite | PASS | 810 passed, 0 skipped; local Python 3.12.14 |
| Portability regression checks | PASS | Two new tests; 90 relevant tests passed |
| Full post-fix permanent suite | PASS | 812 passed, 0 skipped, 477.55 seconds locally |
| Lint and formatting | PASS | Ruff check and format check; no skipped meaningful tests |
| Fresh wheel and sdist | PASS | Gate builds use fresh output folders; prepared version 0.1.0a1 |
| Clean wheel install | PASS | Fresh venv, isolated installed import, dependency check, console/module help |
| Clean sdist install | PASS | Separate fresh venv and isolated build using local dependency wheels |
| Public API smoke | PASS | Timeline, as-of, reported/derived resolution, original XML, snapshot, panel and provenance |
| Export round trips | PASS | CSV/Parquet/DuckDB semantic equality from installed artifacts |
| Independent environments and replay | PASS | Identical semantic receipts/rows and CSV bytes; HTTP disabled |
| Metadata and README metadata | PASS | Strict packaging metadata validation, Markdown description, version/range/license/URLs |
| Distribution contents | PASS | Package, frozen example, license/notices present; sdist includes checkout policy |
| Python support | PASS | 3.12 only; local 3.12.14; CI patch versions recorded per OS |
| macOS exact baseline CI | PASS | Python 3.12.10: 810 tests, build, wheel/sdist clean installs |
| Linux exact baseline CI | PASS | Python 3.12.14: 810 tests, build, wheel/sdist clean installs |
| Windows exact baseline CI | FAIL | Python 3.12.10: 771 passed, 2 failed, 37 setup errors; build/install steps not reached |
| Windows fixed-candidate CI | BLOCKED | Fixes remain uncommitted/unpushed; requires authorized synchronization and new CI |
| README / guide / release claims | PASS | Supported scope conservative; coverage distinct from correctness; Windows failure disclosed |
| API inventory / dependency notices | PASS | Existing API maintained; MIT/source notices present; no legal-clearance claim |
| Version / changelog / release notes | PASS | Package 0.1.0a1 explicitly maps to intended tag v0.1.0-alpha |
| Authentic goldens / hashes / temporal / resume regression | PASS | Included in the full permanent suite; no fixture or expected-value edits |
| New full Tier B benchmark run | NOT APPLICABLE | This gate requires permanent/installation tests; existing 100-issuer evidence retained with its scope |
| Secret / private-path scan | PASS | Candidate repository and distribution contents scanned, including decompressed evidence |
| Tier B / scratch / environments | PASS | Local ignored evidence and diagnostics; excluded from index and distributions |
| Final Git hygiene | PASS | HEAD unchanged; only intended local fixes/docs; index empty; no history operations |
| GitHub synchronization of gate fixes | BLOCKED | Explicitly prohibited automatically; local changes await review |
| Twine-specific validation | NOT APPLICABLE | Not configured/installed; strict metadata and distribution checks used |
| Tag / GitHub Release / PyPI publication | NOT APPLICABLE | Prohibited in this task; none performed |

The Windows failure blocks release acceptance. Passing local simulations cannot
replace an actual fixed-candidate Windows run. Review and explicitly authorize the
small fixes before synchronization, then rerun the full platform matrix on the new
commit. Do not tag the failing original candidate. Existing issuer-authored source
notices and distribution context should also be reviewed before publication; this
checklist grants no rights over third-party material.
