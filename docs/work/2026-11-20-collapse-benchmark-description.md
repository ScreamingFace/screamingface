---
ticket: OME-1985
stack: scoreboard
status: done
started: 2026-11-20
finished: 2026-11-20
---

# collapse-benchmark-description — fold the long description on a benchmark page

## Intent

A benchmark page prints its whole description as one plain paragraph at lead size. Across the 103
authored descriptions the median is 723 characters and the longest (EnigmaEval) is 2,515, so the
leaderboard starts a screen or more below a wall of text. Fold the description to three lines
behind a "Show more" button and set it at body size. Rendering only: no description copy changes.

## Planned changes

- `apps/scoreboard/portal/benchmark.html`: wrap the description paragraph, add the hidden button.
- `apps/scoreboard/portal/leaderboard-logic.js`: `descriptionFoldState`, the fold rule.
- `apps/scoreboard/portal/benchmark.js`: `initDescriptionFold`, which measures and applies it.
- `apps/scoreboard/portal/portal.css`: the three-line clamp and body-size type.
- `apps/scoreboard/tests/portal/benchmark-description.test.js` (new) and one static test appended
  to `apps/scoreboard/tests/unit/test_portal_static.py`.

## Test plan

- The rule: short text has no button; long text is folded with "Show more"; an opened text keeps
  "Show less" although it no longer measures as overflowing.
- The wiring, against the real `benchmark.js`: load folded, open, fold again; a window resize
  re-measures; missing markup is a no-op.
- Static: the button ships hidden and the clamp exists only under the script-added class, so a
  page without scripts shows the whole text.

## Acceptance

- A description taller than three lines loads folded with a working "Show more / Show less".
- A description that fits shows no button.
- Server-side description filling (`board_pages.py`) is untouched.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned.
- **Commits:** see the pull request.
- **Gates:** `node --test` on the new file plus the seven portal test files that load
  `benchmark.js` or the logic module: 126 passed. `pytest tests/unit/test_portal_static.py
  tests/unit/test_board_pages.py tests/unit/test_board_pages_review.py`, ruff and pyright on the
  touched test file. Real-browser check: the 2,515-character text measured 77 px folded and
  307 px open at 16 px type; a one-line text showed no button.
- **Deviations:** the four descriptions containing `**` are left as written. They quote replies a
  grader accepts (`'**Yes**' count`), so rendering them bold would misstate the rule.
- **Owner-verify:** the new test file must be named in `scoreboard-tests.yml` and in the
  scoreboard card's gate list to run in CI.
