---
id: OME-1715
linear_url: https://linear.app/openmined/issue/OME-1715/mint-the-d18-puts-connection-at-its-own-address-and-remove-the-dead
status: done
type: task
priority: high
labels: [aigateway, agentic, autonomous]
parent: OME-1138
created: 2026-10-22
closed: 2026-10-22
---

# Mint the D18 PUT's Connection at its own address and remove the dead Profile conflict arms (Stage E, E5a)

Landing E5a of the Stage E history cleanup, the first of three (E5a trim, E5b purge command, E5c
vocabulary). A D18 PUT on a pair with no reusable row no longer mints its row at the `default`
Profile address: the row takes its own `<account_id>:<connection id>` address, as a native API-key
row does, so the PUT cannot adopt a blob the E5 purge may be deleting. The Profile name the PUT
carried goes with it (`DEFAULT_LEGACY_NAME`, `PairMutation.profile_names`), the Profile-backed admin
base folds into `connection_admin.py`, and the conflict renderings whose last emitter left in E4b
are removed. 21 prior tests in 11 files, and the remote-endpoint harness helper that read the old
address, move under the owner-approved manifest `.claude/test-change-approvals/OME-1715.json`.

Spec: `docs/spec/2026-10-21-OME-1715-e5-history-cleanup.md`. Plan:
`docs/plan/2026-10-21-OME-1715-e5-history-cleanup.md`. Ledgers:
`docs/work/2026-10-21-e5-history-cleanup-spec.md`, `docs/work/2026-10-22-e5a-put-own-address.md`.
