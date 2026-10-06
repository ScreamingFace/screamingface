---
id: OME-1497
linear_url: https://linear.app/openmined/issue/OME-1497/guard-provider-credential-writers-and-publish-the-pair-addressed
status: backlog   # Linear is the authority; blocked until the OME-1375 contract lands
type: task
priority: high
labels: [aigateway, agentic, autonomous, blocked]
parent: OME-1138
blocked_by: [OME-1375]
blocks: [OME-1498]
created: 2026-10-06
closed:
---

# Guard provider credential writers and publish the pair-addressed Connection admin API

Gateway landing of D18 (`OME-1375`), in two sequential releases of one issue:

- G0 writer floor: every authority-changing credential writer, OAuth refresh publication included,
  uses the pair-generation compare-and-set also on `none` and `quarantined` pairs; refresh never
  advances the generation. No new API.
- G1: `GET/PUT/DELETE /v1/admin/accounts/{account_id}/connections…`, the neutral DTO, the ordered
  pair disposition, the mutation-time bridge and the legacy OAuth shadow identity proof. Deployed
  only after G0 runs on every Gateway instance that writes credentials.

Release checklist (owner-confirmed): G0 merged → G0 deployed → G1 merged → G1 deployed.

Contract: `docs/spec/2026-10-02-provider-credential-admin-contract.md`.
Plan: `docs/plan/2026-10-02-provider-credential-admin-contract.md` (sections B and C).
Ledger: created when implementation starts.
