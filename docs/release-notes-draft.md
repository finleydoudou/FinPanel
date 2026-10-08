# Historical record — Draft release notes — v0.1.0-alpha

> **Historical, superseded record.** The original audit/draft below predates
> publication and retains its original failures and pending actions.
> [Current release status](release-status.md): `v0.1.0-alpha` is published on
> GitHub at `30ffbbe658fbc517ec838ba499859ec05093283b`; final macOS/Linux/Windows
> CI passed with 814 tests and 0 skipped on each platform. PyPI is not published.
> The statements below are not current release blockers or installation guidance.

**Unreleased preparation; not a publication announcement.** Package version: `0.1.0a1`, explicitly mapped to the first-alpha Git label `v0.1.0-alpha`.

FinPanel provides reproducible research panels from SEC fundamentals with explicit
historical cutoffs, revision policies, source provenance, immutable snapshots, and
receipt replay. Six metrics and conservative reported/derived periods are supported
for ordinary US-GAAP operating companies. Unresolved states are retained.

WP7 adds historical transition and amendment audits, safe validation resume,
a 100-issuer purposive validation universe, and an installed offline example.
See [measured validation](release-validation.md), [support policy](api-stability.md),
and [the release checklist](release-checklist.md) before making claims about readiness.

Python 3.12 is the declared support range. macOS passed local checks and CI. Linux/Windows
CI results and the blocking Windows fixes are recorded in the
[release gate](release-candidate-gate.md). Local fixes still require CI validation.
No bank/insurance/IFRS/segment/FX/pricing capability is claimed. Current SEC aggregate
captures do not establish historical API delivery time. Original XBRL verification
has explicit coverage limits. The included example resolves three of six cells;
that demonstrates conservative states as well as usable values.

Existing WP1–WP6 call patterns remain compatible. Exact receipts remain bound to
the original software and contracts; upgrading does not rewrite old receipts.
Before publication, review platform CI and bundled issuer material notices. This
work does not create a tag, GitHub Release, or PyPI upload.
