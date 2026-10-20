---
id: OME-1685
linear_url: https://linear.app/openmined/issue/OME-1685/resolve-availability-and-pair-admin-read-no-profile-document-stage-e
status: in_progress
type: task
priority: high
labels: [aigateway, agentic, autonomous]
parent: OME-1138
created: 2026-10-20
closed:
---

# Resolve, availability and pair admin read no Profile document (Stage E, E4a)

Landing E4a of Stage E (`OME-1209`). The 2026-10-20 census met the E4 precondition, so the read path
stops consulting the legacy Profile index: resolve decides on the pair marker (a `quarantined` pair
answers 409 `credential_pair_unresolved`, an absent or `none` marker takes the Connection label path,
a `migrated` pair uses its effective Connection), availability folds no Profile state, and the D18
classification drops its Profile rows. Writes stay for E4b, the plugin hook names for E4c; no
document or blob is deleted.

Ledger: `docs/work/2026-10-20-e4a-connection-only-readers.md`.
