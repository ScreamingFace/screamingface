---
ticket: OME-1144
stack: scoreboard
status: in_progress
started: 2026-09-08
finished:
---

# OME-1144 — Remove the Submitter column from the leaderboard table

## Intent

The benchmark leaderboard table shows `Submitter` and `Authors` next to each other, and
`_resolved_authors` falls back to `[submitted_by]`, so for any submission without an explicit
author list the two cells are byte-identical. Reported by the owner from the populated dev board.
This unit removes the `Submitter` column from that one table and changes nothing behind the
portal.

## Planned changes

- `apps/scoreboard/portal/benchmark.js` — drop the `submitted_by` `COLUMNS` entry and its cell
  append.
- `apps/scoreboard/tests/unit/test_multiple_authors.py` — remove the two assertions that name the
  deleted column config and cell render; add `test_portal_leaderboard_table_has_no_submitter_column`.

`apps/scoreboard/portal/main.js` is deliberately untouched: `formatSubmitter` still serves
`portal/spec.js:17`, so the ticket's "drop it if no other caller" branch does not apply.

## Test plan

RED first, `test_portal_leaderboard_table_has_no_submitter_column`:

- `'label: "Submitter"'` absent from `benchmark.js` (the header);
- `"P.formatSubmitter(entry.submitted_by)"` absent from `benchmark.js` (the cell);
- `"P.formatAuthors(entry.authors)"` still present — removing both identity columns must fail;
- `"P.formatSubmitter(s.submitted_by)"` still present in `spec.js` — deleting the shared helper
  must fail.

The last two are the reason this is a guard and not a restatement of the diff.

## Acceptance

- the leaderboard table renders eight columns, none of them Submitter;
- Authors still renders, em dash included;
- the spec page and `main.js` are unchanged;
- full Scoreboard gates green, with the append-only exception recorded.

## Outcome

- **Actual files:** as planned. `portal/benchmark.js` lost two lines (the `COLUMNS` entry and the
  cell append); `tests/unit/test_multiple_authors.py` lost the two stale assertions and gained
  `test_portal_leaderboard_table_has_no_submitter_column`. `portal/main.js`, `portal/spec.js` and
  `portal/spec.html` untouched, as D3 and D4 require.
- **Commits:** see the PR — one commit, `Refs: OME-1144`.
- **Gates:**
  - `run_gates.py scoreboard --base origin/main` → append-only check FAILS on
    `tests/unit/test_multiple_authors.py` (removed old lines 197, 198). That is exactly the
    recorded Confidence-Gate exception in the spec and nothing else was flagged.
  - `run_gates.py scoreboard --base origin/main --skip-append-only` → ALL GATES GREEN: ruff check,
    ruff format, pyright, pytest with `--cov-fail-under=80`, and all three portal suites.
- **Mutation check:** the new guard was verified against three mutations of `benchmark.js`, each
  restored afterwards and the file confirmed byte-identical to its backup:

  | Mutation | Result |
  |---|---|
  | restore the header without its cell | CAUGHT |
  | restore the cell without its header | CAUGHT |
  | delete the Authors cell too (both identity columns gone) | CAUGHT |

  The third is the one that matters: a bare "Submitter is absent" assertion would pass while the
  board lost every identity column.
- **Deviations:** two, both against the ticket text rather than the plan.
  1. The ticket says `formatSubmitter` "becomes unused; drop it if no other caller". There is
     another caller — `portal/spec.js:17` — so `portal/main.js` was left alone (spec D3).
  2. The ticket says "update any portal tests asserting the Submitter header/column". No test
     under `tests/portal/` asserts it; the assertions live in the Python suite at
     `tests/unit/test_multiple_authors.py`, which is where the edit landed.
