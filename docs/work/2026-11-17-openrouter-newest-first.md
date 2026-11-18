---
ticket: OME-1956
stack: aigateway
status: done   # planned | in_progress | done | blocked
started: 2026-11-17
finished: 2026-11-17
---

# openrouter-newest-first — list the newest OpenRouter models first

## Intent

The gateway lists the discovered OpenRouter models in alphabetical order. A researcher wants the newest models first. The gateway reads the release date (`created`) of each catalogue row and sorts the discovered rows newest first. Spec and plan are in the worktree `models-list-live-catalog`: `docs/spec/2026-11-17-OME-1955-refresh-curated-model-list.md` §5.2 and `docs/plan/2026-11-17-OME-1955-refresh-curated-model-list.md` §3 (PR B).

## Planned changes

- `apps/aigateway/src/aigateway/plugins/openrouter_provider/live_models.py`
- `apps/aigateway/src/aigateway/plugins/openrouter_provider/plugin.py`
- `apps/aigateway/tests/unit/openrouter/test_live_models_newest_first.py (new)`

## Test plan

- The eight tests of the plan, §3, written first. No current test changes.

## Acceptance

- With dates, the discovered OpenRouter rows are newest first. With no dates, the order is the order of today. The `aigateway` gates are green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
  - `apps/aigateway/src/aigateway/plugins/openrouter_provider/live_models.py` (`parse_page_created`, `LiveCatalog.created`, the `created` keyword of `live_listing_entries`, the newest-first sort, docstrings)
  - `apps/aigateway/src/aigateway/plugins/openrouter_provider/plugin.py` (`created=catalog.created` in `discover_live_models`)
  - `apps/aigateway/tests/unit/openrouter/test_live_models_newest_first.py` (new, 13 tests)
- **Commits:** `443a1f0a4` feat(aigateway): list the newest OpenRouter models first. The docs commit follows it.
- **Gates:**
  - RED: the new test file failed at collection, `ImportError: cannot import name 'parse_page_created'`.
  - Final run on 2026-11-17, after the design review fixes: `uv run .claude/scripts/run_gates.py aigateway` gives ALL GATES GREEN, with the append-only check green. `uv run pytest tests/unit/openrouter -q` gives 1101 passed. No current test changed.
- **Deviations:**
  - (a) A first gate run was red on `tests/unit/auth/test_login.py::test_unknown_user_timing_close_to_wrong_password`, a timing test in a file that this change does not touch. It failed while three test suites ran at the same time on this machine, and it passed in the final run.
  - (b) Design review (Opus), verdict ACCEPT-WITH-FIXES. Fixes applied: the operator test and the no-dates test now use ids for which only the new sort key gives the result; the plugin test has a row with a bad date; a new test shows that dates change the order and not the row content; the docstrings use double backticks, give the tie rule, and name the dates in `LiveCatalog`. Not applied: the test helpers stay copies, as in `test_openrouter_input_modalities.py`.
