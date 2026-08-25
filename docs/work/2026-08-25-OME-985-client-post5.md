---
ticket: OME-985
stack: screamingface
status: done
started: 2026-08-25
finished: 2026-08-25
---

# OME-985 — Release the ScreamingFace client as 0.1.1.post5

## Intent

Make the Client changes merged after post4 installable as `0.1.1.post5`, without widening this
manual release bump into source, dependency, or release-automation changes.

## Planned changes

- `packages/screamingface/pyproject.toml` — version only.
- `packages/screamingface/uv.lock` — matching local package version.
- This unit's task, spec, plan, and work records.

## Test plan

- Manifest and lockfile agree on `0.1.1.post5`.
- Built distribution metadata reports `0.1.1.post5`.
- Complete ScreamingFace quality gates pass.

## Acceptance

- The installable Client version is `0.1.1.post5`.
- No source, dependency, API, or runtime behavior changes.

## Outcome

- **Actual files:** Client manifest and lockfile version entries, plus this unit's task,
  spec, plan, and work records.
- **Commits:** `chore(screamingface): release the client as 0.1.1.post5`
- **Gates:** lockfile check and the complete ScreamingFace gate suite passed (append-only,
  Ruff, Pyright, pytest with 95% coverage, notebook validation, package build, and
  distribution validation).
- **Deviations:** the fresh worktree initially lacked notebook extras, so the declared
  development dependencies were installed into its private `.venv`. The local `uv`
  version also proposed an unrelated `ptyprocess` marker normalization; that incidental
  lockfile change was removed, and `uv lock --check` still passed.
- **Follow-up:** release-please remains to be reconciled with the manual post-release sequence.
