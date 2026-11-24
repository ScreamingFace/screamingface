---
id: OME-2002
linear_url: https://linear.app/openmined/issue/OME-2002/provide-the-hubspot-sync-token-and-egress-in-prod
status: Pick Immediately
type: task
priority: medium
labels: [scoreboard, human, deferred, task]
parent: OME-1504
created: 2026-11-23
closed:
---

# Provide the HubSpot sync token and egress in prod

Infra steps for the scoreboard's HubSpot sync (OME-1991), assigned to Stephen: write
`sf-scoreboard-prod-hubspot-token` to `kv-openmined-prod-eastus`, take over and merge
OpenMined/infrastructure#2438 (ExternalSecret, egress on 443, prod values in dry run) once
#1981 is promoted, then set `hubspotSync.dryRun: false` after the dry-run review. Blocks OME-1991.
