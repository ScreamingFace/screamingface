---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: screamingface
status: in_progress
started: 2026-09-25
finished:
---

# client-post9 — Release the ScreamingFace client as 0.1.1.post9

## Intent

Make the Client changes merged after `0.1.1.post8` installable as `0.1.1.post9`, without
widening this manual release bump into source, dependency, or release-automation changes.
Publish the result to PyPI via the `release-screamingface` workflow (tag
`screamingface-v0.1.1.post9`). Same shape as post1–post8 (most recently OME-1137 / PR #851).

## Planned changes

- `packages/screamingface/pyproject.toml` — version only (`0.1.1.post8` → `0.1.1.post9`).
- `packages/screamingface/uv.lock` — matching local `screamingface` package version.
- This unit's work ledger and (at PR-open) task mirror.

## Test plan

- Manifest and lockfile agree on `0.1.1.post9`.
- `tests/test_version.py` passes: `sf.__version__` (installed distribution metadata) equals
  the `pyproject.toml` version after `uv` re-syncs the editable install.
- Built distribution metadata reports `0.1.1.post9` (`scripts/check_distribution.py`).

## Acceptance

- The installable Client version is `0.1.1.post9`.
- No source, dependency, API, or runtime behavior changes.
- `0.1.1.post9` tagged `screamingface-v0.1.1.post9` and published to PyPI (publish may block
  on the one-time PyPI Trusted-Publisher owner setup — reported explicitly, not worked around).

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
- **Commits:**
- **Gates:**
- **Deviations:**
