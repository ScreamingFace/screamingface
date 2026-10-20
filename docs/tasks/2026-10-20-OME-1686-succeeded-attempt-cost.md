---
id: OME-1686
linear_url: https://linear.app/openmined/issue/OME-1686/report-the-cost-of-the-successful-attempt-in-request-economics
status: in_review
type: feature
priority: high
labels: [aigateway, agentic, autonomous]
parent: OME-1287
created: 2026-10-20
closed:
---

# Report the cost of the successful attempt in request economics

The leaderboard shows the cost of intelligence of a model, not the money spent on one run. A
retry must not change the price of a call. The gateway adds a successful-attempt cost field to
`_aigw.request_economics` (for example `succeeded_attempt_direct_cost`), computed before the
truncation of `attempts[]`. `direct_cost_status`, `known_direct_cost_subtotals` and `attempts[]`
stay unchanged as the record of the actual spend. `docs/usage-accounting.md` documents the field.

Blocks `OME-1687` (the engine prices each call from this field). Replaces `OME-1519` (canceled).
