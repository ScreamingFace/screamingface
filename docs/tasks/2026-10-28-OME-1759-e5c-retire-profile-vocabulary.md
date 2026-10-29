---
id: OME-1759
linear_url: https://linear.app/openmined/issue/OME-1759/retire-the-profile-vocabulary-from-the-gateway-stage-e-e5c
status: in_progress
type: task
priority: high
labels: [aigateway, agentic, autonomous]
parent: OME-1138
created: 2026-10-28
closed:
---

# Retire the Profile vocabulary from the gateway (Stage E, E5c)

Landing E5c of the Stage E history cleanup, the last of three (E5a trim, E5b purge command, E5c
vocabulary). Runtime has been Connection-only since E4a/E4b, and the E5b purge has removed the
Profile index rows from every environment. This unit deletes the Profile model, the index store,
the offline backfill and the purge command, drops `credential_names.profile_id_for`, and makes
`auth_type_of` take only the Connection. Retired suites become retirement docstrings naming their
successors; surviving suites stop seeding or reading Profile documents; the import guard pins that
the modules are absent. Prior-test changes move under the owner-approved manifest
`.claude/test-change-approvals/OME-1759.json`. No data changes on merge.

Spec: `docs/spec/2026-10-21-OME-1715-e5-history-cleanup.md`. Plan:
`docs/plan/2026-10-21-OME-1715-e5-history-cleanup.md`. Ledger:
`docs/work/2026-10-28-e5c-retire-profile-vocabulary.md`.
