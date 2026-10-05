# FinPanel

FinPanel is open-source research infrastructure for auditable financial fundamentals
from SEC EDGAR. Its long-term goal is reconstruction of information available at a
historical `as_of` date, with filing history and complete provenance.

**FinPanel does NOT yet provide research-grade point-in-time financial panels.**
This repository implements Phase 0A raw ingestion and Phase 0B historical filing
coverage, explicit availability precision, and filing-level as-of filtering.
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
- `models/`: dataclasses for filings, observations, source identities and issues.
- `cache/file.py`: raw JSON objects keyed by SHA-256; versioned retrieval metadata
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
  from `end`, filing date, fiscal year or frame. There is no submissions join yet.
- Fiscal year end comes from current submissions entity metadata. It is not
  independently validated as the fiscal year end at each historical filing.
- Acceptance timestamps retain supplied timezone information. A timestamp without
  an offset stays naive; no timezone is guessed.
- No taxonomy harmonization, period normalization, revision/restatement resolution,
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

Remaining work includes broader historical-company fixture coverage, independent
filing-header/dissemination validation, cache snapshot manifests across live
retrievals, and cross-process rate coordination. A suitable Phase 0C would validate
filing-level timestamps and XBRL context provenance, with a specification for
availability uncertainty. No Phase 0C, financial metric normalization, restatement
value selection, ratios, valuation, price data or trading functionality is included.
