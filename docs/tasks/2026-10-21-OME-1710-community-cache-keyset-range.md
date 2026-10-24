---
id: OME-1710
linear_url: https://linear.app/openmined/issue/OME-1710/start-each-community-cache-page-batch-at-its-cursor-in-the-index
status: in_progress
type: perf
priority: high
labels: [aigateway, agentic, autonomous]
parent: OME-1311
created: 2026-10-21
closed:
---

# OME-1710 — Start each community-cache page batch at its cursor in the index

AIGateway follow-up to OME-1631 under epic OME-1311. A full pull from dev ran ~33 s a page
(~55 min) because the keyset OR is no index range: every batch walked the `(updated_at,
key_hash)` index from its start, through dev's ~188k-row tie runs. What follows a cursor is now
two index ranges (the rest of the tie run, then later times), ~1 ms each on dev against 1.4 s.

Ledger: ../work/2026-10-21-community-cache-keyset-range.md
