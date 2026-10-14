---
ticket: OME-1609
stack: screamingface
status: done
started: 2026-10-15
finished: 2026-10-15
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
