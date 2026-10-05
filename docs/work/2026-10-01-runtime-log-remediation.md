---
ticket: OME-1048
stack: screamingface
status: done
started: 2026-10-01
finished: 2026-10-01
---

# runtime-log-remediation — tighten rotated runtime-log backups and add `logs --purge`

## Intent

OME-990 made `runtime.log` `0600` and tightens it on reopen, but rotated backups
`runtime.log.1..5` written by the earlier code keep `0644` until they roll off, and nothing
removes prompts already written by pre-OME-990 versions. Owner decision (lane brief):
(a) chmod `0600` on every rotated backup unconditionally at start, plus (c) an explicit
`screamingface logs --purge`. Explicitly NOT (b) an automatic purge.

## Planned changes

- `packages/screamingface/src/screamingface/_runtime/runtime_logging.py` — `RuntimeLog`
  tightens every existing backup to `0600` when it opens (every start); a `purge_runtime_log`
  helper.
- `packages/screamingface/src/screamingface/_runtime/cli.py` — `logs --purge`.
- `packages/screamingface/tests/test_runtime_log_remediation.py` — new tests.
- `packages/screamingface/README.md`, `CHANGELOG.md` — document `--purge`.

## Test plan

- After a start, every path from `cli._log_paths` is `0600` (backups planted `0644`).
- Missing/gappy backups (e.g. only `.2` and `.5`) don't error.
- `logs --purge` removes every rotated backup and empties the live log, keeps it `0600`, and
  does not tail; a running writer keeps appending to the emptied file.
- `logs --purge` with no log present exits cleanly and says there is nothing to purge.
- Existing rotation tests unchanged and green.

## Acceptance

- No runtime-log file is group/world-readable after `screamingface up`.
- `screamingface logs --purge` leaves no prompt history on disk in the log set.
- `run_gates.py screamingface` green; prior tests unmodified.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned. `runtime_logging.py` gains `_backup_paths` (now the single
  source for `cli._log_paths`), `_tighten_backups` (called from `RuntimeLog.__init__`, i.e.
  every start) and `purge_runtime_log`. `cli.py` gains `logs --purge`, dispatched through
  `_logs_command` so `main` stays within the statement budget. Also `tests/test_runtime_log_remediation.py`
  (7 tests), README, CHANGELOG, and the `docs/tasks/` mirror.
- **Commits:** `feat(screamingface): tighten rotated runtime logs and add logs --purge` (this
  ledger's commit).
- **Gates:** `run_gates.py screamingface` ALL GATES GREEN. That covers append-only, ruff,
  format, pyright, pytest (2110 passed / 26 skipped at 96% coverage), notebooks, build and
  distribution. Existing rotation tests are unchanged and green.
- **Smoke:** `screamingface logs --purge` on an empty data dir prints "no runtime log to
  purge". With `runtime.log` + `runtime.log.2` present it prints "purged 2 runtime log
  file(s)" and leaves an empty `0600` `runtime.log`.
- **Deviations:** none from the owner's decision ((a) + (c), not (b)). Design choices made
  inside it:
  - `--purge` truncates the live log rather than unlinking it, so a running stack stays
    visible to `logs`.
  - There is no interactive confirmation, because the flag is the explicit opt-in.
  - The purge covers exactly the `cli._log_paths` set (backups 1..`LOG_BACKUPS`).
  - It is not a secure erase, and the README says so.
