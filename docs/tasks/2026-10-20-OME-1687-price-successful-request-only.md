---
id: OME-1687
linear_url: https://linear.app/openmined/issue/OME-1687/price-a-model-call-from-its-successful-request-only
status: done
type: feature
priority: high
labels: [screamingface-engine, agentic, autonomous]
parent: OME-1287
created: 2026-10-20
closed: 2026-10-20
---

# Price a model call from its successful request only

The leaderboard shows the cost of intelligence of a model, which assumes each model answers on
the first attempt. No retry path may make a call or a run unpriced:

- gateway retry (429/503/529): price from the `OME-1686` successful-attempt cost field, not from
  `direct_cost_status`;
- engine transport retry: remove the `OME-1220` rule in `world/connector.py` `_report_usage`;
- retried cache hit: price and count saved cost like any other hit.

A successful call with no cost of its own stays unpriced. Judge redraws continue to count. The
frozen-copy replay logic that reads `retried` does not change.

Blocked by `OME-1686`.
