# FinPanel

FinPanel is open-source research infrastructure for auditable financial fundamentals
from SEC EDGAR. Its long-term goal is reconstruction of information available at a
historical `as_of` date, with filing history and complete provenance.

**FinPanel does NOT yet provide research-grade point-in-time financial panels.**
This repository implements Phase 0A raw ingestion and Phase 0B historical filing
coverage, explicit availability precision, and filing-level as-of filtering.
Phase 0C adds opt-in SEC header corroboration and auditable fact/context links.
Phase 0D interprets reported fiscal periods with explicit evidence and uncertainty.
Phase 0E bounds evidence by a historical cutoff and exposes temporal revision contracts.
Authentic SEC fixtures are tested offline alongside separate synthetic edge cases.
It still does **not** construct normalized point-in-time financial fundamentals.

## Installation

Requires Python 3.12 or later; CI verifies Python 3.12.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
pytest
ruff check .
ruff format --check .
```

## Quick start

Set a descriptive identity with your real contact details. There is no default
identity, API key requirement, or ticker resolution. Pass CIKs explicitly.
Both the Python client and CLI read `FINPANEL_SEC_USER_AGENT`; an explicit
User-Agent argument takes precedence. Set it in your local shell, not in source
files or committed shell scripts. `.env` files are ignored by Git but are not
automatically loaded by FinPanel. Never commit your actual contact identity.

```bash
export FINPANEL_SEC_USER_AGENT='Your Research Organization your-email@example.org'
finpanel sec submissions 0000320193
finpanel sec companyfacts 0000320193 --raw-output output/aapl-facts.json
finpanel sec companyfacts 0000320193 --normalized-output output/aapl-observations.json
finpanel sec submissions 0000320193 --refresh --cache-dir .finpanel-cache
```

Commands print compact JSON summaries with record/issue counts, source URL,
response hash and cache status. `--raw-output` exports the original decoded HTTP
response bytes without JSON reformatting. `--normalized-output` saves typed records,
issues and provenance; decimal values remain JSON numbers without float rounding.
`--strict` exits 1 when parser issues exist. Request/configuration/I/O errors exit 2.
Output paths are overwritten atomically. Raw and normalized exports must identify different files; identical paths,
symlinks and hard links to the same file are rejected before requesting data. `--verbose` enables diagnostic logging. Routine tests never use SEC access.

```python
from finpanel.sec.client import SECClient
from finpanel.sec.companyfacts import parse_companyfacts

with SECClient() as client:  # reads FINPANEL_SEC_USER_AGENT
    source = client.companyfacts(320193)
result = parse_companyfacts(source)
print(len(result.records), len(result.issues))
```

## Architecture

- `sec/client.py`: synchronous httpx client, explicit User-Agent, timeout, CIK
  validation, deterministic exponential retries and a shared in-process limiter.
- `sec/submissions.py`: recent/historical column arrays and typed history references;
  a shared column parser preserves the original source paths.
- `filings.py`: accession-based timeline assembly, availability policy, filtering
  and coverage diagnostics; separate from raw parsing and Company Facts.
- `models/timeline.py`: filing events, historical references, availability precision,
  timeline results and coverage dataclasses.
- `sec/companyfacts.py`: one record per taxonomy/concept/unit/array position.
- `sec/headers.py`: minimal official text header parser, raw fields and line evidence.
- `availability.py`: cross-source metadata comparison and categorized diagnostics.
- `facts.py`: exact-concept observation inspection, filing links and repeated periods.
- `periods.py` and `models/period.py`: observed fiscal calendars and separate derived
  period classifications, identities, evidence and diagnostics.
- `asof.py` and `models/asof.py`: eligibility decisions and filtering before derivation.
- `revisions.py`: exact-concept revision groups and temporal candidate contracts.
- `models/`: dataclasses for filings, observations, contexts, evidence and diagnostics.
- `cache/file.py`: raw JSON/text objects keyed by SHA-256; versioned retrieval metadata
  keyed by metadata hash; atomic latest-response pointers keyed by URL hash.
- `serialization.py`: sorted JSON, exact Decimal parsing, ISO dates, duplicate-key
  rejection and rejection of non-standard NaN/Infinity JSON.
- `cli.py`: developer summaries and optional raw/normalized exports.

No database, web UI or point-in-time resolver is implemented. Runtime dependencies
are httpx and simplejson. Tests use pytest and httpx's in-memory MockTransport.

## SEC sources and access

Official sources:

- [SEC JSON API documentation](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)
- [SEC fair-access guidance](https://www.sec.gov/about/developer-resources)
- `https://data.sec.gov/submissions/CIK##########.json`
- `https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json`

The submissions endpoint supplies a recent filing section and references to older
history files. The raw `sec submissions` command remains recent-only for backward
compatibility. The Phase 0B `filings` API loads recent and all valid referenced
history files through the same client/cache. Company Facts
aggregates selected standard-taxonomy, whole-entity facts. It is not a complete
archive of filing-level XBRL contexts, dimensions or company-specific extensions.

The default limiter spaces request starts by at least one second across clients
sharing the default limiter in a process, including retries. An injectable limiter
supports a minimum 0.2-second interval. Coordinate multiple processes/machines
externally; their combined traffic is not managed by this package.

HTTP 429, 500, 502, 503 and 504 and transient transport failures retry at most three
times by default (four total attempts), with deterministic 1/2/4-second backoff.
Retry-After seconds and HTTP dates can extend the wait, including after the final
failed attempt. There is no jitter. HTTP 403 and other permanent errors fail
immediately. Redirects are not followed. Each connect/read/write/pool operation
has a 30-second default timeout, **not a total request or retry wall-time deadline**.
A server Retry-After can require a long wait; interrupt the operation if necessary.

## Provenance, cache and determinism

Raw JSON is retained separately under `.finpanel-cache/raw/objects/<sha256>.json`.
Headers, source URL and UTC retrieval time live under `raw/requests/<url-hash>/`.
A refresh stores a new version and updates `latest.json`; old objects and metadata
remain. HTTP compression is decoded by httpx; hashes cover decoded response bytes.
This is raw JSON preservation, not wire-level packet capture.

Cache hits do not contact SEC, expire automatically, or assert that SEC has not
changed. Use `--refresh` deliberately. Invalid successful-response envelopes are
not cached. Corrupt cache entries raise an explicit CacheError; explicit refresh
can replace the latest pointer. The cache has no database, garbage collection,
ETag revalidation or cross-process download locking. Concurrent refreshes use
atomic files; whichever latest pointer finishes last wins.

Each record carries source URL, response hash and JSON pointer. Fact pointers
identify the original observation object. Filing pointers identify the accession
cell in SEC's column arrays; the row index applies to all sibling column arrays.
Original record fields are also retained. Issues retain the offending raw value or
record plus a pointer; the complete original response remains authoritative.

Given identical bytes and source URL, parsing and normalized serialization are
deterministic. Retrieval timestamps and network results are deliberately not
claimed to be deterministic. Neither file dates nor ingestion times imply when
information first became public.

## Explicit assumptions and limitations

- Raw parsers do not select or deduplicate observations. Input array order is
  retained; taxonomy/concept/unit keys are traversed in sorted order. The derived
  filing timeline groups by CIK/accession and retains every original source row.
  Amendments with separate accessions always remain separate filing events.
- Missing optional fields remain `None`. Invalid optional fields produce issues
  and retain their original raw value. Unusable observations produce issues;
  they are excluded from typed records but retained in raw data and issue payloads.
- Broken top-level JSON or unusable CIK raises ValidationError. Duplicate JSON
  keys are rejected rather than silently keeping the last value.
- Values are integers or exact Decimals; no unit conversion or financial guesses.
- `fp=Q3` does not imply three months. Start/end dates are preserved independently.
  Absent start dates are not a validated claim of instant taxonomy semantics.
- `report_date` is read only if supplied as `reportDate`. It is never inferred
  from `end`, filing date, fiscal year or frame. Phase 0C links the observation to a
  separate filing event without overwriting any observation metadata.
- Fiscal year end comes from current submissions entity metadata. It is not
  independently validated as the fiscal year end at each historical filing.
- Acceptance timestamps retain supplied timezone information. A timestamp without
  an offset stays naive; no timezone is guessed. Text header wall times use the
  explicit, separately recorded policy described below.
- No taxonomy harmonization, financial value reconstruction, revision/restatement resolution,
  valuation, predictions, trading, portfolio logic, LLM/news/NLP, external vendor
  integrations, non-US exchange coverage or dashboard.

## Testing and authentic snapshot provenance

The frozen JSON under `tests/fixtures/` models SEC structures for Apple (AAPL),
Microsoft (MSFT), Walmart (WMT) and NVIDIA (NVDA). Its manifest records hashes and
explicitly marks it **synthetic**. All observations, filing dates and accessions
there are artificial test inputs and must never be used for research.

Tests cover CIKs, duplicate observations, units, dates, missing fields, malformed
containers/records, amendment retention, period metadata, provenance pointers,
exact decimals, deterministic serialization, throttling, retries, permanent errors,
timeouts, cache integrity/version retention and CLI exports. Tests inject HTTP
transports or pre-populate caches; live network access is not needed.

Authentic, unmodified JSON response bodies are stored separately in
`tests/fixtures/sec/` (eight files, approximately 16 MB). Its `manifest.json`
records the exact official endpoint, CIK, UTC retrieval time, SHA-256, raw status,
fixture purpose and parsing counts. HTTP content decoding is the only transport
transformation; financial values and JSON formatting are not edited.

The mandatory authentic-fixture acceptance test checks all eight files offline,
including hashes, expected endpoints, full record counts, original row values,
forms and deterministic serialization. Missing fixtures fail rather than skip.
CI does not contact SEC. Synthetic fixtures continue to cover malformed and
ambiguous records that are unsuitable to inject into authentic data.

To capture a new snapshot set from an authorized environment:

```bash
python examples/freeze_sec_snapshots.py --output output/sec-snapshots
```

The destination must be absent or empty so a capture cannot overwrite existing
evidence. Each successfully captured file has a manifest entry, even if a later
request fails. Partial sets fail the eight-file acceptance check. Review and
replace a frozen set deliberately; do not edit individual financial values.
The capture script uses the normal throttled client and your environment identity.

### SEC access investigation (2026-10-05)

A single request to the official Apple submissions endpoint with the earlier
project-only identity returned HTTP 403, `server: AkamaiGHost`, and the page title
“Your Request Originates from an Undeclared Automated Tool”. With a real contact
identity supplied only through the local environment, a manually issued request
to the same URL returned HTTP 200 JSON. A request five seconds later to
`https://www.sec.gov/about/developer-resources` also returned HTTP 200.
Neither request redirected or retried. The exact private identity is not recorded.

The client sends `User-Agent` and `Accept: application/json`; httpx adds standard
transport headers. Snapshot capture then obtained all eight official responses
through the existing client, at its default one-second request spacing, with no
parser issues. This evidence points to request identity as the likely cause of
the earlier denial, rather than an unresolved network restriction or parser defect.
It does not establish the SEC's internal blocking rule. No endpoint substitution,
proxy configuration, rotating address, HTML scraping or restriction bypass was used.

Review fixes in Phase 0A-Finalize: direct environment identity support in the
Python client; rejection of colliding raw/normalized export destinations; and
snapshot overwrite protection with incremental provenance manifests. Existing
throttling, timeout, HTTP 403 fail-fast behavior and parsing semantics are retained.

## Historical filing timeline (Phase 0B)

```python
from finpanel import filings

history = filings.timeline("0000320193")
available = filings.available_as_of(history, "2020-06-30T15:00:00Z")
report = filings.coverage(history)
# available_as_of also accepts a CIK and loads its timeline using the same client.
```

A `FilingTimeline` is iterable and exposes `records`, `issues`, `sources`,
`historical_references`, `historical_files_loaded`, `availability_policy`, and
`as_of` (UTC when filtered). Keep the original timeline to query a later cutoff;
widening a previously filtered timeline is rejected. Pass a caller-owned
`SECClient` with `client=...` to reuse caching/options; the API does not close it.

```bash
finpanel filings timeline 0000320193 --limit 10
finpanel filings available-as-of 0000320193 2020-06-30T15:00:00Z
finpanel filings coverage 0000320193
finpanel filings timeline 0000320193 --output output/timeline.json
```

Default output is a compact JSON summary plus at most 20 event previews. `--output`
saves all selected events with source rows, issues, policy and provenance.
`coverage` prints counts for each form (including 10-K, 10-Q and 8-K when present),
amendments, availability precision, overlaps, source files and potential gaps.
`--strict` exits 1 on parser/reference/conflict diagnostics. Date-only precision
alone is not a parser error. Request, offline cache miss and invalid-input errors
exit 2. There is no GUI.

### Discovery, identity and preservation

`filings.files` is the sole discovery source. Each reference retains its original
metadata, expected count/range, parent response hash and pointer. Only
`CIK<matching-10-digit-CIK>-submissions-<digits>.json` names are accepted; arbitrary
URLs, other issuers and path traversal are rejected with explicit issues.
Files are fetched from `https://data.sec.gov/submissions/<name>` in sorted name
order, once per unique filename. All repeated references remain in the result.
`refresh=True` refreshes both the parent and each history file.

Historical payloads are root-level column arrays and do not carry their own issuer
CIK/name. Issuer context comes from the parent and validated filename. The raw
history response is preserved unchanged; inherited entity metadata is not proof
of the company's historical name or fiscal-year-end regime. Historical record
pointers are `/accessionNumber/<index>`; recent pointers retain their Phase 0A path.

Within one company's timeline, accession is the primary event identity. Neither
form nor filing/report dates are identity keys. All source records, including
identical duplicate rows and unknown SEC fields, are retained in `source_records`.
Missing values can be supplemented by a non-conflicting source. Conflicting
non-null metadata is exposed in `conflicts` and issues; the derived field becomes
`None`. No latest-source preference is applied. Conflicting filing dates or
acceptance times give unknown availability. Invalid accession rows remain in raw
sources and issue payloads, but cannot become identifiable timeline events.

Forms ending in `/A` mark amendments, including 10-K/A, 10-Q/A and 8-K/A. They are
separate events when their accessions differ. Missing/conflicting forms produce
unknown amendment status. No original-to-amendment relationship is inferred.

### Availability policy: `sec-acceptance-conservative-v1`

Original SEC fields are never overwritten by derived availability. Three distinct
precision values are serialized:

| Precision | Policy | As-of inclusion |
| --- | --- | --- |
| `acceptance_datetime` | Unambiguous, valid timezone-aware SEC acceptance timestamp, converted to UTC | Timestamp is less than or equal to the cutoff |
| `date_only` | Missing/invalid/naive or potentially date-derived acceptance; use supplied filing date | Cutoff's New York calendar date is strictly later than the filing date |
| `unknown` | No usable date/time or conflicting availability metadata | Excluded |

An exact New York midnight acceptance timestamp is treated conservatively as
potentially date-derived, because this pattern occurs in older authentic records.
This is an explicit reliability heuristic, not a proven SEC flag: a true midnight
acceptance may also be downgraded. The original timestamp remains in source and
event metadata. Naive timestamps are never silently assigned a timezone. Other
aware acceptance times are used as supplied; they are not independently verified
against filing headers or dissemination logs.

Acceptance is an availability **proxy**, not proof of actual public dissemination
or delivery to every reader. A filing date is not an acceptance time. `as_of`
requires an offset-aware ISO datetime (or aware Python datetime); date-only and
naive cutoffs are rejected. The conservative date rule avoids intraday look-ahead
but intentionally excludes date-only filings during their own filing day.
New York day boundaries use `zoneinfo` and DST rules from the system IANA database;
on systems without it, install Python's `tzdata` package.

Ordering is ascending by availability time; date-only records sort at the start
of their New York date **only as a sorting key**, never as an exact publication
time. Precision and accession break ties. Unknown records sort last by accession.
Policy version, exact original timestamps and explicit precision remain auditable.

### Coverage and failure behavior

Every valid historical reference is attempted. A download failure or missing
entry in offline mode raises rather than returning an apparently complete recent
subset. Malformed references are preserved as explicit issues; a returned timeline
can therefore have incomplete coverage. Malformed rows are also reported. Inspect
`issues` and `coverage(...).potential_gaps`; use CLI `--strict` for automation.

Diagnostics report expected-versus-parsed historical counts/date ranges, parser
issues, conflicting metadata, missing dates/forms, unknown availability and
unresolved intraday precision. They do not infer expected 10-K/10-Q schedules,
invent absent filings or assert universal completeness when no issue is found.
Company filing histories, caches and separate retrievals may change over time.
A current SEC snapshot cannot establish which metadata was present at an old date.

### Authentic historical fixture and fully offline verification

One additional raw Apple history response is frozen in `tests/fixtures/history/`:
`CIK0000320193-submissions-001.json`, captured on 2026-10-06 (Hong Kong time;
2026-10-05 UTC). Its manifest preserves endpoint, CIK, UTC retrieval timestamp,
SHA-256, raw/unmodified status, purpose, and the parent fixture's identity/hash.
The Phase 0A fixtures have not been modified.

This file supplies 1,259 historical rows and at least 58 amendments. Together with
1,001 recent rows, the frozen Apple timeline contains 2,260 distinct accessions,
covering observed filing dates from 1994-01-26 through 2026-10-02. This particular
pair has no natural accession overlap; separate synthetic tests cover overlaps,
conflicts and duplicate rows without editing the authentic data.

The parent advertises history through 2015-09-08, whereas the captured historical
file's latest filing date is 2015-08-31. The timeline reports
`history_range_mismatch` and preserves both facts. This is a potential coverage
inconsistency, not proof of a missing filing or a reason to alter the fixture.

```bash
# Seed an ignored cache from the committed fixture manifests; no SEC requests.
python examples/inspect_timeline.py --cache-dir output/offline-cache
finpanel filings timeline 320193 --offline --cache-dir output/offline-cache --limit 3
finpanel filings available-as-of 320193 2020-06-30T15:00:00Z --offline --cache-dir output/offline-cache
finpanel filings coverage 320193 --offline --cache-dir output/offline-cache
```

Offline mode requires no contact identity and never falls back to networking.
Missing cache entries fail explicitly; combining `--offline` and `--refresh` is
invalid. The default remains network-capable for uncached requests. CI only reads
frozen fixtures or mocked transports; fixture capture is never part of CI.

Optional future capture (requires your locally configured real SEC identity):

```bash
python examples/freeze_history_snapshots.py --parent tests/fixtures/sec/aapl_submissions.json --output output/new-history
```

Only parent-referenced files are downloaded, with two-second request spacing.
The destination must be absent/empty. A partial manifest records successful
responses if a later request fails. Captures are not atomic multi-file SEC
snapshots; count/range diagnostics remain necessary.

## Filing evidence and context provenance (Phase 0C)

```python
from finpanel import facts, filings

checked = filings.validate_availability("0000320193", "0000320193-24-000123")
print(checked.comparison_status, checked.availability.method, checked.diagnostics)
observations = facts.for_concept(
    cik="0000320193",
    concept="RevenueFromContractWithCustomerExcludingAssessedTax",
    taxonomy="us-gaap",  # optional exact namespace filter
    header_accessions=("0000320193-24-000123",),  # optional, explicit fetches only
)
for record in observations.records:
    print(record.observation.value, record.context, record.filing, record.availability)
```

Both APIs accept `client=...` and `refresh=...`. Fact inspection loads Company
Facts and the complete referenced timeline; it does not fetch headers unless
explicitly requested. A missing concept returns an empty result with a diagnostic.
A supplied `filing_timeline` must be unfiltered and for the same issuer. This API
exposes observations, not a canonical or point-in-time financial value.

### Header retrieval and evidence policy

`SECClient.filing_header(cik, accession)` retrieves only the official
`https://www.sec.gov/Archives/edgar/data/<CIK>/<accession-without-dashes>/<accession>.hdr.sgml`
resource. It uses the existing limiter, retry, timeout, cache and offline policies,
with `Accept: text/plain`. A missing/blocked header fails explicitly; there is no
HTML scrape, unofficial mirror or full-filing fallback. The parser reads the
SEC-HEADER envelope only, supports tagged and readable labels, and preserves raw
fields including public document count and other supplied metadata. It does not
build a document/exhibit relationship graph or parse document bodies.

Text responses are kept as `<sha256>.txt` cache objects with `raw_format: text`
in metadata; old cache metadata without this field continues to mean JSON.
Header evidence uses one-based `line:N` locators, while submissions/facts use JSON
pointers. Both retain source URL and response hash. Exact bytes remain authoritative.

Each availability has `precision`, `timestamp` or `date`, `method`, `reason`,
and `evidence`. Evidence records raw field values, source locators and any
interpretation policy. The comparison policy is `sec-header-corroboration-v1`:

1. Compare accession/issuer identity, form, filing/report dates and all usable
   acceptance instants. Different offsets representing the same instant agree.
2. Preserve a usable submissions acceptance proxy (`sec_acceptance_datetime`).
   Agreement with a header yields `acceptance_corroborated`, not proof of public
   dissemination. Without headers, `not_checked` is explicit.
3. If submissions acceptance is unusable, a nonconflicting header acceptance may
   supply `filing_header_acceptance`. Otherwise use `filing_date_fallback` with
   date-only precision, or `unknown`. No intraday timestamp is synthesized.
4. Conflicting acceptance or filing dates, linked-header identity/metadata conflicts,
   or conflicting scalar header fields produce unknown availability. Both source
   values and diagnostics remain. Phase 0B's raw timeline remains unchanged by
   opt-in validation; use the returned validation/linked fact to inspect its result.

Four diagnostic categories distinguish `verified_inconsistency`, `missing_data`,
`precision_limitation` and `heuristic_warning`. Malformed supplied timestamps are
verified formatting inconsistencies; naive timestamps lack precision. Missing or
malformed evidence does not erase a usable independent source. Submissions form,
report-date and document conflicts remain explicit without alone invalidating
Phase 0B's acceptance proxy. Cross-source disagreement is never silently resolved.
Acceptance preceding the report end or following the filing day is a warning:
filing-date adjustments and form-specific circumstances require interpretation.
Midnight acceptance retains Phase 0B's conservative date-derived heuristic.

The 14-digit header acceptance field contains no offset. The parser explicitly
interprets it as `America/New_York` wall time using IANA DST rules and records that
policy. DST gaps/folds produce no exact timestamp; `timezone=None` keeps the
header time unresolved. This is a documented interpretation, not an offset
supplied in the header. Submissions timestamps without offsets remain naive.
The authentic sample corroborates the default policy but does not validate it
for all historical SEC formats.

[SEC webmaster guidance](https://www.sec.gov/about/webmaster-frequently-asked-questions)
describes a variable delay between acceptance and website availability, often
one to three minutes. Neither matching metadata nor an acceptance timestamp
establishes market-wide dissemination, and FinPanel adds no assumed fixed lag.

### Context and filing identity

The original observation retains taxonomy, concept, unit, exact value, accession,
form, filed date, fiscal year/period, start/end, frame, source and raw fields.
`observation_id` hashes the response URL/hash/pointer: identical-looking rows at
different array positions or in different snapshots remain distinct. It is a
source observation identity, not a persistent SEC fact identifier.

`FactContext` classifies the observed fields conservatively:

| Kind | Evidence | Duration days |
| --- | --- | --- |
| `duration` | Valid start and end, start <= end | Inclusive calendar count `(end - start).days + 1` |
| `instant` | Valid end and the start key is absent | None |
| `unknown` | Missing/malformed/reversed fields, including explicit null start | None |

An observed instant shape is not taxonomy validation. Company Facts does not
supply original instance `contextRef` identifiers, dimensional members, complete
entity contexts or filing document locations. `instance_context_id` remains None;
no original XBRL context ID is invented. No Q1/Q2/Q3, annual, YTD or TTM label is
inferred from duration, fiscal period or frame.

`LinkedFact` retains the observation, derived context, matched `FilingEvent`,
availability evidence and diagnostics. Links use issuer plus exact accession.
A missing filing link stays unknown; Company Facts `filed` is not substituted as
availability. Conflicting non-null fact/event form or filing date is reported and
makes the linked availability unknown. All source records remain auditable.

`repeated_periods` groups exact taxonomy/concept/unit/context/start/end matches
seen under multiple accessions, with member observation IDs, accessions and a
`values_differ` flag. Linked records retain each value and filing availability.
Originals, amendments and later comparative observations remain separate. These
groups identify repetition, not the cause of a revision or a restatement winner.

### Offline inspection and authentic validation

```bash
python examples/inspect_provenance.py
finpanel filings validate-availability 320193 0000320193-24-000123 --offline --cache-dir output/offline-provenance-cache
finpanel facts inspect 320193 RevenueFromContractWithCustomerExcludingAssessedTax --offline --cache-dir output/offline-provenance-cache --header-accession 0000320193-24-000123 --output output/provenance.json
```

CLI previews are bounded by `--limit`; `--output` writes the complete inspection
including contexts, raw observations, filing source rows, evidence and repetition
groups. Ordering and JSON serialization are deterministic for fixed inputs.
Fact `--strict` exits 1 for source/timeline issues or verified inconsistencies;
header validation `--strict` exits 1 for verified inconsistencies. Missing evidence,
precision limits and heuristic warnings alone do not fail strict validation.
Request/cache/configuration failures exit 2. The authentic Apple inspection still
reports the documented Phase 0B `history_range_mismatch` (strict inspection exits 1).

One unmodified 986-byte Apple 2024 10-K header is added in
`tests/fixtures/headers/`, with an official URL, UTC retrieval time and SHA-256
manifest. Its `20241101060136` wall time corresponds to submissions acceptance
`2024-11-01T10:01:36Z` under the recorded policy. Existing Apple Company Facts
fixtures exercise instant Assets, duration revenue and repeated reporting periods;
the historical fixture covers older lower-precision availability. Synthetic tests
cover amendments, conflicts, malformed data and DST ambiguity without changing
any authentic fixture. Routine CI remains offline and requires no SEC identity.

To capture another header deliberately, using a local environment identity:

```bash
python examples/freeze_filing_header.py 320193 0000320193-24-000123 --output output/new-header
```

The destination must be absent/empty. The helper uses two-second request spacing
and never records the contact identity. Capture is not part of CI.

### Remaining Phase 0C limitations

Technical debt includes broader issuer/header-format coverage, full instance
context and document relationship support, cache snapshot manifests across live
retrievals, cross-process rate coordination and a metadata conflict review workflow.
Availability validation is opt-in and does not mutate the Phase 0B timeline or
as-of filter. Repeated filing objects in full exports favor self-contained audits
over compact output. Live SEC responses may change independently between requests.

## Fiscal period interpretation (Phase 0D)

```python
from finpanel import facts, periods

inspected = facts.for_concept("0000320193", "RevenueFromContractWithCustomerExcludingAssessedTax")
result = periods.interpret(inspected)
for record in result.records:
    print(record.fact.observation.accession_number, record.period)

# Or load and interpret through one API:
result = periods.for_concept("0000320193", "RevenueFromContractWithCustomerExcludingAssessedTax")
# A single observation can use the same audited calendar:
period = periods.classify_period(inspected.records[0], calendar=result.calendar)
```

`periods.for_concept` accepts `taxonomy`, `client` and `refresh`. `interpret` is
purely local and preserves the entire Phase 0C inspection as `provenance`; its
records wrap each original linked fact alongside a derived `period`.
`classify_period` accepts a `FactObservation` or `LinkedFact`, with optional
`filing` and `calendar`. Without neighboring evidence it can classify an instant,
or establish a current annual window from a linked annual filing; quarterly
labels normally need an explicitly supplied calendar. No observation is dropped,
no financial values change, and duplicate/amended observations remain separate.

### Classification and identity

`PeriodClassification` contains `kind`, start/end, inclusive duration days,
`method`, deterministic `status`, `identity`, quarter/YTD flags, raw-field evidence,
diagnostics and policy version `reported-context-periods-v1`. Status is one of
`observed_shape`, `rule_supported`, `ambiguous`, or `insufficient_data`.
**Rule-supported is an interpretation under this policy, not SEC verification.**

| Kind | Interpretation |
| --- | --- |
| `instant` | Valid end with absent start key; keeps observation date, no fiscal duration label |
| `annual` | Exact match to a supported observed annual window |
| `single_quarter` | Exact observed quarter endpoint and start immediately after the previous endpoint, or at fiscal-year start for Q1 |
| `year_to_date` | Starts at observed fiscal-year start and ends at a supported Q2/Q3 boundary |
| `other_duration` | Valid interval outside supported standard duration ranges; no normalized fiscal label |
| `ambiguous` | Usable interval but missing/conflicting calendar, boundary or metadata evidence |
| `unknown` | Missing, malformed or reversed required dates |

As in Phase 0C, end-without-start is only observed instant shape, not taxonomy
validation. An explicit null or malformed start is unknown, not instant. Assets,
Cash and Liabilities stay distinct from duration facts. A duration uses
`(end - start).days + 1`, including leap days and both boundary dates.

`PeriodIdentity` keeps CIK, exact start/end and, only when supported, the represented
fiscal-year identifier and label (`FY`, `Q1`–`Q4`, `YTD-Q2`, `YTD-Q3`). It does not
include value, concept or accession and is not a fact identity. Phase 0C observation
IDs and filing provenance remain authoritative for distinguishing disclosures.
An ambiguous/unknown/other-duration result retains dates but has no fiscal label
or fiscal-year assignment. Instant identities keep the date without a fiscal label.

### Observed fiscal calendars and annual recognition

`FiscalCalendar` uses policy `observed-fiscal-windows-v1`. The default inspection
builds anchors from observations of the exact requested concept, including its
units/namespaces unless a taxonomy filter is supplied. Callers can build an
explicit calendar from audited same-issuer `LinkedFact` records with
`build_calendar(cik, records)`; it never mixes issuers.

A fiscal-year anchor requires all of:

- A valid inclusive duration of 350–378 days.
- An annual `10-K` or `10-K/A` fact with `fp=FY` and usable `fy`.
- A consistent accession/issuer/form/date link to a filing event.
- The context end matching that filing's report date.

The range is a versioned guardrail, not a universal annual-duration definition.
It admits 364-day (52-week), 371-day (53-week), and 365/366-day calendars. Dates
outside it may describe legitimate transition or irregular periods; they are not
automatically errors, and they do not establish an annual anchor in this version.
No January 1 or December 31 assumption and no issuer-specific code is used.

Current submissions `fiscalYearEnd` is retained with its source as a hint. It is
not projected backward into historical boundaries: week-based dates and issuer
calendars can change. Observed annual start/end dates define each supported year.
Different windows for the same fiscal year, overlapping fiscal years, conflicting
quarter endpoints or impossible quarter ordering mark that year's calendar
ambiguous. All candidate boundaries and their evidence remain in the result.

Annual classification requires an exact supported window match, not merely an
annual form or near-year duration. Comparative contexts matching an older window
keep that older fiscal year even when raw `fy` describes the later reporting year.
The report-end match required for anchoring prevents a later comparative context
from creating a false current-year window.

### Quarter, YTD and Q1 policy

Quarter boundaries require a consistent `10-Q`/`10-Q/A` linked fact whose end
matches its filing report date, whose `fy` matches an observed fiscal year, and
whose start equals that fiscal-year start. Its `fp` and inclusive duration must
agree with these policy guardrails:

| Boundary | YTD day range |
| --- | --- |
| Q1 | 70–112 |
| Q2 | 150–210 |
| Q3 | 230–308 |

A reported single quarter must be 70–112 days **and** exactly span the previous
observed quarter end plus one day through the current observed quarter end.
Q1 starts at the observed fiscal-year start. Missing prior-quarter evidence is
not replaced by subtracting 90 days or dividing an annual window into quarters.
Q2/Q3 YTD starts at the fiscal-year start; it does not require an intervening
quarter boundary. A reported Q4 context may be recognized when it starts the day
after observed Q3 and ends at the observed year end. **No Q4 or other financial
value is derived, and no synthetic observation is created.**

Q1 is represented as `kind=single_quarter`, label `Q1`, with both
`is_single_quarter=True` and `is_year_to_date=True`. Later single quarters have
YTD false; Q2/Q3 YTD has single-quarter false. Annual contexts leave the YTD flag
unspecified because this API reserves it for interim interpretations.

SEC `fp` alone is insufficient: a quarterly filing can contain both a single
quarter and cumulative YTD, and an annual filing can contain short comparative
contexts. Current-context metadata conflicts remain ambiguous. For comparative
contexts, the later filing's `fy/fp` is preserved without forcing it onto the
represented period. Frame is evidence, not a fiscal label: the
[SEC frames documentation](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)
describes alignment to calendar periods and warns that the included start/end
dates can differ. A calendar frame's quarter number does not override fiscal
boundaries.

### Authentic Q3 example

Apple accession `0000320193-24-000081` contains both of these observations for
`RevenueFromContractWithCustomerExcludingAssessedTax`, with raw `fy=2024`,
`fp=Q3`, and form `10-Q`:

| Represented dates | Inclusive days | Derived period |
| --- | --- | --- |
| 2024-03-31 to 2024-06-29 | 91 | FY2024 Q3 single quarter |
| 2023-10-01 to 2024-06-29 | 273 | FY2024 YTD-Q3 |

The classification also uses the observed FY2024 window (2023-10-01 through
2024-09-28), Q2 endpoint (2024-03-30), and current Q3 report endpoint. It is not
inferred from 91/273 days or `fp=Q3` alone. The same filing repeats FY2023 periods;
those retain FY2023 identities. The later FY2024 annual filing also repeats the
371-day FY2023 context (2022-09-25 through 2023-09-30), classified as FY2023.

### Diagnostics and ambiguity

Diagnostics cover reversed/missing dates, unusual durations, annual-form short
contexts, quarterly metadata accompanying annual durations, fiscal-year or `fp`
conflicts, missing annual/quarter boundaries, fiscal-calendar ambiguity, report
end conflicts, comparative contexts, and overlapping contexts within one filing
and exact taxonomy/concept/unit. Nested quarter/YTD intervals are ordinary
examples of overlap, so overlap is a heuristic warning, not an error. Duplicate
identical intervals do not themselves produce overlap warnings.

Missing evidence never creates a label. The classifier reports raw-field and
boundary evidence with URLs, hashes and source locators. Calendar conflicts
retain competing candidates; no newest-filing or restatement winner is selected.
`other_duration` describes an unnormalized interval, not an erroneous filing.

### Offline CLI and validation

```bash
python examples/inspect_provenance.py
finpanel facts periods 320193 RevenueFromContractWithCustomerExcludingAssessedTax --offline --cache-dir output/offline-provenance-cache --limit 10 --output output/periods.json
finpanel facts periods 320193 Assets --offline --cache-dir output/offline-provenance-cache --limit 3
```

The preview shows accession, form, filed date, raw `fy/fp/frame`, observed dates,
duration, derived identity/kind/status/method and diagnostics. `--output` preserves
all evidence, the complete observed calendar, every linked observation and the
original inspection. Fixed inputs produce deterministic output. `--strict` exits
1 on parser/timeline issues or verified inconsistencies, but not ambiguity or
heuristic warnings alone. Request/configuration/cache errors exit 2. Apple's
existing `history_range_mismatch` remains visible and causes strict exit 1.

No new SEC fixture download is needed. Tests reuse unchanged, hash-verified Apple,
Microsoft, Walmart and NVIDIA fixtures for non-calendar annual/quarter/YTD
contexts and instant facts. Apple supplies real 364/371-day years. Synthetic tests
cover missing/conflicting evidence, leap years, 14-week Q1, amendments and boundary
cases. All Phase 0A–0C regressions remain mandatory; CI uses no live SEC access.

### Phase 0D retrospective limitations

Calendar discovery depends on available anchors for the selected concept. Older
comparatives, incomplete histories and current-year quarters without a supported
annual window can remain ambiguous. This version supports US 10-K/10-Q families;
foreign and transition filing policies need separate evidence and tests. It does
not validate taxonomy periodType or recover original instance contexts.

Calendar evidence may come from later filings in the supplied snapshot. This is
retrospective period interpretation, **not an as-of-safe fiscal-calendar resolver**.
Consumers must not treat a normalized identity as proof that its supporting
metadata or financial value was available at an earlier date. Full exports repeat
linked observations/evidence for auditability and can be large.

Technical debt includes historical calendar transitions, finer conflict scope,
more periodType/context evidence, compact export references, and explicit timing
constraints for calendar evidence. Phase 0E supplies the explicit boundary described
below; the existing Phase 0D API retains its retrospective meaning. No canonical metrics, subtraction-derived quarters, restatement
winner selection, TTM, ratios, prices, trading or GUI has been implemented.


## As-of evidence and revision contracts (Phase 0E)

Retrospective and as-of interpretation answer different questions:

| Mode | Evidence used | API |
| --- | --- | --- |
| `retrospective` | All admissible observations in the supplied snapshot, including later filings | Existing `periods.interpret` / `periods.for_concept` |
| `as_of` | Only observations and filing evidence eligible at the explicit cutoff, filtered before calendar construction | `asof.view` / `asof.from_inspection` |

Period results expose `mode`; as-of results also expose their UTC `as_of` cutoff.
No existing Phase 0D classification behavior has silently changed.

```python
from finpanel import asof, facts, periods, revisions

# Filings only by default; an exact concept also loads facts and interprets periods.
view = asof.view(
    "0000320193",
    "2024-08-02T20:00:00Z",
    concept="RevenueFromContractWithCustomerExcludingAssessedTax",
)
for record in view.records:
    print(
        record.fact.observation.accession_number,
        record.eligibility.reason,
        record.period.kind,
        record.supporting_evidence,
    )

history = revisions.analyze(view, policy="latest_available")
# Equivalent fetching API:
history = asof.revisions(
    "0000320193",
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    as_of="2024-01-01T00:00:00Z",
    policy="first_reported",
)

# Compare modes locally, reusing an existing inspection:
inspected = facts.for_concept("0000320193", "Assets")
retrospective = periods.interpret(inspected)
bounded = asof.from_inspection(inspected, "2024-01-01T00:00:00Z")
```

Fetching APIs accept a caller-owned `client`, `taxonomy`, and `refresh`. Local
`from_inspection` admits only linked filings represented in that inspection;
`view` loads the complete referenced timeline before applying the cutoff. Missing
history still fails explicitly. No canonical concept mapping or metric is selected.

### Evidence eligibility and derivation order

Each `EvidenceEligibility` identifies a source URL/hash/locator, source accession,
availability value/precision/method, cutoff, role, eligibility flag and reason.
Fact decisions also retain the observation ID. Compact availability summaries
omit repeated raw evidence; the filing and fact objects retain their original
source fields and availability evidence.

The boundary follows the Phase 0B/0C availability policy:

- A valid aware acceptance proxy is eligible when its timestamp is **<= T**.
- Date-only evidence enters only after its New York filing day has ended. An
  intraday or same-day cutoff excludes it explicitly. DST day boundaries are
  respected, and no exact publication time is invented.
- Unknown/conflicting availability or a missing/invalid filing link is excluded.
- Both the linked filing and the fact's availability must be eligible. A usable
  filing date cannot rescue a conflicting fact-to-filing availability decision.

The implementation filters source observations first, then builds a new fiscal
calendar and reclassifies the retained contexts. It never takes a retrospective
calendar and filters the resulting classifications afterward. Future observations
cannot contribute annual anchors, quarter boundaries, overlap diagnostics, or
comparative metadata to admitted classifications. An earlier classification may
therefore become ambiguous even though the retrospective result is supported.

Current issuer names and submissions `fiscalYearEnd` have no historical field
availability in these models. The as-of projection withholds them and records
`unversioned_issuer_metadata` exclusions. Original source objects and raw bytes are
not mutated. Filing-linked dates, form and acceptance metadata use the documented
original-filing proxy assumption described below.

The view's primary `filings`, `records`, and `calendar` contain admitted inputs
and derivations. `admitted_evidence` records permission to use those sources;
each result's `supporting_evidence` traces the fields actually referenced by its
classification back to eligible decisions. `excluded_filings`,
`excluded_observations` and `excluded_evidence` are separate audit collections,
including raw future observations. They must not be used as derivation inputs.
Exclusions are retained even when they would have supplied a useful future anchor.
Snapshot-wide parser and coverage issues remain audit information, not anchors.

### Revision grouping and candidate states

Revision analysis groups exact CIK, taxonomy, concept, unit, observed context
kind and start/end dates. It never groups by numeric equality, aliases or a
cross-taxonomy financial metric. Unknown context shapes remain separate by
observation ID. Ambiguous contexts with exact dates can form comparison buckets,
but cannot produce resolved selections. A normalized period is attached only
when all members have supported, agreeing period identities. Disagreement remains
a conflict instead of being hidden by splitting incompatible normalized labels.

Every group retains all eligible candidates with exact values, accessions, forms,
filing availability, source provenance and bounded period interpretations.
`is_amendment` uses the filing form; `is_comparative` indicates that the represented
end precedes the filing report end. The latter is a metadata heuristic, not proof
of why a value was repeated or changed. Candidate states distinguish
`selected_by_contract`, `retained_history`, and `unresolved`.

| Policy | Contract |
| --- | --- |
| `first_reported` | Earliest eligible candidates by availability, within this observed exact-concept group |
| `latest_available` | Latest eligible candidates **by cutoff T**, not the latest observation present in today's full snapshot |
| `all_available` | Preserve the entire eligible set without a temporal preference |

These are temporal candidate contracts, **not economic restatement winners or
canonical metric selections**. No scalar financial value is returned. A later
comparative or amendment may be the unique latest temporal candidate without any
claim that it is the economically correct value.

Exact timestamps order directly. A date-only candidate is represented internally
by its New York filing-day uncertainty interval solely for partial ordering; it
is not assigned an exact availability timestamp. Candidates on different days
can be ordered, but an exact timestamp inside another candidate's date-only day
cannot establish which came first. No accession, array order, or numeric value
breaks such a tie.

### Conflicts and empty results

`first_reported` and `latest_available` remain conflicted when equally ranked or
partially ordered candidates cannot be distinguished, even if their values agree.
Different values among the selected temporal candidates produce an explicit value
conflict. `all_available` retains all members and reports a value conflict when
those values differ. Earlier differing values do not by themselves prevent a
unique later temporal candidate under `latest_available`; history remains intact.

Insufficient period evidence, normalized-period disagreement and matching-context
observations with unknown availability also prevent a resolved selection. Unknown
observations remain excluded and are shown as uncertainty blockers, not silently
ranked before or after known observations. Known-future observations do not enter
revision groups or affect their selection/conflict state at an earlier cutoff.

A group is `resolved` or `conflicted`; conflicted groups have no selected IDs.
The overall history additionally supports `no_eligible_candidates` when no group
can be formed. This does not imply that no filing or economic value existed.
`first_reported` means first among the evidence available in this source coverage,
not a claim of universal earliest disclosure. All policies retain their audit view.
Revision analysis rejects retrospective classifications and supporting evidence
outside its view's cutoff boundary, even if a caller mixes results manually.

### Authentic cutoff example and offline CLI

In the frozen Apple revenue data, the 2024 Q3 filing
`0000320193-24-000081` supplies the single-quarter context 2024-03-31–2024-06-29.
Retrospective Phase 0D interpretation calls it FY2024 Q3 using an annual anchor
from the later 2024 10-K, `0000320193-24-000123`.

At `2024-08-02T20:00:00Z`, that annual filing is future evidence. The quarter's
observation is admitted, but its interpretation remains ambiguous without the
annual anchor. At the annual filing's acceptance proxy,
`2024-11-01T10:01:36Z`, the anchor becomes eligible and supports classification.
Prior-year comparative observations in that later filing enter only then; they
are not substituted into earlier candidate histories.

```bash
python examples/inspect_provenance.py
finpanel asof evidence 320193 2024-08-02T20:00:00Z --concept RevenueFromContractWithCustomerExcludingAssessedTax --offline --cache-dir output/offline-provenance-cache --limit 3
finpanel facts revisions 320193 RevenueFromContractWithCustomerExcludingAssessedTax --as-of 2024-01-01T00:00:00Z --policy latest_available --offline --cache-dir output/offline-provenance-cache --limit 3 --output output/revisions.json
```

Without `--concept`, `asof evidence` inspects filing eligibility only. Previews show
eligibility/exclusion counts, reasons, periods, revision candidates/conflicts and
source locators. `--output` saves the full audit structure, including excluded
evidence. Repeated fixed inputs produce deterministic output. `--strict` exits 1
for parser/coverage issues, verified inconsistencies, or revision conflicts;
ordinary future exclusions and ambiguity alone in the evidence command do not
fail strict checks. Errors such as missing offline cache entries exit 2.
The inherited Apple `history_range_mismatch` remains visible and fails strict mode.

No authentic fixtures were added or changed. Existing Apple snapshots test future
filing/fact exclusion, later comparative admission and loss of future fiscal
anchors. Synthetic cases cover amendments, conflicting values, equal times,
unknown availability and date-only partial ordering. Metamorphic tests add or
change future observations, including conflicting annual windows, and require
the earlier admitted periods and revision groups to remain unchanged. All
Phase 0A–0D regression tests remain mandatory. CI has no live SEC dependency.

### Scope, limitations and technical debt

SEC acceptance remains the project's availability **proxy**, not proof of the
exact instant every market participant could see a filing. This boundary prevents
later-accession evidence from entering an earlier derivation under that proxy.
It does not turn today's SEC snapshot into a versioned historical archive.
Company Facts and submissions fields can be corrected or changed between
snapshots. Original filing-level metadata availability is assumed for the linked
fields; current issuer attributes are explicitly withheld. The API emits a
`snapshot_metadata_proxy` diagnostic so this limitation remains visible.

Uncertain availability, incomplete source coverage, absent fiscal anchors and
unavailable original instance contexts still limit results. First/latest are
relative to the loaded evidence set. Audit sections intentionally contain future
data and must remain separate from modeling inputs. Full exports repeat source
objects for auditability and can be large. There is no persistence or resolver
that chooses a canonical financial metric.

Technical debt includes versioned historical metadata snapshots, finer evidence
timing, original instance-context validation, more issuer/revision fixtures,
compact provenance references and bounded export sizes. A proposed next phase is
to specify a narrowly scoped metric-resolution contract with explicit concept
mapping and conflict handling, before implementing any metric winners. No such
mapping, resolver, derived quarters, ratios, prices, trading or GUI is included.
