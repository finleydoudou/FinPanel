# Draft release notes — v0.1.0-alpha.1

**Unreleased preparation; not a publication announcement.** Package version: `0.1.0a1`.

FinPanel provides reproducible research panels from SEC fundamentals with explicit
historical cutoffs, revision policies, source provenance, immutable snapshots, and
receipt replay. Six metrics and conservative reported/derived periods are supported
for ordinary US-GAAP operating companies. Unresolved states are retained.

WP7 adds historical transition and amendment audits, safe validation resume,
a 100-issuer purposive validation universe, and an installed offline example.
See [measured validation](release-validation.md), [support policy](api-stability.md),
and [the release checklist](release-checklist.md) before making claims about readiness.

Python 3.12 is the declared support range. macOS is tested locally. Linux/Windows
CI is configured but its WP7 results require the later authorized Git synchronization.
No bank/insurance/IFRS/segment/FX/pricing capability is claimed. Current SEC aggregate
captures do not establish historical API delivery time. Original XBRL verification
has explicit coverage limits. The included example resolves three of six cells;
that demonstrates conservative states as well as usable values.

Existing WP1–WP6 call patterns remain compatible. Exact receipts remain bound to
the original software and contracts; upgrading does not rewrite old receipts.
Before publication, review platform CI and bundled issuer material notices. This
work does not create a tag, GitHub Release, or PyPI upload.
