# Third-party notices and evidence provenance

FinPanel's own source is distributed under the repository's MIT license. That
license does not purport to relicense third-party dependencies or issuer filings.

## Dependencies

Dependencies are installed separately; FinPanel does not vendor their source.
Their installed distributions carry their own license files and notices.

| Component | Use | Declared runtime range | License reference |
|---|---|---|---|
| HTTPX | SEC HTTP transport, timeouts, response handling | `>=0.28,<0.29` | [BSD-3-Clause](https://github.com/encode/httpx/blob/master/LICENSE.md) |
| simplejson | Exact decimal JSON reading/writing | `>=3.19,<5` | [MIT or AFL-2.1](https://github.com/simplejson/simplejson/blob/main/LICENSE.txt) |
| PyArrow | Typed Parquet and Arrow interchange | `>=18,<24` | [Apache-2.0 and bundled-component notices](https://github.com/apache/arrow/blob/main/LICENSE.txt) |
| tzdata | IANA timezone fallback on systems without zone data | `>=2024.1` | [Apache-2.0 package metadata](https://pypi.org/project/tzdata/) |
| DuckDB | Local analytical export and read-back | `>=1.5,<2` | [MIT](https://duckdb.org/faq) |

Development-only pytest, Ruff, build, and build-backend setuptools identify MIT
licenses in their installed metadata. These are not added as runtime dependencies.
No dependency was removed: all existing runtime dependencies have exercised uses. The added first-party tzdata
fallback supplies the SEC local timezone on platforms without a system IANA database.
No assertion is made that every allowed dependency combination was tested; see
[the support audit](docs/api-stability.md) for actual versions.

This inventory records upstream licensing information, not a legal opinion about
all downstream redistribution arrangements. If dependencies are bundled into a
standalone binary, preserve their complete distributed notices, including transitive
components; the short table above does not replace them.

## Authentic SEC evidence

Frozen evidence comes from the official SEC hosts `data.sec.gov` and `www.sec.gov`.
Each fixture manifest records its source URL, accession where applicable, retrieval
time, original byte hash, and the lossless compressed-transport hash. Small regression
captures and the packaged HRB example are source material for reproducible research;
they are not authored by FinPanel. Public availability through EDGAR is not a blanket
claim that every issuer-authored narrative, attachment, image, or trademark is public
domain. FinPanel claims no ownership or endorsement over that material.

WP7 includes HRB, Mattel, and Kraft Heinz aggregates and two issuer narrative filings.
The full source URLs and hashes live in `tests/fixtures/release/manifest.json`.
The installed onboarding example contains HRB JSON responses only, with its separate
`finpanel/example_data/manifest.json`. Lossless gzip is transport, not altered evidence.
Synthetic test mutations are identified as synthetic and do not replace raw captures.

The broader Tier B SEC corpus remains local and ignored; it is excluded from wheel,
source distribution, and Git. Before an actual public release, review the specific
bundled issuer-authored narrative fixtures and the intended distribution context.
This preparation does not grant rights beyond those held by the original sources.
