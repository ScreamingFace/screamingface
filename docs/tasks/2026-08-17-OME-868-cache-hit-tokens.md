---
id: OME-868
linear_url: https://linear.app/openmined/issue/OME-868/stop-counting-a-cache-hits-replayed-tokens-as-freshly-consumed
status: In Progress
type: Feature
priority: P1
labels: [url4-cloud, agentic, autonomous]
created: 2026-08-17
closed:
---

# Stop counting a cache hit's replayed tokens as freshly consumed

Part of the OME-849 cost epic, found in peer review of PR #620. A cache hit falls back to the
replayed cached body's `usage`, publishing the original call's tokens as consumed while pricing
the call at zero. Spec: `docs/spec/2026-08-17-OME-849-run-cost-openrouter.md`.
