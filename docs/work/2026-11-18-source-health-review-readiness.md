---
ticket: OME-1309
stack: scoreboard
status: done
started: 2026-11-18
finished: 2026-11-18
---

# Source health review readiness

## Intent
Prepare PR #1749 for review after benchmark revision history (#1892) and weight labels
(#1899) merged. Filip authorized rebasing, renumbering, validation and leaving draft.

## Planned changes
Rebase the existing source-health branch on current main. Rename the source-health
migration to 0025, depending on 0024_benchmark_revisions. Update migration test targets
and runbook references while preserving existing assertions. Add a populated upgrade
regression proving revision history survives the source-health migration.

## Test plan
Run scoreboard and repository gates against origin/main, focused PostgreSQL migration
and source-health regressions, and inspect mixed-source local previews at 1440px and
390px in light and dark themes. Use a headless browser and close it afterward.

## Acceptance
Current main remains intact; the migration chain has one head; gates and visual checks
pass. Push with an exact lease on 3cabc3067edc89b330dece72838ca98e20bdeeae, update the PR
body and mark it ready for review. Deployment and live source checks follow merge.

## Outcome
Rebased all four source-health commits onto origin/main at bd57b53b6 without conflicts.
Renamed the migration and test file to 0025 and changed its dependency to
0024_benchmark_revisions. Updated the operator runbook. The existing test's assertions
are unchanged; only migration targets move. Added a populated upgrade regression
proving old benchmark revision metadata survives.

Validation:
- Both populated SQLite migration tests failed before the migration change, then passed.
- Scoreboard and repository gates pass against origin/main, including the existing
  exact-file test approval and preservation checks. No bypasses.
- 30 PostgreSQL source-health/history/visibility/migration tests pass.
- Full PostgreSQL migration chain applies through 0025; one head; model autodetection
  reports no changes.
- Headless preview inspected at 1440px and 390px in both themes. Six mixed rows,
  two unchecked notices, four source links and the history link remain correct.
  The table scrolls on mobile with no page-wide overflow. The previously documented
  long-title header crowding is unchanged. No browser errors, only localhost analytics
  warnings. Screenshot artifacts are outside the repository.
- Browser session closed after validation. Local fixture preview remains available
  at http://127.0.0.1:9194/benchmark.html?id=demo.

No production data was read or changed. Deployment, live source checks and recurring
scheduling remain rollout work; OME-1309 remains open. This step makes #1749 ready
for review, not merged or deployed.
