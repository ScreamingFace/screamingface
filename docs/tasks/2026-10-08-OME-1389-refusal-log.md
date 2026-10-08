---
id: OME-1389
linear_url: https://linear.app/openmined/issue/OME-1389/connections-view-still-shows-a-provider-as-connected-after-its-key-was
status: in_review
type: bug
priority: medium
labels: [bug, aigateway, agentic]
created: 2026-09-27
---

# Connections view still shows a provider as connected after its key was rejected

A migrated provider slot was listed `connected` while every chat call was refused with
`401 auth_required`, and the refusal left no log line, so the cause took a database query.

Ledger: `docs/work/2026-10-08-ome-1389-refusal-log.md`.

- 2026-09-27: filed from a dev observation (OpenRouter, slot migrated from a Profile).
- 2026-10-08: the ticket's path re-run on current main: the listing already reports
  `needs_reauth` after a provider 401 (#1029 availability overlay, #1240 / OME-1250 operational
  outcome). Remaining work: an end-to-end test of that path on a Profile-migrated slot, and one
  structured WARNING when a migrated pair's credential is refused as unusable. Implemented,
  reviewed (no blockers; one finding fixed), gates green; PR opened.
