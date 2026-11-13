---
id: OME-1913
linear_url: https://linear.app/openmined/issue/OME-1913
status: in_progress
type: feature
priority: medium
labels: [screamingface-engine, agentic, autonomous]
parent: OME-1314
created: 2026-11-13
closed:
---

# Run the engine's Garage and migrate Job on the chart's node placement

The two bundled Garage StatefulSets and the migrate Job now use the chart's `nodeSelector` and `tolerations`, so they run on the tenant pool and not on the shared `user` pool.

- 2026-11-13: filed under epic `OME-1314` (E23) at PR-open. Source: platform follow-up on #1738 (https://github.com/ScreamingFace/screamingface/pull/1738#issuecomment-6830194905).
- Ledger: `docs/work/2026-11-13-engine-chart-placement.md`
