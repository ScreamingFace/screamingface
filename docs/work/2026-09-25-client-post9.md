---
ticket: OME-1338
stack: screamingface
status: done
started: 2026-09-25
finished: 2026-09-25
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

## Outcome

- **Actual files:** `packages/screamingface/pyproject.toml` (version `0.1.1.post8` →
  `0.1.1.post9`), `packages/screamingface/uv.lock` (matching `screamingface` entry), this
  work ledger, and `docs/tasks/2026-09-25-OME-1338-client-post9.md`. Change set matches PR
  #851 (post8) exactly; `CHANGELOG.md` untouched.
- **Commits:** `12bc3301` chore(screamingface): release the client as 0.1.1.post9 ·
  `2ed08679` docs(screamingface): file OME-1338 task mirror and backfill the ledger ticket
  → squash-merged as `1c22a64a6` (PR #1068). Close-out (this Outcome + mirror status Done)
  lands in a follow-up docs PR on branch `OME-1338-close`.
- **Gates:** `uv run .claude/scripts/run_gates.py screamingface` — ALL GATES GREEN
  (append-only check, ruff check, ruff format --check, pyright, pytest
  `--cov=screamingface --cov-fail-under=95`, check_notebooks, `uv build`,
  check_distribution). CI green on PR #1068 (test 3.12 + 3.13, golden-replay, CodeQL).
  Release workflow run `36113839220` (tag `screamingface-v0.1.1.post9`): verify + build +
  publish-pypi all success. PyPI now serves `0.1.1.post9` as latest.
- **Deviations:** (1) `uv sync` under local `uv 0.7.15` downgraded the lockfile format
  (revision 3 → 2) and rewrote unrelated markers; reverted and edited only the single
  `screamingface` version line to match the post8 change shape. (2) The version-bump commit
  landed before the merge/publish, so this Outcome + the mirror's Done status close in a
  small follow-up docs PR rather than in the original PR (prior post-releases filled the
  Outcome pre-PR). (3) GitHub automation did not auto-transition OME-1338 (branch/PR used
  `Refs:`, not the automation's branch pattern); moved to Done manually via the close
  comment.
