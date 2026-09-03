---
ticket: OME-824
stack: screamingface
status: in_progress
started: 2026-08-13
finished:
---

# OME-824 — Realign screamingface release baseline past manually-published PyPI 0.1.1

## Intent

The `packages/screamingface` PyPI release lane is red and cannot self-heal. Both `0.1.0` and
`0.1.1` were uploaded to PyPI manually (17:37:34Z and 17:48:52Z) before PR #553 merged at
17:55:23Z and pushed tag `screamingface-v0.1.0`. The resulting
[run 31728158888](https://github.com/ScreamingFace/screamingface/actions/runs/31728158888) passed
`verify` and `build`, then failed `publish-pypi` with PyPI's immutability rejection:

```
400 File already exists ('screamingface-0.1.0-py3-none-any.whl',
with blake2_256 hash '5b202898501ee26a912688f353b6a589667a0c386ff3912e0838a37e70e3ea8a').
```

Trusted Publishing is not at fault — the run obtained an OIDC token and Sigstore signed the
artifacts (transparency-log entries created) before the upload was refused.

`origin/main` records the component at `0.1.0` while PyPI is one version ahead at `0.1.1`, so
the next release-please run would propose `0.1.1` and fail identically. Moving the baseline to
`0.1.1` makes the next automated release `0.1.2` — which will be the first version ever
published by the Trusted Publishing pipeline.

## Planned changes

- `.release-please-manifest.json` — `packages/screamingface`: `0.1.0` -> `0.1.1`
- `packages/screamingface/pyproject.toml` — `version`: `0.1.0` -> `0.1.1`
- `packages/screamingface/CHANGELOG.md` — add a `0.1.1` entry recording that `0.1.0` and
  `0.1.1` were published outside CI
- `docs/tasks/2026-08-13-sync-screamingface-pypi-version.md` — issue mirror

Commit type is `fix(screamingface):` so release-please proposes `0.1.2` rather than sitting
idle on a `chore:`.

## Decisions (owner-approved)

- **No backfill `screamingface-v0.1.1` tag.** `release-screamingface.yml` triggers on
  `push: tags: ["screamingface-v*"]`; that tag would immediately attempt to publish `0.1.1`
  and reproduce the same `400`. The manifest — not the tag — determines the next version.
- **No `skip-existing: true`** on the publish step. A duplicate version stays a loud failure
  so an out-of-band upload is never silently masked.

## Test plan

No product behaviour changes, so there are no new unit tests. Verification is the release
machinery itself:

- `uv build` + `scripts/check_distribution.py` + `twine check --strict` still pass (the same
  gates `screamingface-tests.yml` and the release `build` job run).
- Built artifact filenames carry `0.1.1`.
- The tag-vs-manifest guard in `release-screamingface.yml` `verify` would agree: the awk
  extraction of `version` from `pyproject.toml` returns `0.1.1`.
- `.release-please-manifest.json` remains valid JSON with every other component untouched.

## Acceptance

- `main` reports `0.1.1` in both `.release-please-manifest.json` and `pyproject.toml`.
- release-please opens a `screamingface 0.1.2` release PR.
- Merging that PR drives `release-screamingface.yml` to a green `publish-pypi`.

## Outcome

- **Actual files:** as planned, plus `packages/screamingface/uv.lock` (the lock pins the
  workspace member's own version, so the bump propagates into it — one line, version only).
  - `.release-please-manifest.json`
  - `packages/screamingface/pyproject.toml`
  - `packages/screamingface/CHANGELOG.md`
  - `packages/screamingface/uv.lock`
  - `docs/tasks/2026-08-13-sync-screamingface-pypi-version.md`
  - `docs/work/2026-08-13-OME-824-sync-screamingface-pypi-version.md`
- **Commits:** `fix(screamingface): realign release baseline with published PyPI 0.1.1`
- **Gates:** no unit tests apply (no product behaviour change). Ran the release `build` job's
  own gates against the bumped tree:
  - `uv build` -> `screamingface-0.1.1.tar.gz` + `screamingface-0.1.1-py3-none-any.whl`
  - `scripts/check_distribution.py` -> exit 0
  - `twine check --strict dist/*` -> PASSED (both artifacts)
  - `release-screamingface.yml` `verify` awk guard extracts `0.1.1` from `pyproject.toml`
  - `.release-please-manifest.json` parses; all five other components unchanged
- **Deviations:**
  - The backfill `screamingface-v0.1.1` tag named in the originally approved option was
    **dropped**. `release-screamingface.yml` triggers on `push: tags: ["screamingface-v*"]`,
    so creating it would have immediately attempted to publish `0.1.1` and reproduced the same
    `400 File already exists`. The manifest alone determines the next proposed version, so the
    tag was unnecessary as well as harmful.
  - `uv.lock` was not in the planned file list (see above).
