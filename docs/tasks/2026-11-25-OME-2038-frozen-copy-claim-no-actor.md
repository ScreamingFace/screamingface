---
id: OME-2038
linear_url: https://linear.app/openmined/issue/OME-2038/the-frozen-copy-claim-route-needs-no-caller-address
status: in_review
type: bug
priority: high
labels: [bug, aigateway, agentic]
parent: OME-1947
created: 2026-11-25
closed:
---

# The frozen copy claim route needs no caller address

The claim route of the AI Gateway accepted a claim only with a fixed address in `X-User-Email`
(`AIGW_FROZEN_COPY_CLAIM_EMAILS`), and the scoreboard sent it (`SCOREBOARD_GATEWAY_ACTOR`). Users
never reach the gateway; only services in the cluster do. Each admitted pod can send any header, so
the address protected nothing.

- 2026-11-25: owner decision (spec Q34): remove the address. The claim route checks the peer
  network only. Filed as a `bug` sub-issue of OME-1947 (Triage, unassigned, Irina + Kevin tagged).
- Ledger: `docs/work/2026-11-25-frozen-copy-claim-no-actor.md`.
- Infrastructure: OpenMined/infrastructure#2531 (NetworkPolicy only).
- 2026-11-25: pull request https://github.com/ScreamingFace/screamingface/pull/2064 (branch
  `OME-2038-frozen-copy-claim-no-actor`).
