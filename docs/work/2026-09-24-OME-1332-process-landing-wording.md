---
ticket: OME-1332
stack: repo
status: done
started: 2026-09-24
finished: 2026-09-24
---

# OME-1332 — Fix stale `repo`-for-process-work label wording

## Intent

After `repo` issues migrated to `cross-unit/repo-dev-processes` (OME-1331), the mandatory-component
rule text still named a bare `repo` for process work. Correct it so docs match where process work
actually lands.

## Changes

- `CLAUDE.md` rule 1 + `.claude/task-board.local.md` mandatory-component rule now read
  `app/*` / `pkg/*` / `cross-unit/*` (e.g. `cross-unit/repo-dev-processes`).

## Outcome

- **Files:** CLAUDE.md, .claude/task-board.local.md. Docs-only; no behavior change.
- **Gates:** SHARED-LOOP untouched; `check_loop_parity.py` green.
