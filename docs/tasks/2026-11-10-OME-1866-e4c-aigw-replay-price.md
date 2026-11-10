---
id: OME-1866
linear_url: https://linear.app/openmined/issue/OME-1866/carry-the-captured-calls-price-on-a-frozen-copy-replay
status: in_progress
type: feature
priority: 2
labels: [aigateway, agentic, autonomous]
created: 2026-11-10
closed:
---

# Carry the captured call's price on a frozen-copy replay

Mirror of OME-1866 (parent epic OME-1291, E4c). Scope (Q21b): a frozen-copy replay carries the captured call's price as `cache.reference`; a `partial` stored entry withholds its tokens as well as its cost. The pinned test `test_cache_entry_metadata_none_space` changes one expectation. One PR for the three E4c leaves: OME-1864 (Engine),
OME-1865 (SDK), OME-1866 (aigateway). Branch `OME-1864-e4c-routers-cascades`.

Design: `docs/spec/2026-10-22-e4c-routers-cascades/`, plan `docs/plan/2026-10-22-e4c-routers-cascades.md`.
Ledger: `docs/work/2026-10-22-e4c-routers-cascades.md`.
Test approvals: `.claude/test-change-approvals/OME-1291.json`.
