---
ticket: OME-1576
stack: desktop
status: in_review
started: 2026-10-12
finished:
---

# studio-runtime-lock — re-lock the studio sidecar for screamingface 0.1.2

## Intent

OME-1576 (bug, no epic). The studio runtime locks `packages/screamingface` as an editable path
dependency (`screamingface[runtime]`). `e7833e35c` added `ijson>=3.4,<4` as a core dependency
of that package (`screamingface/_results/cases.py:18` imports it), but the studio lock was not
updated. `build-sidecar.sh` runs `uv sync --frozen`, which does not check freshness, so a
sidecar built from `main` installs without `ijson`. Found while reviewing the Dependabot PRs.

## Planned changes

- `apps/screamingface-studio/runtime/uv.lock`: `uv lock` only. Adds `ijson` 3.5.1 and refreshes
  the `screamingface` editable metadata (0.1.1.post9 -> 0.1.2, `ijson`, `notebook` extra).

## Test plan

- `uv lock --check` in `apps/screamingface-studio/runtime` fails on `main` (`0d36b801c` and
  `0f60a39b1`) and passes on this branch.
- The lock diff moves no package version other than the added `ijson` and the editable
  `screamingface` entry.

## Acceptance

- `uv lock --check` passes for the studio runtime.
- A `uv sync --frozen` sidecar build installs `ijson`.

## Outcome

- `uv lock --check`: fails on `main`, passes on this branch.
- Diff: +19/-2 in `uv.lock`; only `ijson` added and `screamingface` metadata refreshed.
- Not run: a full sidecar build (`build-sidecar.sh`). No CI job builds the sidecar; that is the
  owner's check.
- Out of scope: a CI step running `uv lock --check` for this directory. Dependabot PR #1344
  carries the same risk (it moves `packages/screamingface` `runtime` pins without this lock).
