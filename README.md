# FinPanel

FinPanel is open-source research infrastructure for auditable financial fundamentals
from SEC EDGAR. Its long-term goal is reconstruction of information available at a
historical `as_of` date, with filing history and complete provenance.

**FinPanel does NOT yet provide research-grade point-in-time financial panels.**
This repository implements the Phase 0A ingestion foundation. Authentic SEC
snapshots for AAPL, MSFT, WMT and NVDA were captured on 2026-10-05 and are tested
offline alongside separate, explicitly synthetic edge-case fixtures. No Phase 0B
features or point-in-time resolver are implemented.

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
- `sec/submissions.py`: recent filing column arrays to independent filing records.
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
history files. This phase parses **recent only** and preserves those references in
metadata; it does not claim a complete historical filing inventory. Company Facts
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

- No selection, deduplication or amendment merging. Input array order is retained;
  taxonomy/concept/unit keys are traversed in sorted order.
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

Phase 0B planning should start with historical submissions traversal,
filing-level timestamp/context validation and a documented
availability policy. Do not infer point-in-time availability from this ingestion
layer. No Phase 0B features have been implemented here.
