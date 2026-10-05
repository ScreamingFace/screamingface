---
ticket: OME-1488
stack: scoreboard
status: done
started: 2026-10-05
finished: 2026-10-05
---

# name-default-connection — name the request connection in every scoreboard transaction

## Intent

#1213 (`OME-1452`, `aa582c12`) gave the web app a second Tortoise connection, `readiness`, reserved
for `/readyz`. With two connections Tortoise refuses an unnamed `in_transaction()`
(`ParamsError: ... specify connection_name: ['default', 'readiness']`). The web app's leaderboard
and frontier reads (`ScoreStore.read_snapshot`) and its submission path (`submit`,
`_bind_idempotency_key`, `_confirm_replayable`, `_replayed_row_survives`) all open unnamed
transactions, so on dev since ~09:38 UTC every board returns 500 and submissions fail. The CLIs
(`delete_scores`, `purge_private_benchmark`, `import_baselines`) start with one connection
(`init_db` without a pool) and are not affected today.

Name the request connection at every transaction, through one constant, so a second connection can
never again make the choice ambiguous.

## Planned changes

- `apps/scoreboard/src/scoreboard/db.py`: `DEFAULT_CONNECTION = "default"`, used by the config
  builder too, so the name has one source.
- `connection_name=DEFAULT_CONNECTION` at all 8 `in_transaction()` calls: `scores/store.py` (5),
  `scores/baseline_store.py` (1), `delete_scores.py` (1), `purge_private_benchmark.py` (1). The CLI
  ones are not broken today, but the same rule keeps them safe if a CLI ever gains a second
  connection.
- `tests/unit/test_server_connections.py`: initialise Tortoise with the app's real two-connection
  config (`build_server_tortoise_config`) and drive a board read, the frontier read, a submission,
  a replay and a delete through it.
- Spec, plan, mirror.

## Test plan

- RED: the new tests fail with the production `ParamsError` before the fix.
- GREEN: they pass after; the full suite stays green.
- Guard: a test that fails if any `in_transaction()` in the package is called without a
  connection name, checked by parsing the source (AST), not by text search.

## Acceptance

- The leaderboard, the frontier and a submission work with two configured connections.
- No unnamed `in_transaction()` remains in `apps/scoreboard/src`.
- Full scoreboard gates green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned. `db.py` (`DEFAULT_CONNECTION`, used by the config builder and
  exported); `connection_name=DEFAULT_CONNECTION` at the 8 calls in `scores/store.py` (5),
  `scores/baseline_store.py`, `delete_scores.py`, `purge_private_benchmark.py`;
  `tests/unit/test_server_connections.py` (5 tests); spec, plan, mirror.
- **Commits:** one, `Refs: OME-1488`.
- **Gates:** `run_gates.py scoreboard --base origin/main` ALL GATES GREEN with no skip (no prior test
  changed); 905 passed, 9 skipped.
- **RED/GREEN:** the four behaviour tests failed with the exact `ParamsError` the dev pod logged;
  the AST guard listed all 8 unnamed calls. All pass after the fix.
- **Mutation:** removing the name from `read_snapshot` alone fails the board-read test and the guard.
- **Deviations:** the CLIs turned out not to be affected today (they start with one connection), so
  naming the connection there is preventive, not a fix. The ticket said otherwise and was corrected.
