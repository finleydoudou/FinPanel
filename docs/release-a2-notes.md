# FinPanel 0.1.0a2 preparation notes

Intended Git label: `v0.1.0-alpha.2`. Not a publication announcement.

This refresh aligns package metadata and the embedded README with the corrected
public GitHub installation instructions, researcher guide and release-state
explanation. Absolute GitHub documentation links support PyPI README rendering.
It is not a major feature release. No financial/accounting semantics, metric
contracts, revision/as-of selection or provenance behavior changed. Versioned
receipts still require their original matching software for exact replay.

The existing a1 release, tag and assets remain unchanged. A2 needs full local
regression, three-platform exact-commit CI, separate clean wheel/sdist installs,
metadata/README checks and checksums. TestPyPI is conditional on those gates and
Trusted Publishing setup. Production PyPI and an a2 GitHub Release are not
published by this preparation task.

The prior audit remains limited to its specified 100-issuer US-GAAP population:
69.61% scalar coverage is not accuracy; zero unexpected mismatches is not a
universal correctness claim. Banks, insurers, IFRS normalization, segment/FX
normalization remain unsupported; original-XBRL and extension/dimension coverage
remain incomplete. See [validation evidence](release-validation.md).
