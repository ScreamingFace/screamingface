---
id: OME-1719
linear_url: https://linear.app/openmined/issue/OME-1719/bound-per-host-transport-pools-in-url4-source-guard
status: in_progress
type: bug
priority: medium
labels: [bug, url4-sdk, human, autonomous]
created: 2026-10-22
closed:
---

# Bound per-host transport pools in url4 source guard

Per-host inner transports now live in an LRU `HostPools` map (`url4.io._host_pools`) of at most `MAX_HOST_POOLS`
(32). An evicted pool closes at once when idle. If it still has a request in flight, it closes when its last
response closes. Each request holds an idempotent lease from its first attempt until its response closes. An
evicted pool is never reused, so Host/SNI isolation holds. Adapter shutdown closes both retained pools and
evicted pools that are still busy.

Follow-up to `OME-1544` (PR #1521). Parent epic `OME-1529`.
Ledger: `../work/2026-10-26-url4-guard-followups.md`.
