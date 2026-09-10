---
ticket: OME-1147
stack: scoreboard
status: in_progress
started: 2026-09-10
finished:
---

# OME-1147 — Unlist private boards from the portal index

## Intent

The public portal index renders a card for `healthbench-worst30`, the Fusion Monsters entry
challenge, and that card is empty for every anonymous visitor because the board is private. The
owner wants the index to show established benchmarks only, while `sf.leaderboards` keeps listing
everything so participants can still submit, and rankings stay private.

Two of those three already hold. This unit closes the third with a client-side filter on a field
the API already returns.

## Planned changes

- `portal/leaderboard-logic.js` — `listedBenchmarks(benchmarks)`, plus a widened header.
- `portal/main.js` — filter in `initIndex()` before the per-board fetches; fix the empty-state copy.
- `src/scoreboard/routes/leaderboard.py` — correct the `list_benchmarks` docstring, which claims
  the endpoint lists public benchmarks while the store returns every board.
- `tests/portal/leaderboard-logic.test.js` and `tests/unit/test_portal_static.py` — see below.

No new test file, so the gate list and `scoreboard-tests.yml` stay untouched.

## Test plan

Two layers, because neither alone is sufficient.

**Node** — the rule: private dropped, public kept, absent/null/unrecognised kept, non-array yields
`[]`, input not mutated.

**Python** — the wiring: `initIndex` calls the helper, the module exports it, and `index.html`
still loads `leaderboard-logic.js` before `main.js`. The node suite cannot see `main.js`, so a
perfect helper that nothing calls would pass every behavioural test.

## Acceptance

- the index drops private boards and keeps everything else;
- `/v1/benchmarks` is unchanged and still returns private boards;
- no change to who can read rankings;
- full Scoreboard gates green, append-only included — every test change is an addition.

## Outcome

- **Actual files:** as planned — `portal/leaderboard-logic.js` (+32/−7, the helper plus a widened
  header), `portal/main.js` (+6/−2), `routes/leaderboard.py` (+12/−1, docstring),
  `tests/portal/leaderboard-logic.test.js` (+44/−0), `tests/unit/test_portal_static.py` (+22/−0).
- **Commits:** see the PR — one commit, `Refs: OME-1147`.
- **Gates:**
  - `run_gates.py scoreboard --base origin/main --skip-append-only` → ALL GATES GREEN: ruff check,
    ruff format, pyright, pytest with `--cov-fail-under=80`, all three portal suites.
    `leaderboard-logic.test.js` alone: 43 passed.
  - `run_gates.py scoreboard --base origin/main` → append-only flags
    `tests/portal/leaderboard-logic.test.js` with *"existing test artifact is unsupported or
    unparseable"*. **This is not a rule-5 violation.** The change is +44/−0 and `git diff | grep
    '^-[^-]'` returns zero removed lines. The checker has no JavaScript parser, so it reports any
    modification to a `.js` test file rather than reading it. No prior assertion was touched and
    no owner decision is required. See Deviations.
- **Mutation check:** four mutations across three files, each reverted in a `finally` and all
  three files confirmed byte-identical to their backups afterwards:

  | Mutation | Layer | Result |
  |---|---|---|
  | filter made fail-closed | node | CAUGHT |
  | predicate inverted | node | CAUGHT |
  | helper defined but never called from `main.js` | python | CAUGHT |
  | `index.html` script order reversed | python | CAUGHT |

  The last two are the reason the Python layer exists: the node suite cannot see `main.js`, so a
  perfect helper that nothing calls, or one whose module loads too late, passes every behavioural
  test.

- **Deviations:**
  1. **The append-only checker cannot parse JS.** Its message is "unsupported or unparseable", not
     a diff of changed lines, and it fires on a purely additive change. Worth a follow-up ticket:
     as it stands, every future portal JS test addition will need `--skip-append-only`, which
     trains the team to skip the check that also guards the Python suites.
  2. **The first mutation harness aborted mid-run and left `main.js` mutated**, because its
     "did the runner execute?" marker looked for `"passed"` — absent from a failing pytest run,
     which is exactly what a caught mutation produces. Rewritten with the restore in a `finally`
     and a marker that matches either outcome. The mutated line was restored by hand and the
     final state verified byte-identical.
