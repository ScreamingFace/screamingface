---
ticket: OME-1264
stack: screamingface-engine
status: done
started: 2026-09-24
finished: 2026-09-24
---

# OME-1264 — Restore two peer commits clobbered off the mcq-family branch

## Intent

During the post-merge stack rebase (2026-09-24), a force-with-lease push of the
rebased `OME-1264-importer-mcq-family` overwrote two commits a peer session had
pushed on top of it — the lease passed because this session had fetched the
peer's tip, so it protected nothing. The commits survive only in the peer's
worktree (`.claude/worktrees/OME-1264-mcq-fix`, detached at `6ccd5383`) and are
real fixes PR #1036's merged content lacks:
- `a2f9f6e1` — MCQ detected by solver OR the choice scorer: mmlu hides
  `multiple_choice` inside its own `@solver` wrapper, invisible to the solver
  walk, so solver-only detection would misfamily choice()-scored evals on a
  re-import.
- `6ccd5383` — json-encode scorer kwarg NAMES in generated board rows (the
  values were already json-encoded; names weren't).

This unit cherry-picks both onto main and lands them via PR.

## Planned changes

- Cherry-pick `a2f9f6e1` + `6ccd5383` (importer.py + appended tests + the mcq
  ledger note; resolve the ledger hunk against its now-closed state)

## Test plan

- The two commits carry their own appended tests; full inspect lane + gates

## Acceptance

- Both diffs present on the PR branch; inspect lane green; gates green;
  no prior test touched beyond the peers' own appended ones

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** both cherry-picks applied clean (importer.py, appended
  tests, the mcq ledger note merged into its closed state) + this ledger.
- **Commits:** cherry-picks of `a2f9f6e1` and `6ccd5383` (peer authorship
  preserved) + the ledger commit on `OME-1264-restore-mcq-fixes`.
- **Gates:** ALL GREEN, append-only clean; inspect lane 271 passed.
- **Deviations:** none. Process lesson recorded in memory: force-with-lease
  protects nothing when the lease ref was fetched AFTER the peer's push —
  before any force-push, diff the remote tip against your base for commits
  that are not yours.
