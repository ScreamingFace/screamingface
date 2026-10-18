---
id: OME-1651
linear_url: https://linear.app/openmined/issue/OME-1651/retire-the-legacy-profile-http-routes-with-a-410-and-their-successor
status: in_progress
type: task
priority: high
labels: [aigateway, agentic, autonomous]
parent: OME-1138
created: 2026-10-18
closed:
---

# Retire the legacy Profile HTTP routes with a 410 and their successor (Stage E, E3)

Landing E3 of Stage E (`OME-1209`). The 13 legacy Profile routes answer `410 Gone` with
`legacy_profile_api_retired` and their successor, from a static table, before authentication and
any I/O. They leave OpenAPI with their handlers and schemas; the Admin UI `schema.d.ts` is
regenerated. Callbacks, storage, chat resolution and bootstrap stay until E4; the core operations
only the retired handlers called go in E3b.

Ledger: `docs/work/2026-10-18-e3-retire-profile-routes.md`.
