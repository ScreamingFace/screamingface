---
ticket: OME-1947
stack: aigateway
status: in_progress   # planned | in_progress | done | blocked
started: 2026-11-17
finished:
---

# frozen-copy-expiry — sealed frozen copies that no Score claims expire after 90 days (unit C1)

## Intent

A sealed frozen copy that no leaderboard Score claims is never deleted, so the gateway database
grows with no limit (OME-1947). Unit C1 adds the expiry rule to the retention sweep: an unclaimed
sealed copy becomes `expired` 90 days after its clock starts, and its entries are deleted. A
replay of an expired copy gets 410 `frozen_copy_expired`.

Spec: `docs/spec/2026-11-16-frozen-copy-retention/`. Plan:
`docs/plan/2026-11-17-frozen-copy-retention-stack-c.md` (owner approved 2026-11-17).

## Planned changes

Paths are under `apps/aigateway/` unless they start with `.claude/`.

- `.claude/test-change-approvals/OME-1947.json` (branch name, two files; owner decision Q27)
- `tests/unit/test_frozen_copy_sweep.py`, `tests/unit/test_frozen_copy_sweep_cli.py` (one
  assertion each; owner approved, Q27)
- `src/aigateway/core/frozen_copy/models.py` (`retention_from`)
- `src/aigateway/migrations/0019_frozen_copy_retention_clock.py` (new; S1: ships with the model)
- `src/aigateway/core/frozen_copy/sweep_rules.py` (new; the rules move here, Q30; `ExpiryRule`)
- `src/aigateway/core/frozen_copy/sweep.py` (imports, builder)
- `src/aigateway/config.py` (`frozen_copy_unclaimed_ttl_seconds`), `src/aigateway/main.py` (one
  log statement, Q31)
- `src/aigateway/routes/frozen_copies.py` (410 on replay of an expired copy)
- `charts/aigateway/values.yaml`, `templates/configmap.yaml`, `README.md`; `DEPLOYMENT.md`
- New tests: `tests/unit/test_frozen_copy_retention_clock_migration.py`,
  `tests/unit/test_frozen_copy_expiry.py`, `tests/unit/test_chart_render_frozen_copy_expiry.py`,
  `tests/integration/test_frozen_copy_retention_clock_postgres.py`,
  `tests/integration/test_frozen_copy_expiry_postgres.py`
- Appended tests: `tests/unit/test_frozen_copy_sweep_settings.py`,
  `tests/unit/test_frozen_copy_sweep_lifespan.py`, `tests/unit/test_frozen_copy_claim.py` (K-25),
  `tests/unit/test_frozen_copy_replay.py` (R-1 to R-3)

## Test plan

RED first. Test ids of `prd/copy-sweep.md` §7 and `prd/expired-copy-replay.md`.

- S-33 (migration 0019 up, down, stamp of sealed copies; SQLite and Postgres).
- S-6, S-1, S-4, S-35, S-37 (the expiry rule, the setting, the dry run of the command).
- S-14 (Postgres: a claim that commits first wins over the expiry mark) and the `EXPLAIN` check.
- K-25 (a claim does not evaluate the expiry rule; an unclaimed copy of the same age expires).
- R-1, R-2, R-3 (410 on replay of an expired copy; an abandoned copy stays 404).
- All stack A tests of the sweep, the command and the trigger stay green after the move (C1.2).
- Invariant protected: a copy with `claimed_at` set never expires and never loses an entry.

## Acceptance

- `run_gates.py aigateway` all green; the Postgres lane green with `AIGW_TEST_PG=1`.
- No existing test is changed, apart from the two assertions of the owner record (Q27).
- An independent design review against the spec has no open major finding.
- **Do not merge until steps 3 and 4 of `00-overview.md` §7.1 are done in production.**

## Notes at start

- Owner order of 2026-11-17: both plans approved; build stacks B and C in parallel.
- The branch is cut from the B1 branch (commit 24e2304c3), because pull request #1911 and B1 are
  not merged. After both are merged, rebase the branch onto `origin/main`. The local gates use
  `--base 24e2304c3`.
- B1 moved `_utc` of `sweep.py` to `core/frozen_copy/times.py` (`as_utc`). The plan for C1.2
  names `_utc`; this unit uses `as_utc`.
- The `tortoise-dev` companion skill is not installed on this machine. The migration and the
  model follow the house pattern of migration 0018, as the plan names it.

## Outcome (fill at the end — required before COMMIT)

State on 2026-11-17: the code is built, reviewed and committed on the branch
`OME-1947-frozen-copy-expiry`. `status` stays `in_progress` until the pull request is merged.

- **Actual files:** as planned, plus `tests/unit/test_frozen_copy_support.py` (two shared test
  helpers appended, `lookup_path` and `set_copy_status`; review finding F2).
- **Commits:** one commit,
  `feat(aigateway): expire sealed frozen copies that no score claims (OME-1947)`.
- **Gates:** `uv run .claude/scripts/run_gates.py aigateway --base 24e2304c3` → ALL GATES GREEN
  (approved OME-1947 test transition for the two files of Q27; append-only check; ruff check;
  ruff format; pyright; enterprise check; pytest with coverage).
  Postgres lane, `AIGW_TEST_PG=1 uv run pytest -m needs_postgres`: 84 passed, 5 failed. The 5
  failures are all in `tests/integration/test_cache_snapshot_upload_postgres.py`: this machine
  has no `pg_dump`. This work does not touch that code. S-33 and S-14 with the `EXPLAIN` check
  passed on Postgres, and so did the stack A lock tests after the move of the rules.
- **Design review:** verdict ACCEPT-WITH-FIXES, 9 low findings, none major. Fixed: F1 (dead
  helper), F2 (shared test helpers), F4 (the two rules call `mark_locked` in one form), F5
  (`sweep.py` docstring names the claim and the lock step), F7 (docstring form), F8 (runbook
  wrap), F9 (the docstring of migration 0019 says that the stamp runs in the transaction of the
  `ADD COLUMN`, so the table lock is held until the `UPDATE` ends, and that the 3-second lock
  wait also applies to the row locks of the `UPDATE`). Open, low: F3
  (`tests/unit/test_frozen_copy_replay.py` grows from 490 to 549 lines; it was above 450 before
  this work, and the plan names it for R-1 to R-3) and F6 (the comment about the final states in
  `models.py` is now an AIDEV-NOTE; the old text was no longer true).
- **Deviations:**
  - `_utc` does not exist after B1; this unit uses `as_utc` of `core/frozen_copy/times.py`. Only
    `_is_postgres` moved with its name.
  - The approval record `.claude/test-change-approvals/OME-1947.json` names this branch and has
    three files. `base_blob` of the two new files is the blob at the stack A branch tip; if
    `main` changes one of the two files before this branch is rebased, compute the record again.
    The two files got no other edit.
  - The 0019 downgrade and its stamp are tested on SQLite and on Postgres (S-33).
  - CH-1: `tests/unit/test_frozen_copy_replay.py:337` and
    `tests/unit/test_frozen_copy_routes.py:330`. Both green with no edit.
  - **Do not merge until steps 3 and 4 of `00-overview.md` §7.1 are done in production.**

## Review fix (2026-11-23)

A code review of the stack found that `GET /v1/frozen-copies/{id}/provenance` shares
`_sealed_copy`, so it changes from 404 to 410 for an `expired` copy, and no contract or test said
so. Owner decision 2026-11-23 (option A): keep the 410, the same answer as a replay. Changed: the
route docstring, contracts K3 (route list, R-8), `prd/expired-copy-replay.md` (R-8),
`DEPLOYMENT.md`. New test file `tests/unit/test_frozen_copy_provenance_expired.py` (expired →
410 with no `X-AIGW-Replay`; abandoned → 404). No code path changed; no existing test changed.
