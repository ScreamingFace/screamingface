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

## Rebase onto main after #1080 merged (2026-09-29)

#1080 was squash-merged (`5fd16fb4`), so this branch's three commits moved onto `origin/main`.
Two conflicts, both additive: `portal.css` (the weights-line block beside the mark-column header,
which #1049 had stripped of its ticket marker) and `routes/leaderboard.py` (the page's verdict read
and #1080's in-snapshot `benchmark_scope` both kept, verdicts inside the snapshot).

**Logging follow-up from #1080 review round 3.** `classify_entry` became silent there, so the
table's per-row verdict would have logged nothing. `frontier._verdicts` is now the public
`classify_members` and the table uses it: one aggregated warning per page, the same classifier as
the card. `_ranked_entry` takes the verdict rather than classifying. **Test:**
`test_a_page_logs_its_unrecognised_models_once_in_aggregate` (5 rows x 4 unknown routes gives one
line naming 20). RED before (`0 == 1`), GREEN after.

Gates ALL GREEN with the approved append-only skip; without it the check flags only the approved
`_PUBLIC_BOARD_ENTRY_FIELDS` change and the portal JS file it cannot parse.
