---
ticket: OME-1576
stack: desktop
status: done
started: 2026-10-12
finished: 2026-10-12
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
- `build-sidecar.sh` on this branch (macOS, PyInstaller cache in a scratch dir): builds; the
  bundle has `_internal/ijson`; `screamingface-runtime --help` runs; in the synced venv
  `import ijson, screamingface._results.cases` works (`ijson` 3.5.1).
- Combined with Dependabot #1266 (multidict 6.9.1, same lock): merges cleanly in either order;
  the result passes `uv lock --check` and `uv sync --locked`.
- Out of scope: a CI step running `uv lock --check` for this directory. Dependabot PR #1344
  carries the same risk (it moves `packages/screamingface` `runtime` pins without this lock).
