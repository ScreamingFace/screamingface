---
id: OME-1645
linear_url: https://linear.app/openmined/issue/OME-1645/delete-the-dead-chat-shims-and-the-saved-defaults-pipeline-stage-e-e2b
status: done
type: task
priority: high
labels: [aigateway, agentic, autonomous]
parent: OME-1138
created: 2026-10-17
closed: 2026-10-18
---

# Delete the dead chat shims and the saved-defaults pipeline (Stage E, E2b)

Landing E2b of Stage E (`OME-1209`). Deletes `routes/chat_credentials.py`,
`routes/chat_profile_defaults.py`, `core/provider_access/defaults.py` and
`core/provider_access/profile_defaults.py`, plus `RequestDefaults`, `CredentialTarget.defaults`,
`ProviderAccess.defaults_for` and the `should_apply_profile_default` plugin hook. Stage C
(`OME-1323`) and A2 (`OME-1207`) left all of it with no production caller.

Ledger: `docs/work/2026-10-17-e2b-dead-profile-defaults.md`.
