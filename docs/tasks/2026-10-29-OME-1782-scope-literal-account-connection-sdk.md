---
id: OME-1782
linear_url: https://linear.app/openmined/issue/OME-1782/rename-the-model-parameter-contract-scope-to-account-connection-sdk
status: in_progress
type: task
priority: low
labels: [client-sf, agentic, autonomous]
parent: OME-1138
created: 2026-10-29
closed:
---

# Rename the model-parameter contract scope to account_connection (SDK fixtures)

Close-out leaf L6b of the OME-1138 epic, the SDK half of OME-1781. The SDK decodes
`context.scope` as free text and only escapes it for display, so there is no SDK source change and
an older SDK accepts the new value. Five test files under `packages/screamingface/tests/` move to
`account_connection`. Ships in the same PR as OME-1781.

Spec: `docs/spec/2026-10-29-ome-1138-closeout.md` §4.6. Ledger:
`docs/work/2026-10-29-scope-literal-account-connection.md`.
