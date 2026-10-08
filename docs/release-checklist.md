# Release preparation checklist

This checklist separates locally verified preparation from actions that require a
later authorized publication workflow. No box below authorizes a commit or release.

| Item | State | Evidence / limit |
|---|---|---|
| Prior contracts preserved | Verified | Existing baseline tests unchanged; no selection-rule changes |
| Permanent tests | Verified | 810 passed, 0 skipped; all 739 baseline tests unchanged |
| Lint and formatting | Verified | Ruff check and formatting on all Python source, tests, examples and scripts |
| Wheel and sdist | Verified | Prepared version 0.1.0a1 |
| Clean wheel install | Verified | New venv, isolated import outside checkout, CLI/module, offline six-cell example |
| Clean sdist install | Verified | Separate new venv; build isolation uses a local dependency wheelhouse |
| Export round trips and replay | Verified | CSV, Parquet, DuckDB semantic equality and pinned example receipt replay |
| Python | Verified scope | 3.12.14 locally; declares only Python 3.12 |
| Platform CI | Configured, not executed for WP7 | macOS/Linux/Windows matrix; WP7 remains unpushed |
| README and quick start | Verified | Frozen packaged example; no SEC credentials needed |
| Public API inventory | Prepared and reviewed | Public, experimental, private surfaces and error models documented |
| Dependency and notice audit | Prepared and reviewed | Runtime uses retained; upstream licenses and actual tested versions recorded |
| Historical/revision goldens | Verified | 22 calendar + 20 revision expectations and additional operand/mutation checks |
| Large validation | Verified | 100 issuers, 24,000 cells, 2,435,238 checks, 200 replays; zero unexpected mismatches |
| Resume safety | Verified | Interrupted/continuous receipts equal; corruption/incompatibility rejected |
| Original artifact integrity | Verified by regression | Existing frozen artifacts unchanged; new manifest import verifies byte hashes |
| Secret/path scan | Verified | No findings in candidate public files; compressed fixtures scanned too |
| Tier B corpus | Excluded | Ignored local output; absent from Git and built distributions |
| Changelog, version, URLs, classifiers | Prepared | Consistent 0.1.0a1 / prospective v0.1.0-alpha.1 |
| GitHub state | Baseline only | WP6 remains HEAD/origin/main; WP7 uncommitted and unpushed |
| Tag, GitHub Release, PyPI | Not performed | Requires a separate explicit instruction |

Before actual publication: run the prepared Linux/Windows CI matrix after authorized
synchronization, review issuer-authored narrative fixture distribution/notices, and
perform final artifact review. These are publication checks; no platform execution
or legal clearance is fabricated by this preparation checklist.
