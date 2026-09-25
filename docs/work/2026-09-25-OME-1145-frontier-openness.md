---
ticket: OME-1145
stack: scoreboard
status: in_progress
started: 2026-09-25
finished:
---

# OME-1145 — compute the open share over the cost/score Pareto frontier

## Intent

The "N% open" card on `draco-3pass` reads 0% for three reasons, recorded in
`docs/work/2026-09-10-OME-1145-openness-metric-review.md`. Model identities were discarded
(fixed: `OME-1180`/`OME-1181`). The statistic mixes benchmark revisions (live: 10 rows counted, 7
ranked). And it counts all rows rather than the frontier, which the owner decided on 2026-09-10
(D-L, D-N) to change. This unit migrates `GET /v1/leaderboard/{id}/frontier` to the frontier
basis. Spec: `docs/spec/2026-09-25-OME-1145-frontier-openness.md`.

## Planned changes

Pending the spec's decisions. Expected:

- `scores/frontier.py`: replaced by a frontier-basis computation
- `scores/schemas.py`: `FrontierResult` / `FrontierPoint` / `FrontierResponse`
- `scores/store.py`: a bounded `id, models` read for frontier ids
- `routes/leaderboard.py`: `get_frontier` reuses the ranked route's inputs and `pinned` gate
- `portal/benchmark.js`: `renderFrontier`
- tests: new files, plus the approved prior-test changes listed in spec §7

## Test plan

In the spec, §6.

## Acceptance

- the percentage counts only full-board Pareto frontier entries at the registered revision
- an entry is open only when every declared model is open (D1); unknown closes it (D4)
- rows with no `models` are excluded and counted; unrecognised models are counted
- a board with no registered revision reports no share, matching the ranked route's D12 gate
- full scoreboard gates green, including the portal Node suite

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
  - `scores/frontier.py`: rewritten. `compute_frontier_openness`, `frontier_member_ids`, the
    trend replay. Frontier membership comes from `pareto.compute_pareto_frontier_ids`, never
    re-derived.
  - `classification/openness.py`: `classify_entry` (D1, D4, D-Q4)
  - `scores/schemas.py`: `FrontierPoint`, `FrontierResult`, `FrontierResponse` on the new basis
  - `scores/store.py`: `frontier_member_models`, `frontier_history_inputs`, and a shared
    `_chunked_values` that `models_for_score_ids` now uses too
  - `routes/leaderboard.py`: `get_frontier` on the table's reads and D12 gate
  - `portal/leaderboard-logic.js` (`frontierSummary`), `portal/benchmark.js` (`renderFrontier`)
  - new tests: `test_frontier_openness.py` (17), `test_frontier_models_read.py` (5),
    `test_frontier_route.py` (11), 4 appended to `tests/portal/leaderboard-logic.test.js`
  - rewritten under the approved exception: all 9 of `test_frontier.py`; 3 tests and
    `_PUBLIC_FRONTIER_FIELDS` in `test_leaderboard_routes.py`; `test_a_flip_during_the_frontier_
    query_withholds_the_aggregate` retargeted (approved separately, 2026-09-25)
- **Commits:** see the PR.
- **Gates:** `run_gates.py scoreboard --base origin/main --skip-append-only` ALL GREEN: 776 passed,
  3 skipped; portal Node suite 47/47. Without the skip, the append-only check flagged exactly
  `test_frontier.py`, `test_leaderboard_routes.py` (both approved) and
  `tests/portal/leaderboard-logic.test.js`, which was only appended to but which the checker
  cannot parse. `frontier.py` and `openness.py` at 100% coverage.
- **Mutation check:** 7 mutations, each caught: a dominated row counted (5 fail), history ignoring
  the revision (1), history ignoring the case count (3), unknown reading open (2), the override
  ignored (2), the privacy re-check removed (4), an unpinned board claiming a frontier (3).
- **Deviations:**
  1. **One prior test outside the approved list broke.** The flip test hooked
     `list_all_for_benchmark`, which the route no longer calls. Stopped and asked; the owner
     approved retargeting it to `frontier_member_models` on a pinned board, plus a new test that
     flips during each of the three reads.
  2. **`models_for_score_ids` was reused, not duplicated.** OME-1181 already built the bounded
     models read. It lacks the override, and widening its return type would break its pinned
     tests, so its chunk loop moved into `_chunked_values` and a sibling method reads the override.
  3. **An empty `models` list is unidentified,** not open: `all()` over nothing is True.
  4. **`classify_score` has no production caller now.** It and its tests stay; removing it is
     cleanup for a later unit.
  5. `tests/smoke/test_brand_mockup_drift.py` fails against the live brand mockup when run
     directly. Unrelated and not in the gate's test set.

## Review round 1 (2026-09-26, owner's review)

Four findings, all verified against the code before fixing.

1. **High, verified: a quadratic public request.** `_replay` recomputed the whole frontier after
   every submission, kept every historical frontier, ran twice per request, and classified each
   member at every step (logging each unknown route each time). Reproduced: 1,000 rows 1.55 s,
   2,000 rows 6.93 s, before any database work. **Fix (owner: one point per day + memoise):**
   `replay_frontier` recomputes once per UTC day with submissions and is built once per request;
   `_verdicts` classifies each member once. The trend is now daily. Measured: a 2,000-row
   one-day burst 0.01 s; 2,000 rows over 365 days 0.43 s; 5,000 over 365 days 1.29 s. The residual
   cost is days x entries: bounded by calendar time, not by request volume, but not zero. A
   materialised trend is the next step if boards reach that size.
2. **Medium, verified: responses from inconsistent snapshots.** Three independent reads in
   `get_frontier`, and the same split in `get_leaderboard` (page vs frontier marks). **Fix (owner:
   one repeatable-read transaction):** `ScoreStore.read_snapshot()` sets REPEATABLE READ on
   PostgreSQL; both routes read inside it; `turned_private` stays after it, on the default
   connection, so a mid-request flip is still seen. Proven on PostgreSQL by
   `test_read_snapshot_postgres.py` (added to the PostgreSQL CI lane); removing the isolation line
   makes it fail (`[0.99] == [0.5]`). Run locally against a throwaway Docker PostgreSQL 16.
3. **Cross-PR: markers in served files.** The five `OME-`/`INVARIANT` comments this PR added to
   `benchmark.js` and `leaderboard-logic.js` are rewritten as plain comments, so #1049's
   source-hygiene guard will pass after the rebase.
4. The daily trend changed this PR's own trend assertions (hours to days) and, within the
   already-approved rewrite, `test_get_frontier_reflects_real_submissions` (two same-day posts are
   now one point).

New tests: 3 in `test_frontier_openness.py` (one computation per day, day stamps, one
classification per member), 2 in `test_route_read_snapshot.py`, 1 PostgreSQL-only. Gates ALL GREEN
(append-only flags only the approved files).
