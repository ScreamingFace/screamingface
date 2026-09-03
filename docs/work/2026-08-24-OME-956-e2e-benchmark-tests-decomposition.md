---
ticket: OME-956
stack: repo
status: done
started: 2026-08-24
finished: 2026-08-24
---

# OME-956 — decompose the e2e benchmark-test epic into SDLC-unit sub-issues

## Intent

OME-956 (R1–R11, five boards, harness + failure suite + goldens + surface pin) is
epic-sized; implementation needs one SDLC unit per independently-landable piece, with the
R10 refusal-vocabulary prerequisite made explicit as a blocker instead of prose.

## Planned changes

- File 5 sub-issues under OME-956 in Linear + create their `docs/tasks/` mirrors.

## Test plan

- n/a — filing/process unit, no code.

## Acceptance

- Each sub-issue: one landing label (`py-screamingface`), one actor, one who-acts,
  priority, parent OME-956; goldens ticket blocked-by the R10 ticket and the harness
  ticket; failure ticket blocked-by the harness ticket.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** this ledger + 5 mirrors in `docs/tasks/`
- **Commits:** (mirrors to land via a docs PR — not committed to main in-session)
- **Gates:** n/a
- **Deviations:** none. Sub-issues filed: OME-959 (R10 refusal split, blocks goldens),
  OME-961 (replay harness, R1/R2/R11), OME-962 (failure paths, R7, blocked by 961),
  OME-963 (public surface pin, R6), OME-964 (goldens, R3/R4/R5/R11, blocked by 959+961,
  deferred on owner's paid runs).
