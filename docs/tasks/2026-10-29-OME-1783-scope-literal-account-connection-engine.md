---
id: OME-1783
linear_url: https://linear.app/openmined/issue/OME-1783/rename-the-model-parameter-contract-scope-to-account-connection-engine
status: in_progress
type: task
priority: low
labels: [screamingface-engine, agentic, autonomous]
parent: OME-1138
created: 2026-10-29
closed:
---

# Rename the model-parameter contract scope to account_connection (Engine fixture)

Close-out leaf L6c of the OME-1138 epic, the Engine half of OME-1781. The Engine's
`/v1/model-parameters` proxy passes the gateway document through and does not read
`context.scope`, so there is no Engine source change. The proxy test fixture
`apps/screamingface-engine/tests/unit/test_model_parameters_proxy.py` moves to
`account_connection`. Ships in the same PR as OME-1781.

Spec: `docs/spec/2026-10-29-ome-1138-closeout.md` §4.6. Ledger:
`docs/work/2026-10-29-scope-literal-account-connection.md`.
