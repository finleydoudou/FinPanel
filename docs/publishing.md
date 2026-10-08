# A2 publishing preparation

Package `0.1.0a2` maps to intended tag `v0.1.0-alpha.2`. Neither is
published by preparing this source tree. The existing a1 release is unchanged.

## Protected TestPyPI rehearsal

`.github/workflows/release.yml` is a manually dispatched, exact-tag-only
TestPyPI rehearsal. It checks the supplied full candidate SHA against the
checked-out tag and requires successful `Python checks` on that main commit.
That workflow runs the complete Linux/macOS/Windows matrix. Artifacts are built
from the exact tagged source and transferred within the same workflow run.
Only the isolated publishing job has `id-token: write`; it does not check out
or execute repository code. It uses OIDC, with no stored PyPI API token.
An arbitrary branch push or manual branch dispatch cannot publish.

Before dispatch, the repository owner must configure a **required reviewer** on
the GitHub `testpypi` environment, restrict deployment to the intended release
tag, and verify those protections are active. Creating a workflow does not
configure environment protection automatically. Configure a TestPyPI pending
Trusted Publisher for:

- Project: `finpanel`
- GitHub owner: `finleydoudou`
- Repository: `FinPanel`
- Workflow filename: `release.yml`
- Environment: `testpypi`

The owner must sign in to TestPyPI, satisfy its account requirements, and approve
this publisher themselves. A public project API 404 does not establish that a
name is reservable or owned. Never paste credentials into an issue or chat.
See [PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/adding-a-publisher/).

The workflow is also disabled unless repository variable
`FINPANEL_TESTPYPI_ENABLED` is explicitly set to `true`. Leave it unset during
preparation; enable it only after the owner approves the completed setup.

Stop before creating the public tag until local validation, same-commit matrix
CI, metadata review, name ownership, and account/environment setup are complete.
The intended tag is required by this workflow; preparation alone must not run it.
Review downloaded workflow artifacts and checksums before approving the protected
publishing job. Third-party actions are pinned to immutable upstream commit IDs; review updates
before changing those pins.

## Safe TestPyPI installation verification

After an authorized upload, download **only** `finpanel==0.1.0a2` from
`https://test.pypi.org/simple/` with `pip download --no-deps`. Record the download
URL and verify the downloaded hash against TestPyPI metadata and the approved
workflow artifact. Install that downloaded wheel in a fresh Python 3.12
environment, using production PyPI only for its normal dependencies. Do not use
`--extra-index-url`, an editable installation, or a local development wheel as a
substitute. Run the README/guide example, all three exports, provenance, and
snapshot replay. Compare the installed version and source receipt.

## Production remains disabled

There is deliberately **no production upload job**. Production PyPI requires
separate authorization, a protected `pypi` GitHub environment with required
reviewers and release-tag restrictions, and its own PyPI Trusted Publisher.
Any future production job must retain exact-tag/SHA/CI gates, isolated job-level
OIDC permission, immutable artifact transfer, and reviewer approval. Do not
add a production token or change the TestPyPI URL to bypass that process.
