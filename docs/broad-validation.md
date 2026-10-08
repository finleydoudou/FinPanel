# Broad coverage and scale validation (Work Package 6)

FinPanel now has a repeatable, offline 50-issuer validation workflow. This is a
purposive sample of ordinary US-GAAP operating companies, not a statistically
representative sample of the US market. Scalar coverage is not accuracy.

## Universe and evidence tiers

The packaged `finpanel/validation/universe.json` is the deterministic selection
manifest. CIK is authoritative; tickers and names are convenience metadata, not a
historical security master. The manifest records rationale, inclusion/exclusion,
category, fiscal year end and tier. It contains 50 included issuers in 12 categories
and five explicit exclusion examples. Banks, broker-dealers, insurers, funds/ETFs,
SPAC-only shells, foreign IFRS reporters and unsupported sector ontologies are
outside the core universe. Current fiscal-year-end metadata describes the sample;
it is never used as historically admissible fiscal-calendar evidence.

* **Tier A:** 13 additional issuers: BA, TGT, XOM, INTC, PFE, NKE, ADBE, COST,
  AMZN, UPS, DUK, ORCL and DOW. Their 86 losslessly compressed authentic artifacts
  occupy 7,087,473 bytes (121,877,664 bytes before compression). The manifest checks
  both compressed and original-byte hashes, source URL, retrieval time and capture
  identity. Gzip does not edit SEC JSON/XML. The original four-issuer fixtures are
  unchanged. Tier A is part of permanent offline CI.
* **Tier B:** 50 issuers, 229 immutable artifacts, including 13 original annual
  XBRL instances and their official discovery documents. The full local evidence
  store and acquisition cache are ignored output, not permanent Git fixtures.
  Extended benchmarking is explicit, not part of every CI run. A custom universe
  and `--limit` support selection up to 100 issuers; 100 has not been benchmarked.

The snapshot/evidence manifest is published as report metadata. Reacquisition
from SEC creates a new evidence vintage if upstream responses have changed; hashes
alone cannot reconstruct old bytes. Exact replay of this published benchmark
requires its original immutable Tier B corpus, the matching software/environment,
and the saved per-panel receipts. Tier A can always be reconstructed from the
bundled compressed artifacts.

## Explicit acquisition and offline workflow

Set `FINPANEL_SEC_USER_AGENT` locally to a descriptive organization/project identity
with a real contact. Never put the actual contact in Git. Acquisition uses only
existing official SEC endpoints, serial requests with a two-second throttle and
bounded retries. Successful artifacts are hash-verified and reused on resume;
corruption is an error, not permission to silently replace evidence. Failures have
an acquisition category and HTTP status, separate from metric failures.

```sh
finpanel validate universe --output output/universe.json
finpanel validate acquire output/broad-corpus
# Adds officially discovered annual original instances for Tier A issuers:
finpanel validate acquire output/broad-corpus --originals
# Use the final snapshot ID printed by acquisition; no network in this command:
finpanel validate broad --store output/broad-corpus/evidence \
  --snapshot SNAPSHOT_ID --output output/broad-run
```

Acquisition supports checkpoint resume; the benchmark runner currently requires a
new output directory after interruption. Completed partial outputs remain intact,
but batch-level benchmark resume is not yet implemented.

Use the same acquisition destination and selection parameters to resume. A changed
selection requires a separate acquisition directory. Ford's provisional selection
CIK was corrected to SEC-confirmed `0000037996` during acquisition; the failed
checkpoint was retained locally and already acquired immutable bytes were reused.
No accounting data was fabricated to fill that selection error.

The broad command requires a new output directory. `--config` accepts the fields
of `BenchmarkConfig`; `--tier A`, `--limit` and `--universe` make smaller or custom
runs explicit. Default queries are FY2023/2024, FY/Q1/Q2/Q3/Q4, six existing metrics,
cutoffs 2024-08-15 and 2025-04-01, and both `first_reported` and
`latest_available`: 240 financial cells per issuer, 12,000 total. No metrics were
added. Instant request dates are prepared from raw Assets FY/fp buckets by taking
the latest end in each bucket, and recorded explicitly in receipts. This is a
benchmark query-selection convention, not independent proof of fiscal labels.
The actual resolver still requires admissible evidence at each historical cutoff.

Each issuer/policy produces Parquet with provenance/metadata and a panel receipt.
Every panel is replayed from its pinned snapshot. A separate annual Assets source
audit uses `first_reported`, `best_effort`, and the evidence snapshot capture cutoff;
it does not falsely count later-captured original files as available at the earlier
financial cutoffs. Original source coverage is deliberately sparse: one captured
annual instance for each of 13 issuers, not all years of all 50 companies.

`report.json` contains deterministic coverage, taxonomy, invariant and replay
counts. `findings.json` maps unresolved row IDs to categories. `receipt.json`
contains universe, query, evidence/software identities, ordered panel receipt IDs,
semantic dataset and report hashes. `performance.json` is observational and is
excluded from semantic hashes. Git HEAD identifies the accepted WP5 baseline;
WP6 is uncommitted, so the receipt's source-code hash identifies the actual WP6
implementation used. Wall time and process RSS are not deterministic outputs. Candidate build/reuse
counters sum the 100 initial financial panels; store/parse counters and total
wall time also include replay, invariant checks and the separate source audit.

See `examples/build_broad_panel.py` for the explicit acquisition/preparation steps,
Parquet panel build, SQL coverage queries, resolved/unresolved views, exact value
text, DuckDB export and saved benchmark receipt. It is a research example, not a
trading workflow.

## Independent correctness and raw evidence audits

`tests/golden/broad.json` contains 156 expectations (12 per Tier A issuer), including
annual metrics, reported Q1, Q2/Q3/Q4 operating-cash-flow derivations, conflicts,
missing standard concepts, pre-period unavailability and required-source failures.
Each case has fixed source SHA/pointer, literal values/accessions/dates and, where
applicable, explicit subtraction operands or an absence proof. These expectations
were prepared from frozen SEC JSON, not serialized resolver output.

The first independently prepared hypotheses matched 151/156. Investigation of the
other five revealed omitted raw blockers, not a demonstrated resolver defect:

* Amazon's overlapping trailing-year contexts share quarterly filing FY/fp labels.
  Existing period contracts conservatively reject those ambiguous windows. A
  plausible Q1 NetIncomeLoss and three operating-cash-flow subtractions therefore
  cannot be asserted as safely resolved by the current contracts.
* Dow has quarterly NetIncomeLoss but lacks a same-concept annual anchor for the
  audited year. Borrowing ProfitLoss's calendar would weaken the exact-concept rule.

The ledger preserves the five initial hypotheses, independently computed arithmetic,
and exact blocking observations/absence proof, with reasons for the corrected
contract expectations. No prior tests or resolver safety contracts were changed.

Report review did find a new WP6 diagnostic bug: generic caveats about unproven
original dimensions and revision-or-scope uncertainty were being counted as proven
dimension/revision blockers. Classification now requires the explicit blocker
codes (`dimensioned_arithmetic_not_supported`, `unpaired_value_revision`); a
dedicated regression distinguishes caveats from actual blockers. Financial states
and values are unaffected. The extended run was repeated with the corrected
classifier so its replay receipts match the final source code.
The final audit checks the raw literals before comparing the resulting states.

`tests/golden/broad-edges.json` adds 39 independently located original-XML facts
(three per issuer: decimals metadata, zero and dimensioned context), plus raw JSON
examples of 52/53-week years, amendments, changed comparative values, negative
income/cash flow, large values and zero standard concepts. JSON edge assertions
check literal pointers and the stated edge property. Changed comparative values
are **not** labeled confirmed restatements without causal filing evidence. A
confirmed fiscal-year transition in the query window has not been established.
Historical-gap behavior remains covered by existing offline tests; this corpus
is not claimed to prove complete SEC historical filing coverage.

```python
from finpanel.snapshots import EvidenceStore
from finpanel.validation.fixtures import import_fixtures
from finpanel.validation.goldens import validate_goldens

store = EvidenceStore("output/tier-a/evidence")
snapshot = import_fixtures("tests/fixtures/broad", store)
report = validate_goldens(store, snapshot.snapshot_id, "tests/golden/broad.json")
assert report["unexpected_mismatches"] == 0
```

The equivalent audit command is `finpanel validate goldens --store STORE --snapshot
ID --goldens tests/golden/broad.json --output output/goldens.json`.

## Invariants and failure interpretation

Programmatic checks verify exact raw-pointer value/accession, receipt source hashes,
snapshot identity, scalar/state consistency, panel-to-canonical value, temporal
eligibility of selected facts and calendar support, reported/derived identity,
instant exclusion from arithmetic, same concept/taxonomy/unit, and independent
Decimal subtraction. Pinned replay verifies the complete semantic receipt. Original
source disagreements become unexpected findings rather than reconciled values.

The taxonomy distinguishes expected conservatism, evidence gaps, acquisition
failures and unexpected implementation failures. It includes ambiguous periods,
unsupported/extension-only concepts, incomplete history, missing original sources,
source ambiguity, dimensions, incompatible revisions, insufficient cumulative
facts, units and conflicts. Category counts can overlap and are not scalar accuracy.
An explicit unclassified-conservative category makes residual taxonomy limitations
visible. All unexpected findings are reported separately; no exceptions count as
successful rows.

Coverage means the number of requested financial cells that yield a scalar under
these contracts. Correctness means agreement with the independently audited
expectations. Invariant integrity means absence of detected contract violations.
None of these establishes population-wide financial accuracy.

## Profiling and bounded reuse

A controlled, cProfile-instrumented Boeing 120-cell workload on identical evidence
was measured before and after optimization. Before: 38.107 seconds and 217.0 MiB
process peak RSS. After: 16.285 seconds and 200.953 MiB. Semantic row bytes were
identical. Full Company Facts parses fell from 28 to one; source JSON decodes fell
from 50 to 23. Repeated revision analysis and source parsing were the observed
bottlenecks. These instrumented measurements are not directly comparable to WP5's
unprofiled 480-cell baseline (26.5 seconds, 271 MiB, 48 candidate builds/432 hits).

Reuse is an internal, opt-in, context-local lifetime in the broad runner. Immutable
Company Facts parse keys include URL, byte hash and retrieval time; revision
analysis keys include evidence-view identity and policy. Caches reset on exit and
do not leak across queries/runs. Existing public/default APIs retain their behavior.
Semantic and receipt equality, changed bytes, new/tampered views and closed scopes
are tested. Reuse assumes evidence is not mutated inside the trusted internal
scope; it is not a public mutable-object cache contract.

One worker processes issuer batches sequentially. Large canonical evidence graphs
are released between batches; compact rows and receipts remain for deterministic
aggregate hashing. Each issuer exports independently. No acquisition parallelism,
no global cache, no accounting shortcuts. Peak RSS is process high-water memory,
not live retained Python heap. The extended run overlaps regression tests, so its wall time is an
end-to-end operational measurement, not an isolated performance comparison.
The full run still loads the snapshot repeatedly
and verifies stored bytes; those counters make remaining I/O visible. XML reuse
across distinct verification calls is not separately optimized.

## Current support and limits

| Scope | Evidence-based status |
| --- | --- |
| Ordinary US-GAAP operating issuers, standard company-wide concepts | Tested across 50 selected issuers; conservative abstention remains substantial |
| Annual, reported/derived quarter, instant and historical cutoff queries | Exercised with both revision policies; evidence and same-concept calendar requirements apply |
| Immutable panel replay and exact exports | Supported and regression-tested; exact replay requires original bytes and matching software |
| Extension-heavy or dimension-heavy disclosures | Partial; no extension inference or segment aggregation |
| Missing original instances / incomplete history | Explicit evidence limitations; no live substitution in offline runs |
| Banks, insurers, broker-dealers, foreign IFRS, funds and SPAC shells | Outside this validation universe and current ontology claims |
| FX normalization, security master, market-wide completeness | Not implemented or claimed |

Remaining debt includes broader manually audited original-source coverage, confirmed
fiscal-transition/restatement causality cases, more precise taxonomy for residual
abstentions, and profiling repeated integrity/JSON work without weakening provenance.
A proposed next work package is targeted, independently audited evidence-gap and
calendar diagnostics, selected from these findings; it has not been started.

## Recorded completion run

Machine-readable results: [coverage](broad-validation.json),
[independent goldens](broad-golden-validation.json),
[benchmark receipt](broad-benchmark-receipt.json),
[evidence manifest](broad-evidence-manifest.json),
[performance](broad-performance.json), and
[classifier correction comparison](broad-classifier-regression.json).

| Financial result state | Cells |
| --- | ---: |
| `ambiguous_period` | 720 |
| `conflicted` | 219 |
| `insufficient_evidence` | 580 |
| `resolved_derived` | 1,299 |
| `resolved_reported` | 7,236 |
| `source_verification_failed` | 0 |
| `unavailable` | 1,946 |
| `unsupported` | 0 |

8,535/12,000 cells produce a scalar (71.125% coverage, not accuracy). Independent correctness: 156/156 goldens match; 0 broad unexpected findings and 0 golden mismatches. The broad run executes 1,238,080 checks and 100 exact panel replays; the golden run executes another 20,462 checks.

Separate source audit: `instance_unavailable`: 87, `verified_multiple_equivalent`: 7, `verified_unique`: 6. Missing instances are not verified results.

| Diagnostic category (may overlap) | Cells |
| --- | ---: |
| `ambiguous_fiscal_period` | 994 |
| `conflicting_observations` | 219 |
| `incompatible_revision_operands` | 13 |
| `insufficient_cumulative_facts` | 631 |
| `not_available_as_of` | 1,834 |
| `unsupported_concept` | 680 |

Extended wall time: 1184.703 seconds; process peak RSS: 863.484 MiB. Initial financial panels: 1,200 candidate builds / 10,800 reuses. Overall: 50 full Company Facts parses / 5,650 reuse hits, 702 snapshot loads and 58,918 object reads. The full workload includes exports/provenance, source audits and replay; regression tests overlapped. Use the controlled paired profile for an optimization comparison.

Validation: 739 permanent tests passed, zero skipped; all 712 prior tests unchanged. Ruff, formatting, wheel/sdist builds and isolated installed-package checks passed. CI remains offline. Original 25 authentic hashes and all 86 added compressed/raw hashes were verified. No commit or push was made.

All 12,000 financial rows remained identical after the diagnostic classifier correction (excluding receipt IDs, which correctly change with the source-code hash). Raw Tier B evidence totals 300,445,003 unique bytes; the local acquisition/cache/store uses approximately 577 MiB. Large panel exports and provenance remain ignored local output.
