---
id: OME-1914
linear_url: https://linear.app/openmined/issue/OME-1914
status: in_progress
type: feature
priority: medium
labels: [aigateway, agentic, autonomous]
parent: OME-1314
created: 2026-11-13
closed:
---

# Run the aigateway migrate Job and Garage on the chart's node placement

The `job-migrate` hook and the bundled Garage now use the chart's `nodeSelector` and `tolerations`, so an update no longer waits on a full `user` node.

- 2026-11-13: filed under epic `OME-1314` (E23) at PR-open. Source: platform follow-up on #1738 (https://github.com/ScreamingFace/screamingface/pull/1738#issuecomment-6830194905).
- Ledger: `docs/work/2026-11-13-aigateway-chart-placement.md`
