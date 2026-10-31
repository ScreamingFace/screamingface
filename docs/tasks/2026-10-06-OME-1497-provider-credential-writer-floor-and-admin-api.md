---
id: OME-1497
linear_url: https://linear.app/openmined/issue/OME-1497/guard-provider-credential-writers-and-publish-the-pair-addressed
status: done
type: task
priority: high
labels: [aigateway, agentic, autonomous]
parent: OME-1138
blocked_by: [OME-1375]
blocks: [OME-1498]
created: 2026-10-06
closed: 2026-10-14
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
Ledger (G0): `docs/work/2026-10-06-OME-1497-g0-writer-floor.md`.
Ledger (G0 part 2): `docs/work/2026-10-07-g0-refresh-guarded-publish.md`.
Ledger (G0 part 3): `docs/work/2026-10-13-g0-check-only-fail-guards.md`.
Ledger (G1 part 1): `docs/work/2026-10-13-g1-pair-admin-list.md`.
Ledger (G1 part 2): `docs/work/2026-10-14-g1-pair-admin-mutations.md`.
Ledger (G1 part 3): `docs/work/2026-10-14-g1-shadow-identity-proof.md`.

Squash-merged to `main`: G0 as `c76d39972` (PR #1271), `01875d23f` (PR #1299) and `123be8466`
(PR #1396); G1 as `1ed95abdf` (PR #1397), `e79db8205` (PR #1405, the re-land of PR #1404, which
merged into its stacked base and never reached `main`) and `3bfa2fd24` (PR #1408). Linear closed
the issue Done on 2026-10-14.
