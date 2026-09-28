---
ticket: OME-1146
stack: scoreboard
status: in_progress
started: 2026-09-10
finished:
---

# OME-1146 (part 1) — Rename the Pareto chart

## Intent

The benchmark page heads its Pareto chart "Score for cost" while the legend, the row marks and
every other surface call the same thing the Pareto frontier. Rename the heading and its accessible
label to "Pareto Frontier (cost/score)".

This is **half** of OME-1146. The ticket also asks to delete the self-reported-costs disclaimer;
that half reverses OME-770 D11 and contradicts two recorded invariants, so it stays open pending
the owner's answer on the ticket. Spec D2 records why.

## Planned changes

- `apps/scoreboard/portal/benchmark.html` — the `h2` at :67 and the `aria-label` at :75.
- `apps/scoreboard/tests/unit/test_portal_static.py` — retarget the aria-label assertion at :189;
  add `test_pareto_chart_heading_and_label_name_the_pareto_frontier`.

No JS. `grep -rn "Score for cost" apps/scoreboard/` returns three hits and none is in
`pareto-chart.js` or under `tests/portal/`.

## Test plan

RED first, four assertions:

- the new `<h2>` is present — the heading was asserted nowhere before, so the rename would
  otherwise ship unguarded;
- the new `aria-label` is present;
- `"Score for cost"` is absent from the file — catches a half-done rename;
- the disclaimer is still present — pins the deliberate scope boundary of this unit.

## Acceptance

- no "Score for cost" anywhere in the portal;
- heading and `aria-label` agree;
- disclaimer, provenance comment and every other caption line untouched;
- full Scoreboard gates green with the append-only exception recorded.

## Outcome

- **Actual files:** as planned. Two string edits in `portal/benchmark.html`; one retargeted
  assertion plus one new test in `tests/unit/test_portal_static.py`. No JS touched.
- **Commits:** see the PR — one commit, `Refs: OME-1146`.
- **Gates:**
  - `run_gates.py scoreboard --base origin/main` → append-only FAILS on
    `tests/unit/test_portal_static.py` (old line 189) and nothing else. That is the recorded
    Confidence-Gate exception in the spec.
  - `run_gates.py scoreboard --base origin/main --skip-append-only` → ALL GATES GREEN: ruff check,
    ruff format, pyright, pytest with `--cov-fail-under=80`, and all three portal suites.
    `test_portal_static.py` alone: 16 passed.
- **Mutation check:** three mutations of `benchmark.html`, each reverted and the file confirmed
  byte-identical to its backup afterwards:

  | Mutation | Result |
  |---|---|
  | heading renamed, `aria-label` left behind | CAUGHT |
  | `aria-label` renamed, heading left behind | CAUGHT |
  | disclaimer deleted as well (the out-of-scope half) | CAUGHT |

  The third is the one that matters. It is the only thing in the suite that pins this unit's
  actual scope: renamed, and still disclaimed.
- **Deviations:** none. The ticket's step 6 asked for a stray grep before starting;
  `grep -rn "Score for cost" apps/scoreboard/` returned exactly the three known hits, so steps 3,
  4 (second assertion) and 5 of the ticket are untouched by design — they belong to the disclaimer
  half, which stays open.
