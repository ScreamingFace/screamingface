# OME-1144 — Plan

Spec: `docs/spec/2026-09-08-OME-1144-remove-submitter-column.md`

## Files

| File | Change |
|---|---|
| `apps/scoreboard/portal/benchmark.js` | remove the `submitted_by` entry from `COLUMNS`; remove the matching `P.formatSubmitter(entry.submitted_by)` cell append |
| `apps/scoreboard/tests/unit/test_multiple_authors.py` | drop the two assertions naming the removed column config and cell render (recorded exception); add `test_portal_leaderboard_table_has_no_submitter_column` |

`apps/scoreboard/portal/main.js` is NOT modified — `formatSubmitter` still serves `spec.js`.

## RED

`test_portal_leaderboard_table_has_no_submitter_column` asserts, against `benchmark.js` source:

- `'label: "Submitter"'` is absent;
- `"P.formatSubmitter(entry.submitted_by)"` is absent;
- `"P.formatAuthors(entry.authors)"` is still present — the removal must not take the sibling
  identity column with it;
- `"P.formatSubmitter(s.submitted_by)"` is still present in `spec.js` — the helper's other caller
  survives, which is what keeps `main.js` untouched.

The last two assertions are the ones that make this a real guard rather than a deletion echo: a
change that removed both identity columns, or that removed the helper, would pass a bare
absence check and fail this one.

Run it first and confirm it fails on the two absence assertions.

## GREEN

Delete the two lines from `benchmark.js`. The column count drops from 9 to 8; no other column
config references an index, so nothing else moves.

## Gates

`uv run .claude/scripts/run_gates.py scoreboard --base origin/main`

The append-only check will flag `test_multiple_authors.py`. That is the exception recorded in the
spec; re-run with `--skip-append-only` and record both results in the ledger.

## Risks

- `COLUMNS` drives both the header row and `renderRows`, and the two are positional. Removing the
  config without the cell append (or the reverse) silently shifts every column right of Backends.
  The existing portal suites plus the new assertions cover the pair.
