# Protected A2 TestPyPI rehearsal

The package candidate is immutable:
`415fea03da8b7b65e41f0bc7116c4676559cc183`, version `0.1.0a2`.
The intended final tag is `v0.1.0-alpha.2`; this rehearsal neither requires nor
creates it. A workflow-only commit on later `main` controls the rehearsal, but
must never become the package source implicitly. A1 remains unchanged.

## Manual controls

`.github/workflows/release.yml` accepts only `workflow_dispatch` on this
repository's `main`, with `candidate_sha` exactly equal to the authorized SHA
above. It rejects other input before checkout, checks out the literal authorized
SHA (not branch HEAD or user-selected source), verifies HEAD and package version,
and requires successful three-platform `Python checks` on that candidate.
`FINPANEL_TESTPYPI_ENABLED` must also equal `true`.

Fresh wheel/sdist builds run in GitHub Actions. Both distributions are checked
for name, version, Python constraint, license, URLs, classifiers, dependencies,
and exact embedded README. The run records hashes and separate package-source
and workflow SHAs in `build-provenance.json`, alongside `SHA256SUMS.txt`.
The publishing job downloads only that run's distribution artifact.
No locally prebuilt distributions are uploaded.

## Environment change and approval

The existing `testpypi` environment retains required reviewer `finleydoudou`.
For this rehearsal, add exactly one deployment policy: **branch `main`**.
Keep the existing **tag `v0.1.0-alpha.2`** policy unchanged; add no wildcard or
other branch. This permits a manual workflow from main, not automatic publication
on push: the workflow has no push trigger, accepts only the fixed candidate,
and waits for human environment approval. Self-review remains allowed so the
repository owner can both dispatch and explicitly approve; approval is still
required. The agent must not approve its own deployment on the owner's behalf.

Before approving, review the run summary and `a2-checksums` artifact, verify the
candidate SHA and package version, and confirm the endpoint is TestPyPI. Approve
only the `publish-testpypi` job for this intended run. No production environment
is added or modified.

## Trusted Publishing identity

- TestPyPI project: `finpanel`
- GitHub owner: `finleydoudou`
- Repository: `FinPanel`
- Workflow filename: `release.yml`
- Environment: `testpypi`

Only the isolated publishing job has `id-token: write`; it does not check out
repository code. Actions are pinned to immutable upstream commit IDs. Publishing
uses OIDC and the literal endpoint `https://test.pypi.org/legacy/`. No password,
API token, or long-lived publishing secret is used. See
[Trusted Publishing](https://docs.pypi.org/trusted-publishers/adding-a-publisher/).

There is no production upload job. Production PyPI, the final tag, and a GitHub
Release require separate authorization; this workflow cannot select a production
endpoint via an input. The production path remains absent and disabled.

## Verify the actual TestPyPI package

After approval and successful upload, compare TestPyPI file hashes with the
Actions provenance artifact. Download only `finpanel==0.1.0a2` from
`https://test.pypi.org/simple/` with `pip download --no-deps`. Record the real
TestPyPI download URL and hashes. Install that downloaded artifact into a fresh
Python 3.12 environment; obtain ordinary dependencies separately from production
PyPI. Do not use `--extra-index-url`, editable installs, development sources, or
local build artifacts as substitutes. Run the public Quick Start, panel,
CSV/Parquet/DuckDB exports, provenance, and receipt/snapshot replay.
