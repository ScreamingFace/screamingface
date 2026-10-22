---
ticket: OME-1609
stack: screamingface
status: done
started: 2026-10-15
finished: 2026-10-20
---

# fix-leaderboard-list-filter — the `sf.leaderboards.list()` filter box hides nothing

## Intent

Typing into the filter box above `sf.leaderboards.list()` leaves every row on screen. The
input's handler does run and sets `row.hidden` on each non-matching row, but the row rule
`.sf-lb-list__row{display:grid;…}` in `LEADERBOARD_STYLE` outranks the browser's own
`[hidden]{display:none}`, so a hidden row still renders. The fix is one rule that lets a
hidden row drop out of the layout.

## Planned changes

- `packages/screamingface/src/screamingface/_ui/leaderboard_style.py` — add
  `.sf-lb-list__row[hidden]{display:none}` after the row rule.
- `packages/screamingface/tests/test_leaderboard_filter.py` (new) — pin the rule in the
  rendered catalogue HTML.

## Test plan

- New contract test: the catalogue HTML carries `.sf-lb-list__row[hidden]{display:none}`.
  Fails before the fix.
- Owner visual check: in JupyterLab against the local stack (`screamingface up`), run
  `sf.leaderboards.list()` and type `health`; only the two healthbench rows remain.

## Acceptance

- Typing in the filter hides the rows that do not match and shows them again when cleared.
- `run_gates.py screamingface` is green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned (`leaderboard_style.py`, `tests/test_leaderboard_filter.py`) plus this ledger.
- **Commits:** see the PR (squash-merged as one commit).
- **Gates:** RED first: the new test failed on the missing rule. After: `run_gates.py screamingface` ALL GATES GREEN (append-only, ruff check, ruff format, pyright, pytest with the 95% coverage floor, check_notebooks, build, check_distribution).
- **Deviations:** no semantic-anchor comments in the rule or the test, at the owner's request. No spec or plan, following the OME-1603 precedent for a one-rule CSS fix. Owner verify: typed into the filter in JupyterLab against the local stack.

## Takeover after review (2026-10-20)

Owner asked to review PR #1421 (from the `dbckz` fork) and take over the fixes. The work moves
to the in-repo branch `OME-1609-fix-leaderboard-list-filter`, with Dave Buckley's two commits
cherry-picked onto `origin/main`. A branch in this repo also clears the red `test (3.12)` check,
which failed only because a fork token cannot post the coverage comment.

### Planned changes

- `tests/test_leaderboard_filter.py`: replace the two substring checks with structured ones
  (owner review comment on #1421; no text matching over generated output):
  - parse `LEADERBOARD_STYLE` into selector → declaration blocks and assert
    `.sf-lb-list__row[hidden]` is exactly `display:none`;
  - parse the catalogue HTML with `html.parser` and assert every row carries a
    `data-sf-search` key built the way the filter reads it.
- `_ui/leaderboard_view.py`: build the search key with `str.lower()` instead of
  `str.casefold()`. The handler lowers the typed query with JS `toLowerCase()`, which is the
  Unicode default lowercase mapping, the same as Python's `lower()`. `casefold()` differs on
  some letters (`ß` → `ss`), so a typed `ß` matched nothing.
- This ledger renamed to carry the ticket id (D8).

### Test plan

- RED: a row named `Straße` must have the search key `straße …`; fails on `casefold()`.
- The parsed-CSS and parsed-HTML checks pass on the fix and fail if the rule is removed.
- `run_gates.py screamingface` green.

### Outcome (takeover)

- **Actual files:** as planned: `_ui/leaderboard_view.py` (`lower()` plus one `# WHY:` line, so
  a later edit does not restore `casefold()`), `tests/test_leaderboard_filter.py` (three
  structured tests replace the substring test), this ledger renamed.
- **Gates:** RED: the `Straße` test failed on `casefold()` (`strasse strasse grösse`), and the
  parsed-CSS test failed with the rule removed. After: `run_gates.py screamingface --base
  origin/main` and `run_gates.py repo --base origin/main` ALL GATES GREEN; pytest 4,199 passed,
  33 skipped, 97% coverage. `--base origin/main` because the test file is new to `main`; vs
  `HEAD` the append-only check sees the cherry-picked first version of the same new test.
- **Deviations:** the local venv needed `uv sync --extra notebook` (as CI runs) before pyright
  resolved `ipywidgets`. Out of scope, not changed: the "N benchmarks" count does not follow
  the filter, and no message shows when no row matches.
