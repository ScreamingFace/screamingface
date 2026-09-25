---
ticket: OME-1386
stack: scoreboard
status: in_progress
started: 2026-09-26
finished:
---

# open-entry-badge — mark each leaderboard entry open or closed

## Intent

The Urgent epic `OME-1282` requires the board to show which entries win the open frontier. After
`OME-1145` the card gives a percentage, but no row says which entries are open. Spec:
`docs/spec/2026-09-26-open-entry-badge.md`. Stacked on PR #1080.

## Planned changes

- `routes/leaderboard.py`: `openness` on `RankedLeaderboardEntry`, a page-bounded models read
- `portal/leaderboard-logic.js`: `opennessLabel`; `portal/benchmark.js`: the verdict line;
  `portal/portal.css`: `.weights-line`, `.status--open`
- tests: route tests (new file), portal tests (appended), `_PUBLIC_BOARD_ENTRY_FIELDS` (+1, approved)

## Test plan

Spec §4.

## Acceptance

- every ranked row carries the verdict the card would give it
- the portal shows it without green and without a verification claim
- full scoreboard gates green, including the portal Node suite

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** `routes/leaderboard.py` (`openness` on `RankedLeaderboardEntry`, the
  page-bounded read in `get_leaderboard`, `_ranked_entry`), `portal/leaderboard-logic.js`
  (`opennessLabel`), `portal/benchmark.js` (`renderOpenness`), `portal/portal.css`; new
  `tests/unit/test_entry_openness_route.py` (6); 4 tests appended to
  `tests/portal/leaderboard-logic.test.js`; `_PUBLIC_BOARD_ENTRY_FIELDS` +`"openness"` (approved).
- **Commits:** see the PR.
- **Gates:** `run_gates.py scoreboard --base OME-1145-frontier-openness --skip-append-only` ALL
  GREEN, 782 passed, 3 skipped; portal 51/51. Without the skip the append-only check flagged only
  `test_leaderboard_routes.py` (the approved addition) and the appended-to portal test file,
  which it cannot parse.
- **Mutation check:** reading models for the whole board (1 fail), reading them after the
  privacy re-check (1), no read at all (6), showing unidentified as closed in the portal (2).
- **Visual check:** a local SQLite board seeded with four sample rows (throwaway, never a shared
  board), viewed in light and dark: no green, table 958px in its 958px container, rows 71px.
- **Deviations:**
  1. **Backends cell instead of a column** (owner decision mid-build): the column overflowed
     the table by 20px. Spec §3 revised.
  2. **`nowrap` on the line:** "Closed weights" wrapped to two lines and grew every row; nowrap
     still fits at 958px.
  3. **Private `my_submissions` carry no verdict:** they are not ranked. Out of scope, as the
     spec says.
