---
ticket: unfiled
stack: scoreboard
status: done
started: 2026-09-30
finished: 2026-09-30
---

# e14-final-apps-scoreboard — fix the confirmed cross-unit E14 findings in apps/scoreboard

## Intent

Fix four confirmed findings of the E14 final review in `apps/scoreboard`: FS-1 (a public
Idempotency-Key of 129 to 255 characters is a 500 with clustering on), MRA-1 (the admin audit line
is dropped in production because no scoreboard logger is configured), MRA-2 (the admin audit has no
before value), X-SEC-1 (the replay claim accepts any result id as `pinned_baseline_result_id`).

## Planned changes

- FS-1: `run_id` becomes VARCHAR(255) (same as `IdempotencyKey.key`) in
  `scores/models/reported_result.py` and in migration 0018 (E14 is not released, so 0018 is edited
  in place; no 0020 with AlterField, which Tortoise cannot run on a populated SQLite file).
  Docs: `erd.md` row of `run_id`.
- MRA-1: `cli.py` gets `configure_logging` (handler + `SCOREBOARD_LOG_LEVEL` on the `scoreboard`
  logger), called by `main()` before `uvicorn.run`.
- MRA-2: `routes/admin.py` writes a second line `admin_change` (actor, target, before, after,
  reason) on a successful admin attempt. `set_redistributable` returns the prior value.
  `PublicationStore.withdraw` reports the previous state (keyword callback, under the row lock).
  WHY a second line and not a longer `admin_action` line: prior tests pin the `admin_action` line
  (exact string, `endswith`); append-only rule.
- X-SEC-1: `cluster_store._check_replay` checks the baseline with the same board and
  `replay_access` rules as `result_id`.

## Test plan

- FS-1: 200-char and 255-char key: 201 then 200 replay, same result; column length parity test;
  migrated SQLite file has VARCHAR(255).
- MRA-1: after `configure_logging("info")` a withdraw writes the `admin_action` line to stderr
  WITHOUT `caplog.set_level`; `main()` calls it.
- MRA-2: withdraw of a `private` row logs before=private after=withdrawn; redistributable flip logs
  before=false after=true, a repeat logs before=true after=true; refused attempts log no change.
- X-SEC-1: baseline on another board, private result of another user, gated result: 422
  `invalid_replay_claim`; prior test (different public result of the same board) stays green.

## Acceptance

- The four behaviours above; scoreboard gates green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `routes/admin_benchmarks.py` (before/after values), tests
  `submissions/test_long_idempotency_key.py` (new), `submissions/test_replay_claim.py` and
  `publish/test_withdraw.py` (appended only), `docs/spec/.../erd.md` (run_id width).
- **Commits:** see `git log final/apps-scoreboard` (fix FS-1, fix X-SEC-1, fix MRA-1/MRA-2, ledger).
- **Gates:** `run_gates.py scoreboard` all green (ruff, format, pyright, pytest + coverage, node).
- **Deviations:** (1) the `tortoise-dev` companion skill is not installed here; the house patterns
  were read from the neighbouring migrations and models instead. (2) X-SEC-1 uses the finding's
  second option (same board and `replay_access` rules), not baseline == replayed result, because
  the strict rule would change the prior test `test_replay_run_stores_provenance_and_label` (owner
  approval needed). (3) MRA-2 uses a second `admin_change` line because prior tests pin the
  `admin_action` line. (4) 0018 was edited in place (E14 unreleased). (5) MRA-1 fixes the log
  path; a durable `admin_audit_events` table is NOT built (product decision, see not_fixed).
