---
id: OME-1750
linear_url: https://linear.app/openmined/issue/OME-1750/add-the-offline-purge-of-retired-profile-storage-stage-e-e5b
status: in_progress
type: task
priority: high
labels: [aigateway, agentic, autonomous]
parent: OME-1138
created: 2026-10-27
closed:
---

# Add the offline purge of retired Profile storage (Stage E, E5b)

Landing E5b of the Stage E history cleanup, the second of three (E5a trim, E5b purge command, E5c
vocabulary). `python -m aigateway.purge_profile_history` deletes the Profile index rows and the
provider-credential blobs no Connection addresses, one transaction per account fenced by
`SELECT … FOR UPDATE` on its `accounts` row; it keeps every blob any Connection row resolves to,
skips an account it cannot prove (with a fixed reason), and with `--all` then sweeps the rows of
deleted accounts and the legacy global index row. `--apply` requires `--journal`; a skipped
account or a kept row exits 4. One prior test, the offline-reader guard's `_OFFLINE_READERS`,
moves under the owner-approved manifest `.claude/test-change-approvals/OME-1750.json`. No data
changes on merge; the owner runs the command per environment.

Spec: `docs/spec/2026-10-21-OME-1715-e5-history-cleanup.md`. Plan:
`docs/plan/2026-10-21-OME-1715-e5-history-cleanup.md`. Ledger:
`docs/work/2026-10-22-e5b-history-purge.md`.
