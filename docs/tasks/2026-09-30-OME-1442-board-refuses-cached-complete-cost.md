---
id: OME-1442
linear_url: https://linear.app/openmined/issue/OME-1442/refuse-a-complete-run-cost-from-a-cached-run-on-the-board
status: backlog
type: task
priority: medium
labels: [scoreboard, agentic, design-session]
parent: OME-1251
created: 2026-09-30
closed:
---

# Refuse a complete run cost from a cached run on the board

Board half of the owner's 2026-09-30 decision (D3). `OME-1441` fixes new SDK releases only; older
SDKs and non-SDK clients still submit a cached run's near-$0 spend as `complete`.

Open for the design session: the wire shape of the hit count, what to do when an old client
sends none, and ordering against `OME-1258` and `OME-1382`.

- 2026-09-30: filed at the PR-open of `OME-1441` (#1187).
