---
id: OME-1780
linear_url: https://linear.app/openmined/issue/OME-1780/document-the-stage-e-rollback-floor-and-upgrade-path-for-operators
status: in_review
type: task
priority: medium
labels: [aigateway, agentic, autonomous]
parent: OME-1138
created: 2026-10-29
closed:
---

# Document the Stage E rollback floor and upgrade path for operators

Close-out leaf L10 of the Stage E epic. `apps/aigateway/DEPLOYMENT.md` gains a Stage E section under
"Migrations": the rollback floor after the E5b purge (every image must include E4b `f7e54869b`), the
upgrade path for an install that still holds Profile rows (an E5b-era image such as `main-1ccf80a`
runs `migrate_profiles` and then `purge_profile_history`, then 1.0.0), and what the 410
`legacy_profile_api_retired` routes mean. Profile-era wording is corrected in the chart README, the
gateway README and `docs/diagrams/gateway-identity.md`. Docs only. The L4c `0016` downgrade floor
lands with L4c.

Spec: `docs/spec/2026-10-29-ome-1138-closeout.md` §4.10. Plan:
`docs/plan/2026-10-29-ome-1138-closeout.md` §3 "L10". Ledger:
`docs/work/2026-10-29-stage-e-operator-docs.md`.
