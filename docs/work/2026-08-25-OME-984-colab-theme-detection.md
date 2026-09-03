---
ticket: OME-984
stack: screamingface
status: done
started: 2026-08-25
finished: 2026-08-25
---

# OME-984 — Colab theme detection for every notebook surface

## Intent

Complete OME-955's host-theme contract for the independent notebook style blocks it did not cover,
without changing their SFDS values or their visible design.

## Planned changes

- Shared notebook theme-rule generation.
- Leaderboard, notice, and connection-logo theme wiring.
- One cross-surface theme contract test.
- This unit's task, spec, plan, and work records.

## Test plan

- RED: five independent Leaderboard/notice/logo selectors lack Colab light and dark rules.
- GREEN: all six theme blocks use the shared host matrix.
- Focused presentation tests and the complete ScreamingFace gate suite remain green.

## Acceptance

- Colab's explicit theme wins over the browser fallback on every notebook surface.
- JupyterLab and VS Code behavior remains unchanged.
- No visual token values change.

## Outcome

- **Actual files:** shared theme-rule generation; Leaderboard, notice, and connection-logo wiring;
  a parameterized six-block contract test; and this unit's task/spec/plan/work records.
- **Commits:** `fix(screamingface): unify notebook theme detection`; OME-984 artifact follow-up.
- **Gates:** 101 focused tests passed; complete `screamingface` gate passed Ruff, formatting,
  Pyright, full pytest at the 95% coverage floor, notebook checks, package build, and distribution
  validation.
- **Deviations:** implementation was first completed on the already-merged OME-955 branch; it was
  relocated unchanged onto this fresh `origin/main` worktree before opening a PR.
