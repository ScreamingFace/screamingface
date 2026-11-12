---
ticket: OME-1901
stack: aigateway
status: in_progress   # planned | in_progress | done | blocked
started: 2026-11-09
finished:
---

# undeclare-migration-note — the pair marker model stops declaring `migration_note` (OME-1138 close-out, L4c-1)

## Intent

L4a (OME-1784, #1614) stopped reading and writing `provider_credential_slots.migration_note`, but
its model still declares the field, and Tortoise names every declared field in its SELECT and
INSERT. A migration that drops the column therefore breaks every marker query of an image whose
model still declares it: the old Pods while a Helm rollout runs the pre-upgrade migration Job,
and any image a rollback returns to. So L4c ships in two releases (owner decision, 2026-11-09):
this leaf removes the field from the model and from the migration state only, with no SQL, and
the column stays; L4c-2 (`drop-migration-note`) drops the column one gateway release later. From
this leaf on, no image needs the column. Close-out spec
`docs/spec/2026-10-29-ome-1138-closeout.md` §4.3 (amended here), §6, §8, §9 Q1.

**Gate before PR-open:** none beyond L4a on `main`; the column stays, so a rollout or rollback
across this leaf meets the schema every image expects. The PR is opened when the owner says so.

## Planned changes

Gateway paths under `apps/aigateway/`:

- `src/aigateway/migrations/0016_forget_migration_note.py` (new). Generated with
  `tortoise makemigrations -n forget_migration_note models`, then edited as `0012`–`0015` were:
  the autodetector's `AlterField` on `OAuthConnection.account` is dropped (the drift `0012`
  describes), and its `RemoveField` changes the migration state only, with no SQL in either
  direction.
- `src/aigateway/core/provider_access/models/provider_credential_slot.py`: the field and its
  `WHY` go.
- `docs/spec/2026-10-29-ome-1138-closeout.md` and `docs/plan/2026-10-29-ome-1138-closeout.md`:
  L4c becomes L4c-1 and L4c-2, with the reason.

Tests:

- New: `tests/unit/test_migration_0016_forget_migration_note.py` (SQLite) and
  `tests/integration/test_migration_0016_forget_migration_note_postgres.py` (`needs_postgres`).
- Prior test that changes (owner approval 2026-11-09, manifest at PR-open):
  `tests/unit/core/provider_access/test_compatibility_paths_retired.py`. The leftover-note test
  retires, because the model can no longer read or write the note; `_plant` writes no note; the
  docstring `INVARIANT` names the two steps.

## Test plan

- On a populated database, `0016` runs no SQL: every schema object, the marker table's own
  definition included, and every row are unchanged, on SQLite and PostgreSQL.
- The downgrade runs no SQL either; a rerun is a no-op; `0016` depends on `0015`.
- The model has no `migration_note` field; the autodetector proposes nothing for the marker.
- No gateway source outside `migrations/` names the column (spec §8).

## Acceptance

- `run_gates.py aigateway` green; `AIGW_TEST_PG=1 uv run pytest -m needs_postgres` green.
- The changed prior test is in `.claude/test-change-approvals/OME-N.json` at PR-open.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned. Under `apps/aigateway/`: the new
  `src/aigateway/migrations/0016_forget_migration_note.py`; the model
  `core/provider_access/models/provider_credential_slot.py`; the new
  `tests/unit/test_migration_0016_forget_migration_note.py` (7 tests) and
  `tests/integration/test_migration_0016_forget_migration_note_postgres.py` (1 test); the
  approved prior test `tests/unit/core/provider_access/test_compatibility_paths_retired.py`
  (`test_a_leftover_note_is_neither_read_nor_written` retired, `_plant` writes no note, the
  docstring `INVARIANT` names the two steps). Docs: the close-out spec (§1 table and splits, §4.3,
  §4.10 item 4, §5, §6, §8, §9 Q1) and plan (waves, the L4c section, L11b, risks).
- **Commits:** on `OME-1901-undeclare-migration-note` from `origin/main` `d28bfa99b`:
  `refactor(aigateway): stop declaring migration_note on the pair marker`, with this ledger, the
  mirror and `.claude/test-change-approvals/OME-1901.json`. Upstream since `0ea65d44f` touches
  none of these files, and `0016` is still the next migration number.
- **Gates (2026-11-12, base `origin/main` `d28bfa99b`):** `run_gates.py aigateway --base
  origin/main` green: the append-only check (`OME-1901.json` admits the one approved file), ruff,
  ruff format, pyright, the enterprise guard and the full suite with coverage.
  `AIGW_TEST_PG=1 uv run pytest -m needs_postgres`: 74 passed. `run_gates.py repo` green. A first
  suite run alongside the PostgreSQL run failed only
  `test_login.py::test_unknown_user_timing_close_to_wrong_password`, a 10% wall-clock comparison
  of bcrypt medians; it passed five times alone and in the full rerun without that load.
- **Deviations:** none.
