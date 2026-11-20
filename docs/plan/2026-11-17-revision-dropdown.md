# Plan — revision selector on each leaderboard (OME-1708)

Spec: `docs/spec/2026-11-17-revision-dropdown.md`. One landing (`apps/scoreboard`), two
PRs so each stays under the review size cap. `sdlc-python` loop, with the mandatory
`tortoise-dev` companion for the model and migration.

## PR 1 — revision history and API (backend only; the page is unchanged)

1. **RED:**
   - Model and migration tests for `BenchmarkRevision`: unique (benchmark, revision);
     backfill from `scores` (MIN date, MAX count for old revisions, registered count for
     the current one, null revisions left out, all marked inferred).
   - `register_benchmark` records a new revision once and never overwrites it.
2. **GREEN:** `scores/models/benchmark_revision.py`, migration `0024`, and the recording in
   `store.register_benchmark`.
3. **RED:** route tests:
   - `GET /v1/leaderboard/{id}/revisions` is ordered newest first, with `until`, complete-run
     `result_count` and `current`, and follows the private-board rule.
   - `?revision=` on the board and frontier ranks within that revision and its Case count;
     an unknown revision returns 404.
   - With no parameter, the existing board and frontier responses are byte-identical
     (the current tests stay unedited).
4. **GREEN:**
   - `routes/leaderboard.py` passes the chosen revision and its count to
     `store.leaderboard` and `leaderboard_pareto_inputs`.
   - New store read for the revision list.
   - History response stays unchanged; the portal reads the current id from `/revisions`.
5. **Gates:** `run_gates.py scoreboard`. Then the PR.

## PR 2 — portal (after PR 1 merges)

1. **RED:** portal JS tests, in the existing `tests/portal` suites:
   - Option labels: Latest/Previous, the date range, "about" for inferred dates, short id,
     result count.
   - One revision renders plain text; two or more render a select.
   - `?revision=` round-trips; an unknown id falls back to Latest with the notice.
   - The empty-Latest line points to the previous revision.
   - The history page's Revision column, "latest" tag and link.
2. **GREEN:**
   - `benchmark.html` / `benchmark.js` (`init()` at `:403`) fetch `/revisions` and the
     chosen revision's board and frontier.
   - `spec.js` adds the column.
   - CSS in `portal.css`.
3. **Visual check:** desktop and phone, light and dark, against the mockups. The owner
   looks before the PR.
4. **Gates:** `run_gates.py scoreboard`, then the PR. Close: ledger outcome, mirror, Linear.

## Coordination

- OME-1909 (Khoa) also plans migration 0024: tell him on the PR, and whichever lands second
  renumbers.
- Code starts after the product review of the mockups or Filip's sign-off (ledger
  decision 7).

Review follow-up: reject unregistered scopes; suppress inferred historical frontiers;
put Latest first; count in SQL with current scope; add regression and purge tests.

## Authorized review follow-up — 2026-11-20

Rebase PR #1943, preserving the union of portal test entries. Correct the historical API fixture and pin neutral scope wording. Add versioned baseline-only status regressions, then adjust scope/status rendering without changing the API. Run full scoreboard gates and desktop/mobile light/dark previews before updating the PR.
