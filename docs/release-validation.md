# Release candidate validation evidence

Historical WP7 validation report. Current release acceptance and platform results
are tracked in [the release-candidate gate](release-candidate-gate.md). Statements
about the uncommitted/unpushed WP7 state below describe that earlier validation.

WP7 validation is complete. These results describe a purposive, frozen research
population and the contracts checked on it. Scalar coverage is not accuracy, and
zero unexpected findings is not proof of universal accounting correctness.

## Population and reproducibility

The expanded universe contains **100 ordinary US-GAAP operating companies** in
**14 broad, manually assigned category groups**. Banks, insurers, broker-dealers,
funds and IFRS issuers remain outside the supported benchmark. The selection and
SEC-identity audit are in [release-universe-audit.json](release-universe-audit.json).
The original 50-issuer WP6 manifest and all existing authentic fixtures are unchanged.

The panel spans six existing metrics, FY2023/FY2024, FY/Q1/Q2/Q3/Q4, cutoffs
2024-08-15 and 2025-04-01 (UTC), and first-reported/latest-available policies:
**24,000 requested and observed financial cells**. No metrics were added.
Two disjoint deterministic 50-issuer jobs cover the complete sorted universe.

The pinned local snapshot is
`7ee0bbe49b267ce50d63bf1f45bc4f62b017a195db7e2fcefe99c3dc68669ef0`.
Its 406 raw artifacts total 530,856,505 bytes (506.26 MiB). This Tier B corpus stays
local and ignored; public summaries contain hashes and diagnostics, not a SEC mirror.
The [machine-readable report](release-scale-validation.json) records query inputs,
universe/software identities, shard receipts, output hashes, all issuer-level
coverage, raw-context calendar cohort evidence, and measured performance.

## Independent correctness and safety

| Check | Result |
|---|---:|
| Permanent tests | 810 passed, 0 skipped |
| Unchanged prior baseline tests | 739 |
| Independent authored golden expectations | 255 passed, 0 failed |
| Expanded financial/invariant checks | 2,435,238 passed |
| Exact panel receipt replays | 200 passed |
| Non-vacuous future-evidence mutation checks | 500 passed across 100 issuers |
| Source-verification queries | 200; outcomes below |
| Unexpected mismatches / issuer execution failures | 0 / 0 |

The [golden inventory](release-golden-inventory.json) counts 32 canonical,
25 authentic derived-quarter, 156 broad, 22 new calendar, and 20 new revision
expectations. Distinct cutoff/policy contracts count separately. These are not
255 unique economic cells or 255 restatement events. Seven extra authentic
revision-operand checks, original-XML fact checks, synthetic guards, and replay
checks are deliberately outside that conservative golden total.

The new [historical audit](historical-audit.md) documents H&R Block's 61-day fiscal
transition, Target's 98-day quarter, 52/53-week years, leap years, Mattel's documented
restatement and incompatible revision operands, and Kraft Heinz comparative revisions.
Earlier cutoffs remain unchanged when later evidence is introduced. The expanded
[mutation audit](release-temporal-audit.json) changes actual future observations for
all 100 issuers: 98 use net income and two use operating cash flow because no future
net-income observations existed. Empty mutation populations are not counted as passes.

Interrupted/resumed tests compare complete semantic reports and receipts, verify
completed units are skipped, preserve interrupted files, and reject changed jobs,
software, snapshots and corrupted outputs. See [resume contracts](resumable-validation.md).
Both completed authentic jobs were also resumed: all 100 units were verified and skipped,
with byte-identical semantic files; see [resume evidence](release-resume-verification.json).
Routine CI requires no live SEC access or local Tier B corpus.

## Coverage and result states

**16,706 / 24,000 cells resolve (69.61%)**: 14,136 reported and 2,570 derived.
The other 7,294 are explicit conservative outcomes:

| State | Cells |
|---|---:|
| unavailable | 4,108 |
| ambiguous_period | 1,502 |
| insufficient_evidence | 1,336 |
| conflicted | 312 |
| unsupported | 36 |

No scalar was manufactured to increase these percentages. The benchmark includes
periods not yet filed at the earlier cutoff, so unavailable cells are expected.

### Metric

| Group | Resolved | Requested | Scalar coverage |
|---|---:|---:|---:|
| assets | 3,480 | 4,000 | 87.00% |
| cash_and_cash_equivalents | 3,050 | 4,000 | 76.25% |
| liabilities | 2,088 | 4,000 | 52.20% |
| net_income | 2,724 | 4,000 | 68.10% |
| operating_cash_flow | 2,910 | 4,000 | 72.75% |
| revenue | 2,454 | 4,000 | 61.35% |

### Period

| Group | Resolved | Requested | Scalar coverage |
|---|---:|---:|---:|
| FY | 3,170 | 4,800 | 66.04% |
| Q1 | 3,604 | 4,800 | 75.08% |
| Q2 | 3,558 | 4,800 | 74.12% |
| Q3 | 3,266 | 4,800 | 68.04% |
| Q4 | 3,108 | 4,800 | 64.75% |

### Industry/category

| Group | Resolved | Requested | Scalar coverage |
|---|---:|---:|---:|
| business_services | 134 | 240 | 55.83% |
| communications | 845 | 1,200 | 70.42% |
| consumer_discretionary | 781 | 1,200 | 65.08% |
| consumer_staples | 1,880 | 2,640 | 71.21% |
| energy | 1,330 | 1,920 | 69.27% |
| healthcare | 1,962 | 2,880 | 68.12% |
| industrials | 1,453 | 2,400 | 60.54% |
| large_retail | 818 | 1,200 | 68.17% |
| manufacturing | 994 | 1,440 | 69.03% |
| materials | 290 | 480 | 60.42% |
| retail | 880 | 1,440 | 61.11% |
| technology | 3,594 | 4,320 | 83.19% |
| transportation | 707 | 960 | 73.65% |
| utilities | 1,038 | 1,680 | 61.79% |

These are broad descriptive research categories, not a claim of standardized
industry classification or statistically representative sampling. The smallest
group, business services, has one issuer (H&R Block).

### Fiscal-year behavior

| Observed raw annual-context cohort | Issuers | Resolved / requested | Coverage |
|---|---:|---:|---:|
| 52-week observed, no 53-week in selected window | 12 | 2,247 / 2,880 | 78.02% |
| 53-week observed | 17 | 2,788 / 4,080 | 68.33% |
| Calendar year | 57 | 9,062 / 13,680 | 66.24% |
| Other non-calendar annual | 14 | 2,609 / 3,360 | 77.65% |

These cohorts are retrospective descriptions of raw annual contexts filed before
the final cutoff, not calendar inputs or historical label proofs. Source hashes
and observed windows are recorded in the JSON report. An issuer with a historical
transition can also have an ordinary annual context in this benchmark era.

## Investigation of unresolved cohorts

Liabilities has the lowest metric coverage, 52.20%. Its 1,900 unavailable rows
include 1,516 unsupported-concept findings and 384 cutoff absences. The declared
exact-concept contract does not synthesize total liabilities from other balance-sheet
lines. Revenue contributes 286 of 312 conflicts; competing available source concepts
or observations are retained rather than arbitrarily ranked. Duration queries also
show ambiguous calendar anchors and absent/incompatible cumulative operands.

Reason categories overlap: 3,878 not-available-as-of findings, 2,060 ambiguous fiscal
periods, 1,548 unsupported concepts, 1,414 insufficient cumulative facts, 312
conflicting observations, and 23 incompatible revision-operand findings. They must
not be summed as disjoint cell counts. The 36 unsupported rows concern missing
explicit instant ends for HRB Q1, KHC Q1, and ORLY Q2; they are not unsupported issuers.

The lowest issuer coverage is Amazon and Sempra (110/240, 45.83%), followed by
Illinois Tool Works (112/240, 46.67%). Their recorded reasons include unsupported
concepts, missing historical evidence, uncertain period identity, and (Sempra)
conflicting observations. Materials (60.42%), industrials (60.54%), retail (61.11%),
and utilities (61.79%) trail technology (83.19%). Small cohorts and different
concept/calendar mixes preclude causal industry claims. Week-based calendars do
not uniformly fail: the 52-week cohort resolves 78.02%, compared with 68.33% for
the 53-week cohort. Conservative boundary evidence still limits duration coverage.

Source verification is a separate evidence-vintage audit: 6 queries are
`verified_unique`, 7 `verified_multiple_equivalent`, and **187 `instance_unavailable`**.
The source-verified coverage is therefore 13/200 (6.5%), not 100%. No cross-layer
mismatch was found where supported original XML was present. The other 187 cannot
be advertised as source-verified. These queries use capture-vintage availability;
they do not introduce subsequently retrieved XML into an earlier financial cutoff.
Existing 39 original-XML and 36 JSON-boundary audit checks remain in the regression
suite. Modern CompanyFacts captures do not establish historical API delivery times.

## Performance

The two serial 50-issuer jobs ran concurrently with other validation work. Their
wall times were **2,353.23 seconds** and **2,328.24 seconds** (39.22 and 38.80 minutes),
with per-process peak RSS **880.03 MiB** and **976.11 MiB**. These are measured job
times, not an isolated throughput or speedup claim. The jobs performed 100 CompanyFacts
parses, 11,300 parse-cache hits, 2,400 candidate builds and 21,600 candidate reuses.
No invariant density was reduced. Checkpoint writes retain cumulative semantic
rows/provenance, so disk and memory use grow with the requested grid.

## Package and release scope

Prepared package version: **0.1.0a1**, prospective tag `v0.1.0-alpha`.
Wheel and sdist clean installs check isolated import, dependency consistency,
CLI/module entry points, the frozen six-cell example, three export round trips,
pinned replay, and timezone operation without a system IANA database.
Ruff, formatting, build and metadata checks pass. See the [API/support audit](api-stability.md)
and [release checklist](release-checklist.md).

Python 3.12.14/macOS arm64 was executed locally. Linux/Windows Python 3.12 CI is
configured but not run for this unpushed work; those platforms remain an explicit
pre-publication check. No other Python minor is claimed. No tag, commit, push,
GitHub Release or package publication was performed.

Known limits include no authentic extended transition-year case in this audit,
limited original XML coverage, conservative ambiguity in fiscal-label queries,
no automatic accounting-cause inference, one worker per resumable job, and exact
replay requiring matching software. Issuer-authored narrative evidence has factual
provenance/notices; its distribution should receive a final publication review.
Banks, insurance, IFRS, segments, FX and market-price research remain outside scope.
