---
ticket: OME-1928
stack: aigateway
status: done   # planned | in_progress | done | blocked
started: 2026-11-08
finished: 2026-11-16
---

# drop-migration-note — drop the `migration_note` column from the pair marker (OME-1138 close-out, L4c-2)

## Intent

L4a (OME-1784, #1614) stopped reading and writing `provider_credential_slots.migration_note`.
L4c-1 (OME-1901, `396298f6c`, #1774; gateway 1.0.1) stops declaring the field and removes it
from the migration state only, with no SQL. This leaf, after that release, is the second schema step:
migration `0017` drops the column. The upgrade refuses while any `quarantined` or noted marker row
exists, the downgrade re-adds a nullable column, and the D1 uniqueness of `(account_id, provider)`
and both foreign keys survive on SQLite and PostgreSQL. Close-out spec
`docs/spec/2026-10-29-ome-1138-closeout.md` §4.3, §4.10 item 4, §5, §6, §8, §9 Q1 (as amended
2026-11-09 by L4c-1); plan `docs/plan/2026-10-29-ome-1138-closeout.md` "L4c".

Why a second release (owner decision, 2026-11-09): Tortoise names every declared field in its
SELECT and INSERT, so an image whose model declares the field breaks on a database without the
column. The chart's pre-upgrade migration Job runs while the old Pods still serve, and
`helm rollback` runs no migration. Dropping the column is safe only once no running image, and no
image a rollback returns to, declares it: every image from L4c-1 on.

**Owner decision, 2026-11-16: L4c-2 does not wait for stage and prod to run L4c-1.** Those two
ran an image whose gateway code is 1.0.0 that day. Each takes a rollout window when its next
deploy runs `0016` and `0017` in one Job: until the new Pod is ready, a Connection write on an old
Pod can fail, because the queries that lock or insert a marker row (`hold_pair`, `check_observed`,
`PairAuthorityStore.hold`, the first-marker `create`) name every declared field. Marker reads go
through `.values(...)` with named columns, so model calls and listings keep working. The rollback
floor stays (spec §4.10 item 4). Spec §4.3, §5 and §9 Q1 and the plan record the decision.

**Gate before PR-open.** Gateway 1.0.1 (`7f690bcbc`, tag `aigateway-v1.0.1`) carries L4c-1.
Read-only checks on 2026-11-16, each in a transaction set `READ ONLY` and rolled back:

| Environment | Gateway image | Latest migration | Rows / quarantined / noted |
|---|---|---|---|
| dev | `main-aba60f1e7` (1.0.1 and later) | `0016` | 26 / 0 / 0 |
| stage | `main-24d979a5e` (code of 1.0.0) | `0015` | 1 / 0 / 0 |
| prod | `main-24d979a5e` (code of 1.0.0) | not readable | not readable |

The prod session could not exec into the Pod. Prod's last count was 7 / 0 / 0, after the
2026-10-30 remediation. Its image includes L4a (#1614), which writes no note and no `quarantined`
state, and `0017` refuses to drop the column while either remains.

## Planned changes

Gateway paths under `apps/aigateway/`:

- `src/aigateway/migrations/0017_drop_migration_note.py` (new, hand-written: after `0016` the
  autodetector proposes only the `OAuthConnection.account` drift `0012` describes, which is left
  out):
  - the PostgreSQL lock wait is bounded, as `0013` does;
  - a guard refuses the upgrade while a `quarantined` or noted row exists;
  - the column goes with one plain `RunSQL` `ALTER TABLE … DROP COLUMN` on both dialects, not
    Tortoise's SQLite `RemoveField` rebuild, which loses `unique_together` (spec §4.3); the
    reverse is `ADD COLUMN migration_note VARCHAR(255)`, nullable.
- `DEPLOYMENT.md`: the two releases, the accepted window for an upgrade from an image before
  L4c-1, the guard's precondition, and the rollback floor with its downgrade command (spec §4.10
  item 4).
- `docs/spec/2026-10-29-ome-1138-closeout.md` (§1 table, §4.3, §5, §9 Q1) and
  `docs/plan/2026-10-29-ome-1138-closeout.md` (waves, risks): the 2026-11-16 decision.

Tests:

- New: `tests/unit/test_migration_0017_drop_migration_note.py` (SQLite) and
  `tests/integration/test_migration_0017_drop_migration_note_postgres.py` (`needs_postgres`).
- Prior test that changes (owner approval 2026-11-09, manifest at PR-open, spec §6):
  `tests/unit/test_migration_0012_provider_credential_slots.py`: the column test migrates to
  `0012` instead of head.

## Test plan

SQLite (populated replay: migrate to `0016`, seed an account, a Connection and a marker row):

- After `0017`: the column is gone, every other column keeps its shape, and the row survives.
- Every index, foreign key and other schema object is unchanged, the uniqueness autoindex
  included.
- A second marker for the same pair is refused; deleting the Connection nulls the reference;
  deleting the account deletes the marker.
- The upgrade refuses a `quarantined` row, a noted row and both, naming the counts; the column and
  the row stay; the operator's settlement unblocks it.
- The downgrade re-adds a nullable `migration_note` and leaves every other schema object as it was.
- A rerun is a no-op; `0017` depends on `0016`.

PostgreSQL: the same column, uniqueness, foreign-key, guard and downgrade checks on a populated
database; a blocked lock queue fails the upgrade (`55P03`) instead of stalling every marker read;
plus the existing `needs_postgres` marker suites.

## Acceptance

- `run_gates.py aigateway` green; `AIGW_TEST_PG=1 uv run pytest -m needs_postgres` green.
- The changed prior test is in `.claude/test-change-approvals/OME-1928.json`.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned: `0017_drop_migration_note.py`, `DEPLOYMENT.md`, the new
  `tests/unit/test_migration_0017_drop_migration_note.py` (10 tests) and
  `tests/integration/test_migration_0017_drop_migration_note_postgres.py` (5 tests), the
  approved prior test `tests/unit/test_migration_0012_provider_credential_slots.py`, and the spec
  and plan amendments.
- **Commits:** `086bc723b` refactor(aigateway): drop the migration_note column from the pair
  marker (#1843), squash-merged 2026-11-16 13:44 UTC. Linear `OME-1928` Done with the
  close-comment. The branch held one commit from `origin/main` `adea815d7`, which already carries
  L4c-1: `refactor(aigateway): drop the migration_note column from the pair marker`, with this
  ledger, the mirror and `.claude/test-change-approvals/OME-1928.json`.
- **Gates (2026-11-16, base `origin/main` `adea815d7`):** ruff, ruff format, pyright, the
  enterprise guard and the full suite with coverage green (7901 passed, 119 skipped, 94.16%). The
  append-only check admits the one approved prior test through `OME-1928.json`.
  `AIGW_TEST_PG=1 uv run pytest -m needs_postgres`: 79 passed. The cache-snapshot upload suites
  shell out to `pg_dump`, which must be major version 16 like their container; a local
  `pg_dump` 15 fails them on the version check.
  `run_gates.py repo` green.
- **Deviations:** a first, single-step version (`0016` dropping the column) was replaced by the
  two-release split before any commit, once the rollout and rollback hazard was shown
  (owner, 2026-11-09). On 2026-11-16 the owner chose not to wait for stage and prod to run
  L4c-1 and accepted the rollout window.
