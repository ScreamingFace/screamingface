---
id: OME-1703
linear_url: https://linear.app/openmined/issue/OME-1703/give-the-plugin-hooks-neutral-credential-names-stage-e-e4c
status: in_progress
type: task
priority: high
labels: [aigateway, agentic, autonomous]
parent: OME-1138
created: 2026-10-21
closed:
---

# Give the plugin hooks neutral credential names (Stage E, E4c)

Landing E4c of Stage E (`OME-1209`), after E4a (`OME-1685`) made every reader Connection-only and
E4b (`OME-1695`) removed every Profile document writer. The surviving Profile-named plugin hooks
take neutral names: `allows_chatless_credential`, `credentialless_auth_mode`,
`invalidate_credential_session` and `should_mark_credential_error_on_dispatch_status`, and the
strategy hooks take `credential_name`. Behaviour is unchanged. Core looks the hooks up duck-typed
with a silent default, so a guard test pins that no plugin or base class keeps an old name, that
each plugin overrides exactly the neutral hooks it should, and that every hook name core looks up
on a plugin exists. Prior tests change by name only (approval manifest `OME-1703.json`).

Ledger: `docs/work/2026-10-21-e4c-neutral-plugin-hooks.md`.
