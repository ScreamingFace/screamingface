---
id: OME-1928
linear_url: https://linear.app/openmined/issue/OME-1928/drop-the-migration-note-column-from-the-pair-marker-l4c-2
status: in_review
type: task
priority: high
labels: [aigateway, agentic, autonomous]
parent: OME-1138
created: 2026-11-16
closed:
---

# Drop the migration_note column from the pair marker (L4c-2)

The second of the two schema steps that retire the pair marker's `migration_note` column. L4a
(`OME-1784`) stopped reading and writing the note, and L4c-1 (`OME-1901`, gateway 1.0.1) stopped
declaring it. Migration `0017` drops the column: it refuses while any marker row is `quarantined`
or still carries a note, keeps the one-marker-per-`(account_id, provider)` uniqueness and both
foreign keys on SQLite and PostgreSQL, and its downgrade re-adds a nullable column. The owner
decided on 2026-11-16 not to wait for stage and prod to run L4c-1 and accepted the rollout window
that brings. Close-out spec `docs/spec/2026-10-29-ome-1138-closeout.md` §4.3.

- Ledger: `docs/work/2026-11-08-drop-migration-note.md`
- 2026-11-16: filed under `OME-1138`; the PR opened. In Review.
