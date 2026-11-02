---
id: OME-1084
linear_url: https://linear.app/openmined/issue/OME-1084/resolve-local-and-hosted-profile-discovery-divergence
status: done
type: task
priority: medium
labels: [design-session]
parent: OME-1138
related: [OME-1026]
created: 2026-09-02
closed: 2026-09-23
---

# Resolve local and hosted profile discovery divergence

A design question: decide the product contract for credential discovery across Local and Hosted
AIGateway deployments. When it was filed, Hosted discovery could use the account's default Profile
when no `X-Profile` was sent. A fresh Local gateway had no default Profile row: its credentials
were Connections, and chat treated one active Connection per provider as an implicit default. The
`OME-1026` discovery flow did not use that implicit Local default. The question was one implicit
credential per provider versus several selectable Profiles in the client UX.

- 2026-09-23: closed Done in Linear, with no comment and no linked PR. The `OME-1138` end state
  covers the question: one effective credential per `(account, provider)`, shared by Local and
  Hosted, with no selectable Profiles (`docs/spec/2026-09-09-OME-1138-converge-connections.md` §1).
