---
id: OME-1777
linear_url: https://linear.app/openmined/issue/OME-1777/stop-the-unknown-processor-error-from-listing-a-nodes-routes
status: in_progress
type: fix
priority: high
labels: [url4-engine, agentic, autonomous]
parent: OME-1306
created: 2026-10-29
---

# Stop the unknown-processor error from listing a node's routes

url4 slice of hosted BYOM Unit 2, found in the review of PR #1606 and landing in that PR beside
OME-1770 (Engine), OME-1771 (Gateway chart) and OME-1773 (SDK tests).

A nested peer call can choose its own `processor=`. With an unknown id and a real fan-out reduce,
`packages/url4/src/url4/dag/processor.py::_route_for_id` raised an error that listed every route
the node declares, private configured-endpoint routes included. The run's terminal frame carried
that text to the caller's own WebSocket, in cold and warm runs, without the private model being
called.

- `_route_for_id` names only the id the caller passed, keeping `ErrorCode.UNKNOWN_PROCESSOR` and
  `permanent=True`. Executable routes stay in `processor_routes()`.
- The spec test that pinned the listing now asserts its absence. Owner approval 2026-10-29,
  pinned in `.claude/test-change-approvals/OME-1777.json`.
- Engine regression: a nested fan-out with `processor=never`, cold and warm; no WebSocket frame and
  no HTTP response names the private route.

Ledger: `docs/work/2026-10-29-hosted-byom-unit2.md`.
