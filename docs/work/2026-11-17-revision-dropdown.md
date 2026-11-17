---
ticket: OME-1708
stack: scoreboard
status: in_progress
started: 2026-11-17
finished:
---

# revision-dropdown — a revision selector on each leaderboard

## Intent

Each Benchmark leaderboard shows only its current registered revision
(`apps/scoreboard/src/scoreboard/scores/store.py:1035`). When a revision moves, every
entry under the old id disappears from view. OME-1909 is about to make that routine: a
grading change will now bump the revision, and old entries are re-graded from their
pinned caches. Its decision (2026-11-17) is that revisions are shown on the leaderboard
through this ticket's dropdown. Give each leaderboard a revision selector that defaults
to "Latest", lists the earlier revisions with readable labels, and scopes the ranked
table, frontier and submission history to the chosen revision.

Ticket direction (Irina): build HTML mockups for product feedback before implementation;
default to "Latest" instead of "All"; prefer readable labels or dates, falling back to the
revision id; keep ranking and completeness within the selected revision; existing API
calls keep their current default.

## What exists (origin/main, 2026-11-17)

- `Score.benchmark_revision` records each score's revision
  (`scores/models/score.py:123-131`).
- `Benchmark` holds only the current `revision` and `case_count`
  (`scores/models/benchmark.py:23-38`). The seed job overwrites them from the Engine's
  `GET /v1/benchmarks` (`seed.py:560-615`), so a past revision's case count is lost.
- No table of past revisions exists; the only record is the distinct
  `scores.benchmark_revision` values.
- No route takes a `revision` parameter. `store.leaderboard(registered_revision=…)` and
  `leaderboard_pareto_inputs(registered_revision=…)` already accept one
  (`store.py:2212-2288`). Submission history (`routes/leaderboard.py:443-492`) is not
  filtered by revision at all.
- Portal: `portal/benchmark.html` + `benchmark.js` (`init()` at `:403`); the "Has scores"
  checkbox in `catalog.js` is the remembered-filter pattern to reuse.

## Decisions (Filip, 2026-11-17)

1. **Empty Latest:** Latest stays selected after a bump and shows an empty table with one
   line pointing to the previous revision's results ("No results under this revision yet.
   12 results under 32a91cf1 (previous) — show them."). No silent fallback, no mixing.
2. **Labels:** date range and short id, with result counts, e.g. "Latest · since 17 Nov
   2026 · a41c09e2 · 9 results" and "Previous · 9 Oct – 17 Nov 2026 · 32a91cf1 · 12
   results". The date is when the scoreboard first saw the revision, recorded from now
   on; for older revisions, the first submission date, marked approximate.
3. **Placement (option A of `docs/spec/2026-11-17-revision-dropdown/mockups/placement.html`):**
   under the benchmark title, above the stats, scoping the stats, score bars, frontier
   chart and table together. A dropdown only when the benchmark has two or more
   revisions; otherwise plain text "Revision a41c09e2 · since 9 Oct 2026".
4. **Submission history page:** keeps every run of the recipe, newest first, with a new
   Revision column (short id, a "latest" tag on the current one, the id linking to that
   revision's leaderboard). Mockup 1 of `mockups/all-revisions.html`.
5. **URL state:** the chosen revision lives in `?revision=` (updated without a reload); no
   parameter means Latest. Not remembered across visits.
6. **No "All revisions" choice** in the leaderboard dropdown for now: every leaderboard
   view shows one grading. Mockup 2 of `mockups/all-revisions.html` stays as a possible
   later addition.
7. **Product review:** the mockups are published as a private artifact
   (https://claude.ai/artifact/VTP23xFifCTgQa2scbe58S) for Irina; spec and plan proceed
   meanwhile, code starts after her or Filip's sign-off.
8. **Partial runs stay off every revision's board**, as on the current board: only runs
   covering the revision's full Case count are ranked. New revisions record their Case
   count when the scoreboard first sees them. Older revisions get it backfilled once as
   the largest question count among their results (a run can never exceed its
   revision's Cases, and a partial run always reports fewer), marked as inferred.

## Planned changes

Phase 1 (this step): HTML mockups only, for product feedback. No code.

- `docs/spec/2026-11-17-revision-dropdown/mockups/*.html`: the benchmark page with the
  dropdown in its proposed states.

Phase 2 (after product sign-off): spec, plan, then code. Expected scope, to confirm:
revision history storage (seed job records each revision it sees), a list-revisions
route, a `revision` parameter on the leaderboard, frontier and history routes, and the
portal dropdown.

## Test plan

Written in the spec once the mockups are agreed.

## Acceptance

- Phase 1: Irina and Filip agree on the dropdown's placement, labels, default and the
  empty-latest state.

## Outcome (fill at the end — required before COMMIT)

### PR 1 — revision history and API (2026-11-17)

- **Actual files:**
  - Model `scores/models/benchmark_revision.py` and migration `0024_benchmark_revisions.py`
    (table plus a portable SQL backfill).
  - `scores/revisions.py`: `record_revision`, `find_revision`, `list_revisions`. Kept out of
    `store.py`, which is already 2,487 lines.
  - `routes/revisions.py`: `GET /v1/leaderboard/{id}/revisions`.
  - `routes/leaderboard.py`: `?revision=` on the board and frontier.
  - `store.register_benchmark` now records each revision.
  - `retire_benchmark.py` and `purge_private_benchmark.py` delete revision rows first.
  - `main.py` registers the router.
  - Tests: `tests/unit/scores/test_benchmark_revisions.py` (6),
    `tests/unit/test_leaderboard_revisions_route.py` (9) and
    `tests/unit/test_migration_0024_benchmark_revisions.py` (2).
- **Commits:** the PR 1 commit (`Refs: OME-1708`).
- **Gates:** `run_gates.py scoreboard` all green.
  - Append-only check, ruff, pyright, the full pytest suite (1,993 passed) with coverage
    above 80%, and every portal Node suite.
  - No prior test was edited.
  - The backfill was also run on a local Postgres 17 with data. It gave the same rows as
    SQLite. CI runs every migration on Postgres too, but only on empty tables.
- **Deviations from the plan:**
  - The history response does NOT gain `registered_revision`. Two existing tests pin its
    exact shape, so the page reads `current` from `/revisions` instead (spec updated).
  - Retire and purge needed a change: on SQLite, cascaded revision rows count in the
    delete count, which their exactly-one-row checks refused. Both now delete revision
    rows first in the same transaction.
  - `create_app` registers routers in a loop; one more line pushed it over the statement
    limit.
  - The new route answers a private board with a 404, after a fresh visibility read, so
    the visibility-exit guard needed no new allowlist entry.
