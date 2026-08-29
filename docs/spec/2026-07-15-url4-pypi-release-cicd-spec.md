# Spec — url4 SDK PyPI release CI/CD (OME-465)

## Problem

`packages/url4` is a pure-Python SDK (hatchling + uv, `requires-python>=3.12`, ~96% test
coverage). release-please already registers it (`release-please-config.json` + manifest,
python release-type, `url4-v*` tags) and `url4-tests.yml` gates PRs. But:

1. **No publish workflow reacts to the `url4-v*` tag** — releases are cut (tag
   `url4-v0.1.0` exists) yet nothing ships to PyPI.
2. **The package lacks PyPI metadata** — no README (long description), no LICENSE file in
   the dist, no `py.typed` (so downstreams get no types), no classifiers / project URLs.
3. **No packaging-validation gate** — a broken build or bad metadata is only discovered at
   release time.

## Goals

- A secure, standard PyPI publish lane triggered by release-please's `url4-v*` tag.
- A package that presents correctly on PyPI (name, description, README, license, links)
  and ships type information.
- Packaging breakage caught on every PR, not at release.
- Consistency with the repo's existing release conventions (`aigateway`).

## Non-goals

- Publishing anything now. This lands as a PR; the first real publish is an owner decision.
- Changing url4's library code or its runtime behavior (that is OME-397's domain).
- TestPyPI staging (can be added later; omitted to keep the lane simple and honest).

## Design

### Publish authentication — Trusted Publishing (OIDC)

Use PyPI **Trusted Publishing** (OpenID Connect) via `pypa/gh-action-pypi-publish`, not a
stored API token. GitHub mints a short-lived, workflow-identity-bound OIDC token that PyPI
exchanges for upload credentials. Rationale (DevOps `ci-cd.md`, `security-devsecops.md`):

- **No long-lived secret** to leak, rotate, or scope — the #1 CI credential-exfil target.
- Token is bound to `repo + workflow + environment`; unusable elsewhere and expires in
  minutes.
- Enables **PEP 740 digital attestations** automatically (provenance: "this artifact was
  built by our pipeline from this commit").

Trade-off: requires one-time owner setup on PyPI (a Trusted Publisher) + a GitHub
Environment. That setup is out-of-band and documented as an owner action; the workflow is
correct and mergeable before it exists (it simply cannot publish until then).

### Release trigger — release-please (already wired)

Mirror `aigateway`: conventional commits drive release-please's per-component release PR;
merging it bumps `packages/url4/pyproject.toml`, updates the changelog, and pushes tag
`url4-v<version>`. `release-url4.yml` triggers `on: push: tags: ["url4-v*"]` (plus
`workflow_dispatch` for manual re-runs). This keeps SemVer discipline and changelog
automation, and matches the reviewer's mental model of the repo.

### Publish workflow shape — build once, promote the artifact

Three jobs, mirroring `release-aigateway.yml`'s `verify` guard and the PyPA-recommended
build/publish split:

1. **verify** — recompute the version from the tag and assert it equals
   `packages/url4/pyproject.toml`'s version (fail otherwise). Guards against a mistagged or
   drifted release.
2. **build** — `uv build` (sdist + wheel) once, `twine check --strict`, upload the `dist/`
   as an artifact. One immutable artifact is what gets published.
3. **publish-pypi** — `environment: pypi` (protection point), `permissions: id-token:
   write` (OIDC), download the artifact, `pypa/gh-action-pypi-publish`. No rebuild → the
   bytes that were validated are the bytes that ship. Attestations default-on.

### Package metadata

Follow current packaging standards (PEP 621 / PEP 639 / PEP 561):

- `readme = "README.md"` — a new README serves as the PyPI long description.
- `license = "Apache-2.0"` (SPDX expression) + `license-files = ["LICENSE"]`; copy the root
  Apache-2.0 text into the package so the sdist/wheel carry it. Omit the deprecated
  `License ::` trove classifier (superseded by the SPDX field).
- `authors`, `keywords`, `classifiers` (Development Status, audience, Python 3.12/3.13,
  OS-independent, `Typing :: Typed`), `[project.urls]` (Homepage/Repository/Issues).
- `src/url4/py.typed` marker so type checkers consume url4's inline types.

### Test gate hardening

Add to `url4-tests.yml`: (a) `3.13` to the Python matrix so the versions claimed in
`classifiers` are actually tested; (b) a `build` job running `uv build` + `twine
check --strict` so packaging/metadata regressions fail a PR. Coverage gate stays at 95%
(actual ~96%), consistent with `sdlc.local.md`.

### Dependabot

Add the `uv` ecosystem for `/packages/url4` (weekly, grouped) so the SDK's dependencies
stay current like the apps'.

## Security & failure story

- **Least privilege:** workflow default `permissions: contents: read`; only `publish-pypi`
  gets `id-token: write`; no `packages:`/`contents: write` needed.
- **No untrusted-code publish:** publish triggers only on maintainer-pushed `url4-v*` tags
  (and manual dispatch), never on PRs.
- **Rollback:** PyPI releases are immutable and cannot be re-uploaded; recovery from a bad
  release is a new patch version (yank the bad one on PyPI). The `verify` job + `twine
  check` gate exist to prevent shipping a broken artifact in the first place.
- **What breaks if the OIDC trust is missing:** `publish-pypi` fails at the publish step
  with an auth error; `verify`/`build` still pass, so packaging validity is confirmed even
  before the owner configures PyPI.

## Owner actions (out of band, before first publish)

1. Reserve the `url4` PyPI project name; add a Trusted Publisher →
   `ScreamingFace/screamingface`, workflow `release-url4.yml`, environment `pypi`.
2. Create the `pypi` GitHub Environment (optionally required reviewers / branch limits).
