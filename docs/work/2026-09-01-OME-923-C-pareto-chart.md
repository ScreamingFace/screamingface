---
ticket: OME-923
stack: scoreboard
status: complete
started: 2026-09-01
finished: 2026-09-01
---

# OME-923 — Draw the score/cost Pareto chart (part C)

## Intent

Turn the table's separate score, cost, and Pareto-mark fields into one bounded 2D view so a reader
can see the score-for-cost trade-off directly. Keep the server authoritative for frontier
membership, exclude unknown cost from the numeric axis, and preserve OME-324/325's separate scopes.

## Planned changes

- Add a pure, Node-testable chart model and a responsive SVG renderer under the Scoreboard portal.
- Add the chart shell and lifecycle wiring to the benchmark page.
- Add SFDS-compliant marker, axis, gutter, caption, light/dark, and responsive styles.
- Append pure model and static integration tests without changing prior tests.
- Update the OME-923 task mirror with the Part B/C status and clarified ticket relationships.

## Test plan

- Server-marked frontier points alone form the visible frontier line; no browser recomputation.
- Null costs enter the n/a gutter and never the cost axis; genuine zero stays numeric and linear.
- Positive spread greater than 8x uses log; exactly 8x and smaller use linear.
- Negative/tied scores, one priced row, malformed rows, and empty inputs keep every coordinate
  finite or hide the chart.
- Highest-score state stays orthogonal to frontier state and ties all qualify for the ring.
- Input order and objects are not mutated.
- Static page contract loads the module in order and carries provenance/display-bound copy.
- Browser smoke covers light/dark and desktop/narrow layouts on a mixed priced/unpriced board;
  pure model coverage pins the all-null hidden state.

## Acceptance

- The benchmark page plots score against whole-run cost for its bounded visible entries.
- Visible Pareto points are blue diamonds joined in increasing cost order; dominated points,
  highest-score rings, and unpriced gutter points are distinct by shape as well as colour.
- The caption makes self-reported provenance, n/a semantics, and whole-board-vs-visible scope clear.
- Existing table behavior and all Scoreboard gates remain green.
- The implementation remains unmerged until real non-null cost data is flowing.

## Outcome

- **Actual files:** added the pure model/SVG renderer and its dedicated Node suite; wired and styled
  the chart in the benchmark portal; appended the static shell contract; explicitly added the new
  Node file to local gates, CI, the Scoreboard README, and stack guidance; updated the OME-923 task,
  spec, plan, and this ledger.
- **Commits:** Part C implementation commit (this change), stacked on Part B commit `772a57e9`.
- **Gates:** `uv run .claude/scripts/run_gates.py scoreboard --base 772a57e9` — all green:
  append-only check, Ruff check/format, Pyright, pytest with ≥80% coverage, and both explicit Node
  suites (48 portal tests total). Targeted portal-static suite: 14 passed.
- **Browser QA:** Playwright against a local mixed fixture at 1440px light/dark and 390px dark;
  zero console errors, correct log scale/frontier/gutter/leader rendering, and keyboard ArrowRight
  moved the focus-visible chart viewport from `scrollLeft=0` to `40`.
- **Deviations:** the chart additionally fails closed when priced rows have no authoritative server
  frontier mark, covering revision-unpinned/older-response states without inventing membership in
  the browser. The all-null state was kept in the pure suite instead of a duplicate visual smoke,
  because its specified result is the absence of the chart.

## 2026-09-02 — Restacked after Part B merge

- Part B PR #786 was squash-merged to `main` as `d0e1d7dd` after the owner explicitly waived the
  live non-null-cost rollout gate.
- Merged `origin/main` into this branch without rewriting history. Inherited Part B conflicts were
  resolved to the exact `main` versions; the chart HTML/CSS additions were retained.
- Verified the resulting comparison is exactly `main` plus the original 14 Part C files: 796
  insertions and 6 deletions, with no Part B files leaking back into the PR diff.
- `uv run python .claude/scripts/run_gates.py scoreboard` — all gates green, including both portal
  Node suites.

## Review pass (2026-09-03)

Reviewed before requesting a human read. The chart holds up: it reuses `L.costNumber` and
`L.isParetoMarked` rather than reparsing costs or recomputing the frontier, `logarithmic` is
guarded by `costMin > 0` so a genuinely free run never reaches `Math.log(0)`, unpriced rows are
plotted by score with no cost position instead of being dropped or placed at zero, the SVG is
deliberately `aria-hidden` with the table as the accessible source, and both the card and the CI
workflow name `pareto-chart.test.js` explicitly — the `OME-798` glob trap was handled.

Checked empirically across five cost shapes (zero present, wide range, narrow range, all
identical, sub-cent against hundreds): every coordinate finite, log chosen only where safe.

Two things fixed:

- **The key's swatches were missing from the `forced-colors` block.** The block rescued the
  chart's own SVG marks (`.pareto-chart__*`) but not the legend that explains them
  (`.pareto-chart-key__*`), which are spans coloured by `background` — stripped in Windows High
  Contrast, leaving four labels with nothing to map them to while the chart still drew shapes.
  The same omission the table's `.pareto-mark` had. Hollow swatches (leader, unpriced) keep a
  `Canvas` fill so they stay distinguishable from the solid ones.
- **A dead property:** `[data-theme="dark"] .pareto-chart-key__frontier` set both `fill` and
  `background`. The element is a `<span>`; `fill` is an SVG property and does nothing there.

Gates green, append-only check included with no skip.
