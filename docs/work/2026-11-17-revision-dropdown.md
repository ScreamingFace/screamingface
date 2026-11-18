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
route, a `revision` parameter on the leaderboard and frontier routes, and the
portal dropdown.

## Test plan

Migration, recording and route regression tests cover revision scope, completeness,
visibility, ordering and result counts. Run the scoreboard gates before publication.

## Acceptance

- Phase 1: Irina and Filip agree on the dropdown's placement, labels, default and the
  empty-latest state.

- Backend: historical scopes stay isolated; default reads stay unchanged; unknown or
  unregistered scopes cannot make a frontier claim; Latest always appears first.
- Portal: complete desktop/mobile, light/dark review before publishing PR 2.

## Outcome

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

## Review fixes — 2026-11-17 (PR #1892)

Intent: address the two blockers and the count/query/purge gaps from the review.
Filip explicitly authorized fixing the review comments in this session. This authorizes
the backend corrections; it is not a record of prior product approval for PR 2.

Planned changes:
- Backfill only boards with a registered revision and reject explicit selection on
  unregistered boards, even if stale revision rows exist.
- Historical ids from score submissions cannot be authenticated retrospectively. Keep
  those archives browsable, but suppress frontier claims for inferred/unknown counts.
- Put Latest first regardless of its first-seen date; never fabricate a rollback date.
- Count results in SQL using the ranking filters and the current registered count.
- Add purge regression coverage; correct the spec and plan's obsolete statements.

Validation: add failing regressions first, then run all scoreboard gates and migration
checks. Check historical count anomalies read-only if production access is available.
The MAX heuristic remains inferred; switching to a mode cannot establish provenance.

Review-fix outcome:
- Both blockers fixed, including the inferred historical frontier policy on registered
  boards, empty Latest and rollback ordering. Default responses remain unchanged.
- Current result counts use the live count; historical counts run as SQL aggregates.
  Added a purge-with-revisions regression; removing the explicit delete makes it fail.
  No existing tests were changed.
- New regressions: 9 failures before fixes, then 10 passing (including the purge case
  that already passed). All 21 focused revision/migration cases pass.
- Full scoreboard gates passed: lint, formatting, types, full Python suite with coverage,
  append-only preservation and every portal Node suite.
- Local PostgreSQL: 32 route/recording/migration cases passed. A separate populated
  migration check passed for inferred history, current counts, empty Latest and
  unregistered-board exclusion, without deleting scores.
- Production count audit remains outstanding: the supplied firecall SSH host timed out
  on 2026-11-17. The spec includes the exact read-only anomaly query. No live reads or
  writes succeeded. MAX remains explicitly inferred; historical frontier claims are off.
- Schema check: Tortoise `makemigrations` reports "No changes detected".
- PR 2's portal work remains on its separate branch; this commit changes no portal files.

### PR 2 — portal selector (2026-11-17, stacked on PR 1)

- **Actual files:**
  - `portal/revision-selector.js`: pure labels, URL state, fallback and empty-Latest pointer.
  - `portal/benchmark.html` and `benchmark.js`: the selector under the title, `load(revision)`
    re-run on each switch, the not-found notice and the empty-Latest pointer.
  - `portal/spec.html` and `spec.js`: the Revision column, the "latest" tag and dimmed older
    rows.
  - `portal/portal.css`.
  - `tests/portal/revision-selector.test.js` (8), wired into the sdlc card gate and
    `scoreboard-tests.yml`.
- **Gates:** `run_gates.py scoreboard` all green: the full pytest suite plus every portal
  Node suite, the new one included. No prior test was edited.
- **Visual check:** a local scoreboard on this branch with seeded sample boards, at 1280px:
  - MMLU-Pro on Latest and on Previous;
  - LAB-Bench's empty Latest with the pointer;
  - IFEval's single revision as plain text;
  - an unknown `?revision=` with its fallback notice;
  - the history page's Revision column.

  At 390px, headless Chrome clips the existing page too. The dropdown now shrinks inside
  its row anyway. The owner looks before the PR.
- **Deviations:**
  - Served portal files may not carry ticket ids, agent markers (`FEATURE:`,
    `INVARIANT`) or repository paths (`test_portal_static.py`). The portal comments use
    plain prose instead.
  - The selector sits under the title and the "Follow this board" button, above the
    description. That is option A's place, with the page's existing follow button
    between them.
- **Rebase onto main (2026-11-18):** PR 1 merged with the review fixes above, and main gained
  board addresses (`/benchmarks/<id>/`, OME-1953). Adjustments:
  - `benchmark.js` keeps main's rule that only `benchmark.html` sets the page title.
  - The history page's revision links use the board's own address (`P.boardHref`) instead
    of `benchmark.html?id=`. The old form still works, because its redirect keeps `revision`.
  - Latest is now always listed first. An earlier revision can therefore arrive with no end
    date, and its label reads "from 9 Oct 2026" instead of a bare day. One new test.
  - The gate card and CI keep main's new `board-url.test.js` alongside the new suite.
- **Prod audit (2026-11-18, read-only, firecall):** both queries ran in a read-only
  transaction inside the prod scoreboard pod. Migration 0024 is not applied on prod yet.
  - Four boards have runs under a past revision: draco-3pass (7 runs), inspect-frontierscience
    (6), inspect-winogrande (2) and musique (7). Each has one submitter, and each was submitted
    before the board's current revision was first used. These are real earlier revisions,
    not stray ids.
  - The largest question count equals the board's Case count on all four, and no group's
    largest count differs from its most common one. The backfilled counts hold.
  - inspect-winogrande has no runs under its current revision, so it will open on an empty
    Latest that points to the 2 earlier results.
  - musique's earlier revision was first seen 28 minutes before its current one, on the same
    day. A same-day range now shows that day once ("about 20 Oct 2026"), with one new test.
- **Independent review loop (2026-11-18, PR #1943):** four rounds by a fresh reviewer that saw
  only the diff, the API and the spec. Fixed after review:
  - Overlapping loads: each load takes a number, and a stale board or frontier answer is
    dropped.
  - Every switch resets the summary, frontier card, two-column strip, score bars, chart and
    comparison notes.
  - An unknown revision is told from an unknown benchmark by the 404's JSON `detail`.
  - History rows link and tag only revisions the board lists, and dim only listed earlier ones.
    The table draws first and gains links when the list arrives.
  - The spec's "Case count inferred from results." line, beside the dropdown.
  - An empty past revision says "No complete runs under this revision."; the status line is
    judged on community runs, so imported reference rows never hide it.
  - Latest loads without waiting for the revision list.
  - The 404 fallback moves the dropdown back to Latest; URL updates keep the `#fragment`;
    focus moves to the dropdown after "Show them".
  - New tests: `revision-selector-review.test.js` (2) and `revision-selector-scope.test.js`
    (2). They are separate files because the append-only gate cannot verify an appended
    `.js` test (OME-1709).
  - Declined: everything that happens only when `/revisions` is unavailable or the board is
    private (the backend ignores `revision` there), the shared-link `og:url` (backend code
    outside this PR), screen-reader timing on the notice (unverified), and the label on the
    single-revision text. Round 4 found nothing else worth fixing.
  - The board page at `/benchmarks/<id>/` is read once at server start, so a portal change
    shows only after a restart. A deploy restarts it anyway.
