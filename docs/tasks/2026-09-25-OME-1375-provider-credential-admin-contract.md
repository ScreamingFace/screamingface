---
id: OME-1375
linear_url: https://linear.app/openmined/issue/OME-1375/aigateway-decide-the-pair-addressed-provider-credential-admin
status: in_review   # Linear is the authority; the formalization PR is open
type: task
priority: high
labels: [aigateway, design-session]
parent: OME-1138
created: 2026-09-25
closed:
---

# AIGateway: decide the pair-addressed provider credential admin successor

Contract decision D18 of `OME-1138`: the neutral admin successor that lets `OME-1209` retire the
legacy Profile routes once the Admin UI moves to it. One effective credential per
`(account, provider)`, addressed by pair, API-key-only and masked, with `Connection` as the resource
noun and `provider access` as the boundary. No runtime code, deployment, production access,
migration or Profile cleanup in this issue.

Decision: approved by the owner on 2026-10-05; the shadow identity proof decided the same day.
Correction carried by the formalization: the legacy admin contract has three concurrency outcomes
(503 `profile_index_conflict`, 409 `profile_conflict`, 409 `connection_conflict`), not two.

Ledger: `docs/work/2026-10-05-OME-1375-provider-credential-admin-contract.md`.
Spec: `docs/spec/2026-10-02-provider-credential-admin-contract.md`.
Plan: `docs/plan/2026-10-02-provider-credential-admin-contract.md`.
Umbrella: `docs/spec/2026-09-09-OME-1138-converge-connections.md` §3.5, §8 D18.
Landings filed 2026-10-06 with owner authorization, under `OME-1138`: Gateway `OME-1497` (G0 then
G1, blocked by this issue) and Admin UI `OME-1498` (blocked by `OME-1497`); `OME-1209` is blocked
by `OME-1498`.
