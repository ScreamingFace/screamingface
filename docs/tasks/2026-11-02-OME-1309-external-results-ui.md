---
id: OME-1309
linear_url: https://linear.app/openmined/issue/OME-1309/e20-submissions-from-other-leaderboards-epic
status: Backlog
priority: Medium
labels: [product-feature, scoreboard, human, deferred]
created: 2026-09-23
closed:
---

# E20 — Submissions from other leaderboards

Linear remains authoritative; read on 2026-11-02. This PR implements the first
external-row display using existing imported baselines. It does not close E20:
manual editing/history, refresh/source-health handling and broader comparability
policy remain open. On 2026-11-03 the owner chose a shared table and normal ranks. No Linear writes were authorized.

See `docs/spec/2026-11-02-OME-1309-external-rows.md` and
`docs/work/2026-11-02-OME-1309-external-rows.md`.


## Current work, 2026-11-12

The manual-edit/history item is implemented in PR #1731 and undergoing review corrections;
source-health handling is a separate draft #1749. E20 remains open.

- History: `docs/spec/2026-11-10-OME-1309-external-history.md`, `docs/work/2026-11-10-OME-1309-external-history.md`.
- Source/shared-note layout: `docs/spec/2026-11-10-OME-1309-history-layout.md`, `docs/work/2026-11-10-OME-1309-history-layout.md`.
- Review corrections: `docs/work/2026-11-12-OME-1309-history-review.md`.

Current deferred-work ledger: docs/work/2026-11-18-external-results-deferred.md
Completed history ledger: docs/work/2026-11-12-OME-1309-history-review.md

## On hold, 2026-11-18

Filip deprioritized E20. Linear is Backlog with the deferred label; resume only after reprioritization. PRs #1731 and #1729 are merged. PR #1749 is refreshed against main for preservation and held in draft. Remaining imports, source-check rollout and live acceptance are paused.
