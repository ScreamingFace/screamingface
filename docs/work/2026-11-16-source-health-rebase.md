---
ticket: OME-1309
stack: scoreboard
status: done
started: 2026-11-16
finished: 2026-11-16
---

# Source health rebase and validation

## Intent
Rebase PR #1749 onto current main after #1731 merged, as requested by the owner, and validate before pushing. Preserve the approved source-health behavior and all reviewed history fixes.

## Planned changes
Replay only the three source-health commits after their original history base onto origin/main. Resolve integration conflicts, preserve the prior history approval record, and keep exact-file approval for the source-health visibility fields. Retarget the existing draft PR to main after validation.

## Test plan
Run the full scoreboard and repository gates without bypasses; run source-health, history and migration regressions on disposable PostgreSQL. Inspect mixed healthy/unchecked/recovered source states at desktop and mobile sizes in light and dark themes. Compare rebased changes with the original feature commits.

## Acceptance
Only source-health changes remain in the PR; current main's history fixes are retained; tests and local UI checks pass. Push with an explicit lease on the previous head. No live database writes or merge.

## Outcome
Rebased the three source-health commits onto origin/main at 95f172afd. The two transport fixes replay unchanged; the feature commit retains both main's accessibility CSS and source-status rules. Archived the history test approval record before activating the existing source-health approval. History route, history writer and history regression tests match main byte for byte.

The new source-health test harness initially failed because #1731 moved comparisonNote to main.js. Loaded that real helper; all existing assertions remain unchanged. Full scoreboard and repository gates pass without bypasses. All 40 PostgreSQL source-health/history/migration/visibility cases pass, as do 50 focused network/DNS/CLI tests. Portal source-health checks also pass in UTC+14.

Inspected 1440px and 390px renders in both themes with illustrative mixed community and external rows. Source notices, first-failure dates, recovered states and history links render correctly. On mobile, inspected the Source column after scrolling the existing table; no page-wide overflow. The long preview board name crowds the existing mobile header/theme toggle, outside the source-health changes. No browser errors; localhost analytics warnings only. Screenshots and preview fixtures remain outside the repository.

No live database writes, source checks against live boards, deployment or merge were performed.
