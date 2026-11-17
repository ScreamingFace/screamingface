---
ticket: OME-1947
stack: aigateway
status: in_progress   # planned | in_progress | done | blocked
started: 2026-11-17
finished:
---

# frozen-copy-retention-stack-a — the gateway marks and purges abandoned frozen copies

## Intent

No code deletes a frozen copy, so the production gateway database grows with no limit
(OME-1947). Stack A makes the gateway mark an open copy that is idle for 24 hours as
`abandoned` and delete its entries, in a periodic sweep that is always on. Spec:
`docs/spec/2026-11-16-frozen-copy-retention/`. Plan:
`docs/plan/2026-11-17-frozen-copy-retention-stack-a.md` (owner approved 2026-11-17).

This ledger covers three units, one for each pull request: A1, A2, A3.

## Planned changes

Paths are under `apps/aigateway/` unless they start with `docs/`, `charts/` or `.claude/`.

- **A1** (migration 0018, two new states, seal only an open copy)
  - `.claude/test-change-approvals/OME-1947.json` (new; owner record)
  - `tests/unit/test_frozen_copy_migration.py` (one assertion; owner approved)
  - `src/aigateway/core/frozen_copy/models.py`
  - `src/aigateway/migrations/0018_frozen_copy_retention.py` (new; S1: ships with the model)
  - `src/aigateway/core/frozen_copy/store.py`, `src/aigateway/routes/frozen_copies.py`
  - `tests/unit/test_frozen_copy_retention_migration.py`, `tests/unit/test_frozen_copy_retention_states.py` (new)
- **A2** (idle rule, purge, command, three settings)
  - `src/aigateway/config.py`
  - `src/aigateway/core/frozen_copy/sweep.py` (new), `src/aigateway/frozen_copy_sweep.py` (new)
  - `tests/unit/test_frozen_copy_sweep_settings.py`, `tests/unit/test_frozen_copy_sweep.py`,
    `tests/unit/test_frozen_copy_sweep_cli.py`, `tests/integration/test_frozen_copy_sweep_postgres.py` (new)
- **A3** (periodic trigger, chart values, runbook)
  - `src/aigateway/core/frozen_copy/sweep_trigger.py` (new), `src/aigateway/main.py`
  - `tests/unit/test_frozen_copy_sweep_trigger.py`, `tests/unit/test_frozen_copy_sweep_lifespan.py` (new)
  - `charts/aigateway/values.yaml`, `charts/aigateway/templates/configmap.yaml`, `charts/aigateway/README.md`
  - `apps/aigateway/DEPLOYMENT.md`

## Test plan

RED first for each unit. Test ids are those of `prd/copy-sweep.md` §7.

- A1: S-28 (migration up, down, no autodetector change), S-9 (seal of an `abandoned` or
  `expired` copy → 410; other account → 404). CH-1 and CH-2 stay green with no edit.
- A2: S-2, S-5, S-7, S-8, S-10, S-11, S-12, S-27, S-29 (SQLite); S-13, S-31, S-36, S-15, S-16
  (Postgres, `AIGW_TEST_PG=1`); S-22 (setting limits); S-17, S-21, S-34 (command).
- A3: S-23 (trigger timing, a failed run does not stop the loop), S-24 (lifespan arms and
  stops the trigger; no enable setting), S-25 (run log record has no account name), S-32 (start
  log record).
- Invariant protected: a copy that is `sealed`, or that got an entry inside the idle time, is
  never marked and never loses an entry.

## Acceptance

- All gates of the `aigateway` stack are green (`run_gates.py aigateway`).
- The Postgres lane is green with `AIGW_TEST_PG=1`.
- No existing test is changed, apart from the two assertions of the owner record.
- An independent design review against the spec has no open major finding.

## Notes at start

- Owner approvals (2026-11-17): the plan, and the assertion-only change of
  `test_0014_creates_both_tables_with_the_design_columns`.
- The build found a second assertion in the same test that 0018 breaks (the exact list of
  nullable columns of `frozen_copies`). The owner approved a second assertion-only change on
  2026-11-17: the check is limited to the eight columns of 0014. The record has both changes.
- The approval record names the PR branch `OME-1947-frozen-copy-retention-stack-a` (the matcher
  compares the current branch name).
- `tortoise-dev` companion skill (mandatory in the card) is not installed on this machine. The
  migration and the model follow the house pattern of migrations 0015 to 0017, as the plan
  names them. Proposed to the owner: install the plugin.
- 2026-11-17: the owner ordered the commits and one pull request for A1, A2 and A3.

## Outcome (fill at the end — required before COMMIT)

State on 2026-11-17: the code of A1, A2 and A3 is built, reviewed and committed. `status` stays
`in_progress` until the pull request is merged.

- **Actual files:** as planned, plus:
  - `tests/unit/test_frozen_copy_sweep_support.py` (shared test helpers; review finding F10)
  - `tests/unit/test_chart_render_frozen_copy_sweep.py` (chart render test)
  - the chart is at `apps/aigateway/charts/aigateway/` (the plan wrote `charts/aigateway/`)
- **Commits** (branch `OME-1947-frozen-copy-retention-stack-a`, rebased on `origin/main` f683cd2e6;
  one pull request, squash-merge):
  - 7ba4f2321 — docs(aigateway): spec and stack A plan for frozen copy retention (OME-1947)
  - 5db471fa0 — feat(aigateway): add frozen copy retention states and migration 0018 (OME-1947)
  - 4bc50d705 — feat(aigateway): sweep abandoned frozen copies (OME-1947)
  - 5ceafc31a — feat(aigateway): run the frozen copy sweep on a periodic trigger (OME-1947)
  - one more docs commit records this outcome and the PR branch name in the approval record.
- **Gates:** `uv run .claude/scripts/run_gates.py aigateway` → ALL GATES GREEN (approved
  OME-1947 test transition; append-only check; ruff check; ruff format; pyright; enterprise
  check; pytest with coverage: 7,966 passed, 125 skipped, coverage 94.16%).
  Run again after the rebase, with `--base` at the merge base with `origin/main` (f683cd2e6):
  ALL GATES GREEN.
  Postgres lane, `AIGW_TEST_PG=1 uv run pytest -m needs_postgres`: 80 passed, 5 failed. The 5
  failures are all in `tests/integration/test_cache_snapshot_upload_postgres.py` with
  `FileNotFoundError: 'pg_dump'`: this machine has no `pg_dump`. This work does not touch that
  code. The 6 tests of `test_frozen_copy_sweep_postgres.py` passed (S-13, S-15, S-16, S-31,
  S-36 and the database clock).
- **Design review:** verdict ACCEPT-WITH-FIXES, 12 findings, no major. 11 fixed and checked
  again (F1 a run reports `newest entry not found`; F2 one ERROR record for a failed run; F3 a
  chunk that uses the budget exactly completes the copy; F4, F5 dead code removed; F7 shutdown
  removes the trigger that the lifespan built; F8 to F12 conventions, test helpers, and the
  runbook note that the 0018 downgrade does not limit its lock wait). F6 stays open, low: the
  trigger properties `last_started_at` and `interval_s` are read only by tests; `contracts.md`
  K7 names the `now` input.
- **Deviations:**
  - The existing test needed two assertion changes, not one. The owner approved both.
  - One pull request for A1, A2 and A3, not three (owner decision; point 14 of the plan).
  - The build corrections are at the end of the plan (13 points).
  - `tortoise-dev` companion skill not installed; house pattern of 0015 to 0017 used.
  - `main.py` is 527 lines and `config.py` is 506 lines; both were above 450 before this work.
  - The 0018 downgrade is tested on SQLite only (S-28), as the plan says.
  - CH-1: `tests/unit/test_frozen_copy_routes.py:212`. CH-2:
    `tests/unit/test_frozen_copy_routes.py:102`. Both green with no edit.
