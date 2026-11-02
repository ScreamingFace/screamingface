---
id: OME-1498
linear_url: https://linear.app/openmined/issue/OME-1498/move-admin-ui-credential-management-to-the-pair-addressed-connection
status: done
type: task
priority: high
labels: [aigateway, agentic, autonomous]
parent: OME-1138
blocked_by: [OME-1497]
blocks: [OME-1209]
created: 2026-10-06
closed: 2026-10-14
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
Ledger: `docs/work/2026-10-14-ui-connection-admin.md`.

Squash-merged to `main` on 2026-10-14 as `9be66ecb0` (PR #1411). Linear closed the issue Done the
same day.
