---
id: OME-1781
linear_url: https://linear.app/openmined/issue/OME-1781/rename-the-model-parameter-contract-scope-to-account-connection
status: in_progress
type: improvement
priority: low
labels: [aigateway, agentic, autonomous]
parent: OME-1138
created: 2026-10-29
closed:
---

# Rename the model-parameter contract scope to account_connection (gateway)

Close-out leaf L6a of the OME-1138 epic. The `/v1/model-parameters` document now serves
`context.scope = "account_connection"` instead of the Profile-era `"account_profile"` (owner
decision, 2026-10-29). `scope` is a digest input, so `contract_id` and `context.revision` change
once; nothing in the repo persists either value. One producer
(`apps/aigateway/src/aigateway/routes/model_parameters.py`), the composer and module docstrings,
15 test modules, and a new contract test pinning that a scope change rotates both identities. Ships in one
PR with OME-1782 (SDK fixtures) and OME-1783 (Engine fixture); prior-test changes are under
`.claude/test-change-approvals/OME-1781.json`.

Spec: `docs/spec/2026-10-29-ome-1138-closeout.md` §4.6. Plan:
`docs/plan/2026-10-29-ome-1138-closeout.md` §3. Ledger:
`docs/work/2026-10-29-scope-literal-account-connection.md`.
