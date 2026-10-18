---
id: OME-1647
linear_url: https://linear.app/openmined/issue/OME-1647/move-the-credential-vocabulary-out-of-profile-models-stage-e-e2a
status: in_progress
type: task
priority: high
labels: [aigateway, agentic, autonomous]
parent: OME-1138
created: 2026-10-18
closed:
---

# Move the credential vocabulary out of profile_models (Stage E, E2a)

Landing E2a of Stage E (`OME-1209`). `AuthType` and `AuthMode` move to `core/auth_types.py`;
`credential_name_for` and `profile_id_for` move to `core/credential_names.py`.
`profile_models.py` keeps only the Profile row, and a boundary test stops any non-owner module
from importing it. No behaviour change.

Ledger: `docs/work/2026-10-18-e2a-neutral-types.md`.
