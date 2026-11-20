---
id: OME-1991
linear_url: https://linear.app/openmined/issue/OME-1991/sync-outside-leaderboard-submitters-to-the-hubspot-sota-pipeline
status: In Progress
type: feature
priority: medium
labels: [scoreboard, agentic, autonomous]
parent: OME-1504
created: 2026-11-20
closed:
---

# Sync outside leaderboard submitters to the HubSpot SOTA pipeline

Every outside leaderboard submission reaches the submitter's card on the 😱 SOTA pipeline in
HubSpot: contact by email, one card per person moved through Submission 1, 2 and 3, the newest
leaderboard entry, the last active date, and the SOTA flag when a fusion beats every solo model
on its board. A CronJob drains a queue table, so a HubSpot outage never touches the submit path.

Spec: `docs/spec/2026-11-18-hubspot-submission-sync.md`.
Plan: `docs/plan/2026-11-18-hubspot-submission-sync.md`.
Ledger: `docs/work/2026-11-18-hubspot-submission-sync.md`.
Branch: `OME-1991-hubspot-submission-sync`.
