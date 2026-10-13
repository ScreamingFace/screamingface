---
id: OME-1600
linear_url: https://linear.app/openmined/issue/OME-1600/backfill-a-local-gateways-response-cache-into-production
status: done
type: task
priority: high
labels: [aigateway, agentic, task]
parent: OME-951
created: 2026-10-13
closed: 2026-10-13
---

# Backfill a local gateway's response cache into production

Copy a local AI Gateway's `request_cache_entries` (120,198 rows from the contracteval, gdpval-text
and frontierscience local runs) to prod unchanged, so prod reruns of those boards hit the cache.
Follows `OME-1526` (dev → prod).

- 2026-10-13: filed and started; source inspected, offline delta = all 120,198 rows new.
- 2026-10-13: done. 120,174 rows loaded into prod (insert-only, 24 prod-held keys kept); verified in-pod; probes on gdpval-text, frontierscience and contracteval: 0 misses, $0.
