---
ticket: OME-1487
stack: scoreboard
status: done
started: 2026-10-06
finished: 2026-10-06
---

# OME-1487-unreadable-saving — keep the reproduction cost unknown when a stored saving cannot be read

## Intent

The raw leaderboard and Pareto reads (`scores/store.py`, `_to_python_rows`) degrade an undecodable
money column to `None`. For the two cache savings `None` means "no saving", so a `complete` row with
an unreadable saving is served at its bare spend and can move onto the Pareto frontier. Make an
unreadable saving yield an unknown served cost instead, so the row leaves the frontier like any
other unpriced row. Absent savings are unaffected.

## Planned changes

- `apps/scoreboard/src/scoreboard/scores/store.py`: `_to_python_rows` replaces an undecodable
  saving with a module sentinel (structural identity, not a string); `_serve_reproduction_cost`
  serves `None` when either popped saving is that sentinel, else calls `reproduction_cost` as today.
- `apps/scoreboard/tests/unit/test_unreadable_saving.py`: new regression tests.

## Test plan

- Parametrized over both saving columns: a `complete` row whose saving is written as malformed text
  by raw SQL serves `run_cost_usd` null and `on_pareto_frontier` false in the ranked table
  (`GET /v1/leaderboard/{board}`).
- Same parametrization through `ScoreStore.leaderboard_pareto_inputs`: the entry's cost is `None`.
- The frontier card counts only the priced row.
- An absent (NULL) saving serves the bare spend exactly, through both paths.
- Unit: `_serve_reproduction_cost` on a row with the sentinel returns `None`; a NULL saving returns
  the spend.

## Acceptance

- A `complete` row with an unreadable reported or archive saving serves no cost and is not on the
  frontier.
- A row whose saving is absent serves exactly what it does today.
- `uv run .claude/scripts/run_gates.py scoreboard` green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** `apps/scoreboard/src/scoreboard/scores/store.py`,
  `apps/scoreboard/tests/unit/test_unreadable_saving.py` (13 tests), plus this ledger and the
  `docs/tasks/2026-10-05-OME-1487-unreadable-saving.md` mirror. No schema change, no migration.
- **Commits:**
  - `74f5f6f3c fix(scoreboard): keep the reproduction cost unknown when a saving cannot be read`
    (table and Pareto input).
  - `fix(scoreboard): serve the frontier card when a money column cannot be read` (frontier
    replay; the second commit on the branch).
- **Gates:** `run_gates.py scoreboard` ALL GATES GREEN: append-only check, ruff check, ruff format,
  pyright, pytest 942 passed / 9 skipped (coverage 90% total, store.py 98%), node portal 62/62.
- **Deviations:**
  - Scope widened by owner decision (2026-10-06): `GET /v1/leaderboard/{board}/frontier` returned
    500 on any unreadable money column, because `frontier_history_inputs` read through the ORM
    `.values()` path, which raises `InvalidOperation`. It now reads a raw pypika projection
    (`_build_history_inputs_query`) through `_to_python_rows` and `_serve_reproduction_cost`, like
    the table and the Pareto input. Tests cover all three money columns plus an absent saving.
  - The planned direct `_serve_reproduction_cost` unit test was dropped: the route and store tests
    already cover the sentinel and the NULL branch end to end.
  - The rule is unconditional as the ticket states: any unreadable saving nulls the served cost,
    whatever the status. Only `complete` rows add savings, and `partial`/`unavailable` carry no
    spend by contract, so the difference is limited to a corrupt legacy row.
