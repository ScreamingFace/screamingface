---
id: OME-1682
linear_url: https://linear.app/openmined/issue/OME-1682/delete-the-profile-era-core-left-dead-after-route-retirement-stage-e
status: done
type: task
priority: high
labels: [aigateway, agentic, autonomous]
parent: OME-1138
created: 2026-10-20
closed: 2026-10-20
---

# Delete the Profile-era core left dead after route retirement (Stage E, E3b)

Landing E3b of Stage E (`OME-1209`). After E3 retired the legacy Profile routes, this unit removes
the callback, admin and pending-flow branches that no production path can create or call. Native
Connection OAuth, the D14 compatibility mirror, E1b repair, D18 pair mutations, Profile bootstrap,
chat resolution and the ProfileIndex reads needed by later stages remain.

Ledger: `docs/work/2026-10-19-e3b-retire-dead-profile-core.md`.
