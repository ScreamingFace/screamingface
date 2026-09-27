---
id: OME-1388
linear_url: https://linear.app/openmined/issue/OME-1388
status: in_progress
type: feature
priority: 3
labels: [url4-sdk, agentic, autonomous]
parent: OME-1086
created: 2026-09-27
closed:
---

# OME-1388 — Add a public direct-call API to url4

`url4.peer.dispatch_direct` (with `describe_routes` and `is_eval_path`) runs ONE registered
handler of a node and refuses the eval path (D1). A failed direct call gets a public HTTP
status. The `EventStream` contract's "counter never rewinds" check moves from `purge` to
`delete_stream`.

- Spec: `apps/screamingface-engine/docs/plans/uniform-executor/prd/04-mount-call-as-direct-run.md`
- Ledger: `docs/work/2026-09-27-uniform-executor.md`
- Sibling leaf: `OME-1387` (engine), same PR.
