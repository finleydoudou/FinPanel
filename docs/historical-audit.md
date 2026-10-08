# Historical calendar and revision audit

The independent WP7 ledgers are `tests/golden/release-calendar.json` and
`tests/golden/release-revisions.json`. They record literal raw facts, exact pointers,
response hashes, cutoffs, and authored expected states. They were prepared from
SEC contexts and filing order, not by serializing FinPanel's answers.

## Calendar evidence

Twenty-two expectations cover HRB's April fiscal years, its May–June 2021 transition,
the subsequent June fiscal year, absence before the transition filing, uncertain
quarters before an admitted annual anchor, Target and Costco's 52/53-week years,
Nike's leap-year annual period, and Target's 98-day final quarter with its own filing cutoff. The 61-day transition receives no manufactured
fiscal label. The surrounding full annual contexts retain their observed labels.
A reported date and a filing date are retained separately.

The [HRB transition filing](https://www.sec.gov/Archives/edgar/data/12659/000183886221000036/hrb-20210630.htm)
is accession `0001838862-21-000036`. Original decoded response SHA-256:
`1edcd3bade4414af942ad3f233b78d1e8077ddddfb84d1dd999e8143666957e6`.
It documents the two-month transition period. The aggregate fact observations and
filing timeline remain independently linked to their own original byte hashes.

`validation.historical.calendar_diagnostics` annotates transitions, shortened or
extended transition durations, missing anchors, uncertain boundaries, leap days,
non-calendar years, and week-based annual windows. Boundary movement alone is not
proof of a fiscal policy change. No authentic extended transition-year example was
established in this sample; that diagnostic is not advertised as authentic coverage.

`current_fye_comparison` is a separate retrospective annotation with
`eligible_historical_anchor=False`. It cannot enter the as-of calendar. Mutation
tests poison later facts and metadata and require earlier admitted results to remain
unchanged. New captures are immutable snapshot versions; raw fixtures are never edited.

## Revision evidence

Twenty expectations cover Mattel and Kraft Heinz, exact first/latest selection,
amendments, changed comparative values, unchanged repetitions, cutoff exclusions,
and incompatible values under `all_available`. Twenty expectations do not mean
20 independent accounting restatements.

The [Mattel amendment](https://www.sec.gov/Archives/edgar/data/63276/000162828019013975/mat1231201810-ka.htm)
is accession `0001628280-19-013975`. Original decoded response SHA-256:
`39effbac53b74031dfc3ba7a1f51aa824731f999c08930b35dc4190fc895fdc0`.
Its explanatory note identifies restated September and December 2017 quarterly
information and separately describes revisions to other periods. Those statements
support the limited formal-restatement attribution here, not a general claim that
any changed fact is a restatement.

The four additional Q4 contract checks use independently readable operands:

| Evidence vintage | Annual net income | Nine-month net income | Q4 difference |
|---|---:|---:|---:|
| Original 2017 | −1,053,836,000 | −772,553,000 | −281,283,000 |
| Amended 2017 | −1,054,579,000 | −879,286,000 | −175,293,000 |

The amended operands occur in the same filing. Before amendment, the original
result remains stable; afterward latest-available admits the revised pair while
first-reported retains the original pair. All-available remains conflicted.
These are derived numbers, not newly reported SEC facts.

The diagnostic vocabulary distinguishes amendment filing, later comparative
revision, repeated unchanged observation, unexplained value change, and unknown.
It never assigns an accounting cause automatically. Kraft Heinz's changed values
are labeled comparative revisions with cause unasserted in this audit.

## Fixture provenance

`tests/fixtures/release/manifest.json` describes ten new authentic captures:
CompanyFacts and submissions/history for three issuers, plus the two original
narrative filings. Gzip is lossless transport; both compressed and original byte
hashes are checked on import. Existing authentic fixtures are unchanged.
Synthetic mutations are test transformations and are never saved as authentic data.
These diagnostics add no metrics and change no fiscal or revision selection rules.

A further authentic FY2018 Mattel operand check detects a different situation:
the annual revision is in accession `0001628280-19-013975`, while the revised
nine-month cumulative amount is in `0001628280-19-013987`. Despite a plausible
numeric difference, latest-available returns `unpaired_value_revision`; the
pre-revision and first-reported residuals remain 14,913,000. These three extra
contract checks are reported separately from the 20 revision-ledger expectations.

The bundled HRB FY2022 panel also exposes the distinction between classifying an
individual annual context and resolving a fiscal-label query across all candidates.
Its valid annual contexts classify correctly, but unclassified comparative/quarter
contexts can still conservatively block a fiscal-label metric selection. The example
therefore retains three `ambiguous_period` duration rows, alongside three resolved
instant metrics. WP7 does not relax that blocker to improve onboarding coverage.
