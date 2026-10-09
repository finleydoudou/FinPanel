# Protected A2 TestPyPI rehearsal

The package candidate is immutable:
`415fea03da8b7b65e41f0bc7116c4676559cc183`, version `0.1.0a2`.
The intended final tag is `v0.1.0-alpha.2`; this rehearsal neither requires nor
creates it. A workflow-only commit on later `main` controls the rehearsal, but
must never become the package source implicitly. A1 remains unchanged.

## Manual controls

The TestPyPI path in `.github/workflows/release.yml` accepts only `workflow_dispatch` on this
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
on push: the TestPyPI jobs accept only manual dispatch and the fixed candidate,
and waits for human environment approval. Self-review remains allowed so the
repository owner can both dispatch and explicitly approve; approval is still
required. The agent must not approve its own deployment on the owner's behalf.

Before approving, review the run summary and `a2-checksums` artifact, verify the
candidate SHA and package version, and confirm the endpoint is TestPyPI. Approve
only the `publish-testpypi` job for this intended run. Production uses the separately protected `pypi` environment described below.

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

Production PyPI, the final tag, and a GitHub Release require separate
authorization. No endpoint is selectable through a workflow input.

## Verify the actual TestPyPI package

After approval and successful upload, compare TestPyPI file hashes with the
Actions provenance artifact. Download only `finpanel==0.1.0a2` from
`https://test.pypi.org/simple/` with `pip download --no-deps`. Record the real
TestPyPI download URL and hashes. Install that downloaded artifact into a fresh
Python 3.12 environment; obtain ordinary dependencies separately from production
PyPI. Do not use `--extra-index-url`, editable installs, development sources, or
local build artifacts as substitutes. Run the public Quick Start, panel,
CSV/Parquet/DuckDB exports, provenance, and receipt/snapshot replay.

## Production Alpha.2 contract

The production path is separate from the fixed-source manual TestPyPI rehearsal.
Only a push of exactly `v0.1.0-alpha.2` in `finleydoudou/FinPanel` can enter
`build-production`. No manual dispatch can publish to production.
`FINPANEL_PRODUCTION_CANDIDATE_SHA` is an administrator-controlled repository
variable containing the full, reviewed final commit SHA. Set it only after the
release-only commit is created, avoiding an impossible self-referential SHA in
its own source. It is a public allowlist value, not a credential. An unset or
invalid value fails closed. Changing it requires renewed release review.

The event commit, checked-out source and authorized SHA must match; version must
be `0.1.0a2`. Successful three-platform `tests.yml` CI on that exact main commit
is required. Actions build fresh distributions, validate embedded metadata and
README, and record hashes, source/workflow SHA, run ID and attempt. The isolated
publish job downloads only the same run's named production artifacts and checks
all provenance fields, filenames, sizes, hashes, checksums and package versions
again before upload. It checks out no repository code.

The `pypi` environment must require reviewer `finleydoudou`, allow only tag
`v0.1.0-alpha.2`, and allow no branch deployments. Self-review is allowed for the
sole owner; explicit human approval remains required. TestPyPI settings are
unchanged. Only publishing jobs receive job-level `id-token: write`.
The production endpoint is fixed to `https://upload.pypi.org/legacy/` and the
pinned official PyPA action retains attestations. No persistent publishing
credential is created or stored.

Production Pending Trusted Publisher identity, on **pypi.org**:
project `finpanel`, owner `finleydoudou`, repository `FinPanel`, workflow
`release.yml`, environment `pypi`. TestPyPI uses its separate `testpypi` identity.
A public project 404 is not a name reservation or proof of future availability.
Verify the production account and all identity fields before authorizing a tag.

## Final authorization procedure — not executed during preparation

Resolve `TARGET` from the reviewed preparation report; never substitute main
implicitly. Before proceeding verify the allowlist variable, clean tree, exact
CI success and Pending Publisher configuration. These commands are a plan:

```bash
TARGET='<full reviewed final commit SHA>'
test "$(git rev-parse HEAD)" = "$TARGET"
test "$(git rev-parse origin/main)" = "$TARGET"
test -z "$(git status --porcelain)"
test "$(gh variable get FINPANEL_PRODUCTION_CANDIDATE_SHA)" = "$TARGET"
git tag -a v0.1.0-alpha.2 "$TARGET" -m 'FinPanel v0.1.0-alpha.2'
git push origin refs/tags/v0.1.0-alpha.2
```

Review the triggered production build summary and provenance. The owner then
explicitly approves the **pypi** environment, after checking tag, source SHA,
version and artifact hashes. OIDC publishes fresh workflow artifacts. Verify
production PyPI metadata, project URLs, file hashes and attestations before
creating a GitHub pre-release. Download `production-a2-distributions` and
`production-a2-checksums` from that exact workflow run; use those same files,
checksums and provenance as release attachments (never substitute local builds).

```bash
gh release create v0.1.0-alpha.2 --verify-tag --prerelease \
  --title 'FinPanel v0.1.0-alpha.2' --notes-file docs/release-a2-notes.md \
  release-artifacts/finpanel-0.1.0a2-py3-none-any.whl \
  release-artifacts/finpanel-0.1.0a2.tar.gz \
  release-artifacts/SHA256SUMS.txt release-artifacts/build-provenance.json
```

Finally, create a fresh Python 3.12 environment outside the checkout, install
`finpanel==0.1.0a2` from `https://pypi.org/simple/` without caches or local
artifacts, record source and version, and run import/CLI/public Quick Start,
panel/CSV/Parquet/DuckDB/provenance/receipt/replay checks. Do not redo a successful
upload, move the tag, or overwrite existing releases on failure; report it.
