---
id: OME-1325
linear_url: https://linear.app/openmined/issue/OME-1325/accept-and-store-the-cache-saved-cost-and-rank-on-the-reproduction
status: done
type: task
priority: high
labels: [scoreboard, agentic, deferred]
parent: OME-1251
created: 2026-09-23
closed: 2026-09-25
---

# Accept and store the cache saved cost

Scoreboard half of decision D5 on epic `OME-1251`. The client half is `OME-1326`.

Ledger: `docs/work/2026-09-24-OME-1325-store-cache-saved-cost.md`.
Spec: `docs/spec/2026-09-24-OME-1325-store-cache-saved-cost.md`.
Plan: `docs/plan/2026-09-24-OME-1325-store-cache-saved-cost.md`.

**This mirror was created late, at the close.** It was never created at PR-open.

- 2026-09-23: filed with two phases: store (ungated) and rank (gated on `OME-1287`).
- 2026-09-24: store phase built as PR #1055. Two review rounds; all findings fixed.
- 2026-09-25: merged as `494a5fa3`, approved by Dmitry. Live on dev: the field is optional on
  `ScoreSubmission` and present on `ScoreSchema` in `/openapi.json`.
- 2026-09-25: **split at close.** Closed as the store phase. The rank phase, with the read-path
  A/B question, moved to `OME-1382`, which also takes over blocking `OME-1143`.
