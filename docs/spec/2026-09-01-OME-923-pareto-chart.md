# OME-923 Part C — Score against run cost

Status: approved for implementation (owner, 2026-09-01) · Stack: scoreboard

## Problem

Parts A and B compute score/cost Pareto membership and mark qualifying leaderboard rows. The
board still makes readers compare the Score and Cost columns mentally. Part C adds the promised
two-dimensional view without expanding into OME-324's speed axis or OME-325's contributor
recognition.

## Scope boundary

- This part owns one 2D chart: benchmark-native score against whole-run USD cost, with the
  score/cost Pareto frontier drawn.
- OME-324 retains speed-related 2D views, the 3D speed/score/cost view, and efficiency sliders.
- OME-325 remains independent contributor-ranking and achievement-badge work. Pareto membership
  does not become a contributor badge without a separate product decision.
- The existing table remains the accessible data source and the Cost column remains sortable.
- The cheapest-run summary from OME-770 is not part of OME-923 Part C.

## Data and authority

The chart consumes the same bounded `entries` array already returned to the page. It never fetches
or returns an unbounded second public projection. The chart therefore shows the top submissions
currently shown by the board, while each entry's `on_pareto_frontier` flag remains a server-side
whole-board decision. The caption states this distinction.

The browser must not recompute frontier membership. Table marks, plotted frontier markers, and the
frontier line all consume the same strict `on_pareto_frontier === true` field.

Rows with `run_cost_usd = null` are not coerced to zero. When at least one priced row exists, they
appear in a separate `Cost n/a` gutter at their real score. When no priced row exists, the chart is
hidden rather than showing an empty cost claim.

## Scales

- Higher score is always higher on the y-axis; scores are benchmark-native and may be negative.
- Cost increases left to right.
- Use a logarithmic cost scale only when every priced cost is positive and the maximum/minimum
  spread is strictly greater than 8x. A genuine zero-cost run forces a linear scale because zero
  has no logarithm.
- Degenerate single-value score/cost domains render at a stable midpoint or origin and never emit
  `NaN` SVG coordinates.

## Visual semantics

The chart follows SFDS v2's marketing register and semantic tokens:

- neutral circles: dominated priced rows;
- blue diamonds: score/cost Pareto rows, matching Part B's mark;
- a gold ring: highest score, orthogonal to frontier membership so a row may carry both;
- open neutral circles in the `Cost n/a` gutter: unpriced rows;
- a blue line connects visible frontier points in ascending cost order.

Colour is never the only carrier: categories also differ by shape and are named in the caption.
Every point carries a native SVG tooltip with spec, exact displayed score, cost state, frontier
state, and highest-score state. The SVG is a visual summary; the adjacent table remains the
keyboard and screen-reader representation.

## Trust and copy

The caption says costs are self-reported and not verified by re-running. It also says frontier
membership considers the full board while the chart plots only the submissions shown on this
page. Null cost reads as `n/a`, never free.

## Acceptance

- A board with priced rows renders score against cost and connects its visible Pareto points.
- Frontier styling comes only from the server field and agrees with the row marks.
- Dominated, frontier, highest-score, and unpriced states remain distinguishable without colour.
- More than 8x positive cost spread selects a log scale; exactly 8x, any zero, and smaller spreads
  use linear.
- Negative, tied, zero-cost, null-cost, malformed, and empty inputs produce finite, truthful
  output or hide the chart cleanly.
- The chart is responsive and verified in light, dark, desktop, and narrow layouts.
- Part C remains subject to OME-923's merge gate: real non-null cost must be flowing before merge.
