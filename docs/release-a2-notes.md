# FinPanel v0.1.0-alpha.2

Prepared release notes; publication requires separate authorization.
Python package version: `0.1.0a2`. Python 3.12 is required.

Alpha.2 aligns public documentation and package metadata, and adds protected
TestPyPI rehearsal and production PyPI release infrastructure using OIDC.
Financial/accounting semantics, metric contracts, historical cutoffs, revision
selection and provenance behavior are unchanged from the validated A2 software.
The point-in-time panels, pinned evidence snapshots, explicit unresolved states,
CSV/Parquet/DuckDB exports and reproducibility receipts remain available.
Exact replay requires the matching software version and captured evidence.

Validation covers a specified 100-issuer US-GAAP population: 24,000 financial
cells, 255/255 independent golden expectations, and zero unexpected mismatches
within that population. Scalar coverage was 69.61%; this measures resolution
coverage, not accuracy. The validated A2 software passed 814 tests, with zero
skips, on macOS, Linux and Windows. Final release infrastructure and packaged
documentation changes require fresh exact-commit CI before publication.

This is experimental alpha software, not stable software or a claim of universal
correctness. Banks, insurers, IFRS normalization, segment aggregation, FX
normalization, prices and returns remain outside scope. Original-XBRL,
extension-heavy and dimension-heavy evidence coverage remains incomplete.
See [validation evidence](https://github.com/finleydoudou/FinPanel/blob/main/docs/release-validation.md).
The existing a1 tag, release and assets remain unchanged.
