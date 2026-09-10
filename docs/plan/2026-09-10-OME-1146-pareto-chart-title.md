# OME-1146 (part 1) — Plan

Spec: `docs/spec/2026-09-10-OME-1146-pareto-chart-title.md`

## Discovery

`grep -rn "Score for cost" apps/scoreboard/` returns exactly three hits:

| File | Line | What |
|---|---|---|
| `portal/benchmark.html` | 67 | `<h2>Score for cost</h2>` |
| `portal/benchmark.html` | 75 | `aria-label="Score for cost chart, horizontally scrollable"` |
| `tests/unit/test_portal_static.py` | 189 | asserts the aria-label |

No hits in `pareto-chart.js` or under `tests/portal/`, so the ticket's "check for strays" step is
satisfied and no JS changes.

## Files

| File | Change |
|---|---|
| `portal/benchmark.html` | rename the `h2` and the `aria-label` |
| `tests/unit/test_portal_static.py` | retarget the line-189 assertion (recorded exception); add `test_pareto_chart_heading_and_label_name_the_pareto_frontier` |

## RED

The new test asserts four things:

- `<h2>Pareto Frontier (cost/score)</h2>` is present — the heading is currently asserted **nowhere**,
  so without this the rename would ship unguarded;
- the new `aria-label` is present;
- `"Score for cost"` appears nowhere in the file — catches a partial rename;
- the disclaimer `"Costs are self-reported, not verified by re-running."` is still present.

The last assertion is the one that makes this a guard rather than an echo of the diff. This unit's
whole point is that the rename ships and the disclaimer does not, and nothing else in the suite
pins that pairing.

Run it first and confirm it fails on the heading and label assertions.

## GREEN

Two string edits in `benchmark.html`.

## Gates

`uv run .claude/scripts/run_gates.py scoreboard --base origin/main`

Append-only will flag the one retargeted assertion in `test_portal_static.py`. That is the
exception recorded in the spec; re-run with `--skip-append-only` and record both results.

## Risks

- The heading and the `aria-label` can drift apart, since only the label was previously asserted.
  The new test pins both, which is why it asserts them separately rather than grepping once.
