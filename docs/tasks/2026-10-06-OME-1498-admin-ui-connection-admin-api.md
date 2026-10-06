---
id: OME-1498
linear_url: https://linear.app/openmined/issue/OME-1498/move-admin-ui-credential-management-to-the-pair-addressed-connection
status: backlog   # Linear is the authority; blocked until OME-1497 G1 is deployed
type: task
priority: high
labels: [aigateway, agentic, autonomous, blocked]
parent: OME-1138
blocked_by: [OME-1497]
blocks: [OME-1209]
created: 2026-10-06
closed:
---

# Move Admin UI credential management to the pair-addressed Connection admin API

Admin UI landing of D18 (`OME-1375`). Regenerates `schema.d.ts` from the exact deployed G1 Gateway
revision and moves the account credential list, attach/replace and delete to the pair-addressed
`Connection` routes. Removes the Profile name field, the Name column, the name bindings and the
`default` fallback; renders LIST `conflicts`; replaces the `account_label` Label column with the
always-`null` `masked_key_hint`; dispatches the successor error codes before the status fallback.

`OME-1209` (legacy Profile retirement) is blocked by this issue.

Contract: `docs/spec/2026-10-02-provider-credential-admin-contract.md` §2–§4, §7, §8.
Plan: `docs/plan/2026-10-02-provider-credential-admin-contract.md` (section D).
Ledger: created when implementation starts.
