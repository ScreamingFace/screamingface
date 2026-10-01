---
ticket: OME-1448   # already filed (Backlog, under OME-1294); not created by this unit
stack: screamingface
status: planned   # planned | in_progress | done | blocked
started: 2026-10-01
finished:
---

# report-recovery — Recover a finished Evaluation, and export with bounded memory

## Intent

A finished, paid Evaluation is lost when the notebook runs out of memory while the SDK builds the
Report (OME-1448: 11 Candidates, about $2,600, recovered only by hand on local, and not
recoverable on hosted). This unit makes every finished Evaluation recoverable on both stacks with
`sf.recover` / `screamingface recover`. It also streams `Report.export()`, and it keeps local
spilled results across a reboot. Scope is options A + D + the durable local folder (interview
answer Q1). Options B and C are later work.

## Planned changes

Spec: `docs/spec/2026-10-01-OME-1448-report-recovery/` (overview, ERD, 7 PRDs, contracts, test
plan). Open questions are resolved (Q13–Q15). Plan: `docs/plan/2026-10-01-OME-1448-report-recovery.md`
(4 PRs: A export, B local folder, C record, D recover). The plan waits for approval; no code yet.

## Test plan

See `docs/spec/2026-10-01-OME-1448-report-recovery/test-plan.md`: 91 test rows, risk-ordered.
The first RED is RS-1 (no torn record on a crash). The E2E spine is RC-E2E-1 (a killed notebook
recovers the same Report).

## Acceptance

- OME-1448 acceptance 1–4, as refined in the spec (`prd/recover-evaluation.md`,
  `prd/export-report.md`).
- You approve the spec, then the plan, in plain words before code starts.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
- **Commits:**
- **Gates:**
- **Deviations:** Linear was read with the `linear-cli` skill (API token from vault) at the user's
  explicit request, against the CLAUDE.md "Linear via MCP only" rule. The spec is a directory
  (prompt-planner layout), not a single `docs/spec/*.md` file. The branch already carries
  `OME-1448-`, because the issue existed before work started.
