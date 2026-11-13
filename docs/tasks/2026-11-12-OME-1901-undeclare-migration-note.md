---
id: OME-1901
linear_url: https://linear.app/openmined/issue/OME-1901/stop-declaring-migration-note-on-the-pair-marker-l4c-1
status: done
type: task
priority: high
labels: [aigateway, agentic, autonomous]
parent: OME-1138
created: 2026-11-12
closed: 2026-11-13
---

# Stop declaring migration_note on the pair marker (L4c-1)

The pair marker model (`provider_credential_slots`) still declares `migration_note`, which L4a
(`OME-1784`) stopped reading and writing. Tortoise names every declared field in its SELECT and
INSERT, so dropping the column while a running image, or one a rollback returns to, still declares
the field would break every marker query. The column leaves in two gateway releases (owner
decision, 2026-11-09): this leaf stops declaring the field, and migration `0016` removes it from
the migration state only, with no SQL; L4c-2 (`0017`) drops the column one gateway release later.
Close-out spec `docs/spec/2026-10-29-ome-1138-closeout.md` §4.3.

- Ledger: `docs/work/2026-11-09-undeclare-migration-note.md`
- 2026-11-12: filed at PR-open under `OME-1138`; the PR opened. In Review.
- 2026-11-13: PR #1774 merged as `396298f6c`; Linear Done with the close-comment.
