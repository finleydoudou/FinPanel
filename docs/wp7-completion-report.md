# Work Package 7 completion report

WORK PACKAGE 7: COMPLETE — READY FOR v0.1.0-alpha RELEASE PREPARATION

All six preparation gates passed. This classification authorizes no publication.
The baseline remains `1b9560285b10abf35f08933dd8ff16dc0d5c559c` on `main`;
WP7 is uncommitted and unpushed. No tag, GitHub Release or PyPI upload was created.

## Stage gates

| Stage | Result | Evidence |
|---|---|---|
| 1. Historical calendars | Pass | 22 independently authored expectations; HRB transition, non-calendar years, 52/53 weeks, Target 98-day quarter, leap year, cutoff and metadata guards |
| 2. Restatements/revisions | Pass | 20 authored expectations; Mattel narrative-supported restatement, KHC comparative revisions, seven additional authentic derivation checks; no causal overclaim |
| 3. Resumable validation | Pass | Deterministic job identity, atomic issuer checkpoints, output hashes, exclusive writer lock, compatibility rejection, failure isolation, interruption/resume equivalence |
| 4. Expanded scale | Pass | 100 issuers, 14 categories, 24,000 cells, 2,435,238 invariant checks, 200 exact replays, 500 future-evidence mutation checks; zero unexpected findings |
| 5. API/package | Pass within stated platform scope | Public API inventory, type/doc improvements, explicit Python 3.12 scope, clean wheel/sdist installs, offline example and timezone fallback |
| 6. Release preparation | Pass | Researcher README/guide, validation evidence and coverage, changelog, prerelease metadata, notices, security scan, formal checklist |

Targeted stage checks passed before broader validation. The final permanent suite
passed **810 tests, 0 skipped**; all **739 baseline tests remain unchanged**. Ruff
lint and formatting passed, as did wheel/sdist builds, clean artifact installations,
CLI/module checks, CSV/Parquet/DuckDB round trips, pinned replay, metadata checks,
fixture hashes and repository hygiene. CI remains independent of live SEC access.

## Architecture and files

The financial selection engine, metric registry, period inference and revision
semantics were preserved. No company-specific financial rule or new metric was added.
The changes extend evidence auditing and operational reliability:

- `src/finpanel/validation/historical.py`: bounded offline views and provenance-bearing
  calendar/revision diagnostics. Current FYE comparisons remain retrospective annotations.
- `src/finpanel/validation/checkpoints.py`, `runner.py`, `cli.py`: deterministic jobs,
  verified issuer-boundary checkpoints, resume/subset/checkpoint/worker CLI options,
  isolated recorded failures, and coverage breakdowns.
- `src/finpanel/validation/release-universe.json`: separate 100-issuer manifest;
  the WP6 universe remains unchanged.
- `examples/audit_release_temporal.py` and `examples/summarize_broad_runs.py`:
  offline future-observation mutation audit and integrity-checked disjoint-run summaries.
- `src/finpanel/example.py` and `example_data/`: installed offline six-cell HRB example,
  authentic hash-verified JSON captures, exports and replay.
- `src/finpanel/panel/engine.py`, `panel/export.py`, `metrics/resolver.py`:
  public annotations/docstrings only; no financial behavior change.
- `src/finpanel/__init__.py`, `snapshots/pipeline.py`, `pyproject.toml`, `MANIFEST.in`:
  consistent `0.1.0a1` metadata, version-derived receipt identity, Python scope,
  package contents and timezone fallback dependency.
- `tests/test_release_historical.py`, `test_validation_resume.py`,
  `test_release_example.py`, `tests/golden/release-{calendar,revisions}.json`,
  `tests/fixtures/release/`: 71 new permanent tests and ten authentic captures,
  with raw/compressed hashes and two narrative source filings.
- `scripts/validate_install.py`, `.github/workflows/tests.yml`: isolated artifact
  installation checks and macOS/Linux/Windows Python 3.12 CI configuration.
- README, CHANGELOG, THIRD_PARTY_NOTICES and the documentation listed below:
  researcher onboarding, compatibility boundaries, measured results and release checks.

## Scientific validation

The complete measured [validation report](release-validation.md) separates coverage,
correctness, invariants and unsupported scope. Its [JSON evidence](release-scale-validation.json)
contains every issuer's state counts and the exact query, snapshot, software and shard hashes.

There are **255 independently authored golden expectations: 255 pass, 0 fail**.
The inventory comprises 32 canonical, 25 authentic derived-quarter, 156 WP6 broad,
22 calendar and 20 revision contracts. This counts distinct policy/cutoff expectations,
not distinct restatement events. Source XML checks and replay checks are additional.

**Coverage:** 16,706/24,000 cells resolve (**69.61%**): 14,136 reported and 2,570
derived. The 7,294 remaining cells comprise 4,108 unavailable, 1,502 ambiguous-period,
1,336 insufficient-evidence, 312 conflicted and 36 unsupported-request results.
Zero unexpected mismatches does not turn this coverage percentage into accuracy.

Liabilities coverage is 52.20%, predominantly constrained by unsupported exact
concepts and cutoff absences. Revenue accounts for 286 conflicts. Duration metrics
retain ambiguous calendars or missing/incompatible cumulative operands. Materials,
industrials, retail and utilities have lower coverage than technology; the full
report exposes these cohorts instead of masking them. Original XML source coverage
is limited: 13/200 queries verified, 187 instance-unavailable, zero observed
cross-layer mismatches. The original source audit regression remains intact.

Calendar evidence includes HRB's actual 61-day transition without a fabricated fiscal
label, surrounding full annual periods, Target's 98-day quarter, Costco/Target week
years and Nike's leap-year annual period. No authentic extended transition year was
established. Mattel's original narrative supports the specifically documented 2017
restatement. Same-filing amended operands yield a justified changed Q4; unpaired
FY2018 revisions remain conflicted. KHC changed comparisons have no asserted cause.

## Resume and performance

A job identity pins semantic query inputs, selected issuers, universe, snapshot,
manifest, software and validation-contract version. Each completed issuer is saved
atomically with semantic state and all output hashes. Resume rejects incompatibility
and corruption, skips verified completed issuers, and preserves partial files before
recomputing an interrupted issuer. Failed units remain explicit terminal records;
retry corrected evidence in a new job. Corrupt full snapshots fail closed.

Permanent tests prove interrupted/continuous semantic report and receipt equality.
Additionally, both completed 50-issuer authentic jobs were resumed: report, receipt,
findings and checkpoint files stayed byte-identical; all 100 completed units were
verified and skipped. Each finished in approximately 2.07 seconds. See
[completed resume evidence](release-resume-verification.json).

Initial job wall times were 2,353.23 and 2,328.24 seconds; peak RSS was 880.03 and
976.11 MiB per process. They ran concurrently with other audits, so these are not
isolated speedup measurements. Across the jobs, 100 source parses served 11,300
parse-cache hits, with 2,400 candidate builds and 21,600 reuses. Invariant density
was retained. Only one worker per job is supported; disjoint jobs can run separately.

## API, dependencies and platform claims

The supported research surface is explicitly inventoried for SEC reads, filing/fact
inspection, as-of/period/revision interpretation, six metrics, original XML checks,
evidence stores, snapshots, panels, exports and replay. Validation tooling and the
bundled example remain experimental; underscore helpers remain private. Default
WP1–WP6 API behavior remains compatible. Dynamic provenance is not presented as a
fully statically checked schema. Older receipts require their original software;
the new alpha version does not silently rewrite them.

Python support is **3.12 only**, tested locally with 3.12.14 on macOS arm64.
Linux/Windows CI is prepared but has not run because this work is unpushed; neither
platform is falsely claimed as executed. No additional local platform executor was
available. `tzdata>=2024.1` was added for hosts without system IANA data; clean installs
force the fallback and verify winter/summer SEC offsets. Existing runtime dependencies
remain necessary and unchanged. Tested versions, minima, purposes and license sources
are in [api-stability.md](api-stability.md) and the third-party notices.

## Documentation, checklist and hygiene

The new researcher-facing README links installation, custom panels, provenance,
as-of semantics, revisions, derivation, XBRL verification, snapshots, reproducibility,
exports and troubleshooting in [researcher-guide.md](researcher-guide.md). Earlier
technical examples are retained in [technical-reference.md](technical-reference.md).
Other added documents cover historical audits, resume contracts, API stability,
validation evidence, universe/temporal/golden/resume summaries, draft release notes,
CHANGELOG and the formal [release checklist](release-checklist.md).

The prepared version is `0.1.0a1`, corresponding to future `v0.1.0-alpha.1`.
All local preparation checks pass. Platform CI execution and review of issuer-authored
narrative fixture distribution are explicitly deferred publication checks, not
completed claims. No publication action was attempted.

Secret/path scans include candidate public files and decompressed fixtures. No
credentials, SEC contact identity, SSH material, tokens or private absolute paths
were found. The 506.26 MiB raw Tier B snapshot remains ignored and absent from Git,
wheel and sdist. Old authentic evidence files are unchanged; new authentic captures
retain manifests and both hashes. Synthetic mutations are never saved as authentic
fixtures. Temporary outputs, environments and benchmark checkpoints stay ignored.

## Remaining limitations and technical debt

- This is a purposive ordinary-US-GAAP sample, not market-wide correctness evidence.
  Banks, insurance, IFRS, segment aggregation, FX and market-price features remain excluded.
- Historical filing eligibility does not establish historical CompanyFacts delivery time.
  Original XML coverage is sparse; modern evidence cannot silently backfill cutoffs.
- Fiscal-label queries can remain ambiguous even when individual annual contexts classify;
  the bundled example intentionally has three unresolved duration metrics.
- No authentic extended transition case or universal revision-cause classification is claimed.
- Checkpoints retain cumulative rows/provenance, with increasing memory and disk costs.
  The lock/checkpoint/output location must be reused consistently; failure retry is a new job.
- Exact replay needs matching software. OS timezone data is not separately pinned;
  semantic replay differences fail closed. Dependency minimum-version combinations and
  other Python minors were not tested. Dynamic provenance typing remains future work.
- Linux/Windows execution and final issuer-narrative redistribution review remain before
  actual publication. The factual license inventory is not a legal clearance claim.

Recommended next action: review the WP7 diff and measured reports, then authorize Git
finalization if accepted. Run the prepared platform CI and final distribution review
before separately authorizing a tag or release. No subsequent work package has started.
