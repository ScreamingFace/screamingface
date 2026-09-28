---
id: OME-1210
linear_url: https://linear.app/openmined/issue/OME-1210/aigateway-decide-final-provider-identity-naming
status: done
type: task
priority: high
labels: [aigateway]
parent: OME-1138
created: 2026-09-15
closed: 2026-09-16
---

# AIGateway: decide final provider identity naming

Planning-visible architecture-debt follow-up for `OME-1138`. It decides the vocabulary used by the
next consumer-migration and backing-migration slices before more runtime code lands.

Decision summary:

- Final product/API/domain resource: `Connection`.
- Boundary and route family: `provider access`.
- Compatibility/current backing term: `legacy Profile`.
- Not introduced as a resource/API/UI noun: `Provider Account`.
- Internal resolution value only: `CredentialTarget` / credential target.

Ledger: `docs/work/2026-09-16-OME-1210-provider-identity-naming.md`.
Spec: `docs/spec/2026-09-09-OME-1138-converge-connections.md` §1 and §8 D20.
Plan: `docs/plan/2026-09-09-OME-1138-converge-connections.md` §1, §2 and §4.
