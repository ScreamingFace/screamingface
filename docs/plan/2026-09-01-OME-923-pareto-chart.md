# OME-923 Part C — implementation plan

## Frame

Add a bounded, responsive score-versus-cost chart to the benchmark page. Reuse the server's
whole-board Pareto membership instead of creating a second frontier implementation or public data
read. Preserve the existing table as the accessible source of record.

## Design

1. Add a small UMD module, `portal/pareto-chart.js`, so the pure chart model is importable by the
   existing Node test runner while DOM/SVG rendering stays out of the already-near-limit
   `benchmark.js`.
2. Build a pure model that validates scores, parses fixed-scale cost strings through the existing
   cost helper, chooses linear/log scale, assigns normalized finite coordinates, separates the
   null-cost gutter, identifies visible leaders, and sorts only server-marked frontier points for
   the line.
3. Render one responsive SVG from that model with semantic-token CSS, native point tooltips, axis
   labels, a separate n/a gutter, and a caption that explains shape, provenance, and display scope.
4. Wire the module into `benchmark.html` and call it from both populated and empty render paths.
5. Add a dedicated Node chart-model suite and append the portal-static contract without altering
   prior assertions. Name the new Node file explicitly in both local gates and CI.

## Test order

1. RED: add pure model tests for server-authoritative membership, null gutter, the strict 8x
   threshold, zero-cost behavior, negative/equal score domains, malformed rows, ties, input
   immutability, and visible frontier ordering.
2. RED: append a structural portal test requiring the chart shell, module ordering, provenance,
   bounded-scope copy, and a hidden empty default.
3. GREEN: add the chart module, markup, wiring, and styles.
4. Run the existing Node file, targeted portal-static tests, then the full Scoreboard gate.
5. Use the Playwright CLI against a locally seeded board to verify light/dark and desktop/narrow
   layouts, point tooltips, log/linear labeling, and a no-cost board.

## Files

- `apps/scoreboard/portal/pareto-chart.js` — pure model plus SVG renderer.
- `apps/scoreboard/portal/benchmark.html` — chart shell and script ordering.
- `apps/scoreboard/portal/benchmark.js` — lifecycle wiring only.
- `apps/scoreboard/portal/portal.css` — chart-specific SFDS styling.
- `apps/scoreboard/tests/portal/pareto-chart.test.js` — pure chart-model coverage.
- `apps/scoreboard/tests/unit/test_portal_static.py` — static integration/accessibility contract.
- `docs/tasks/2026-08-20-OME-923-pareto-frontier.md` — part status and scope record.
- `docs/work/2026-09-01-OME-923-C-pareto-chart.md` — implementation ledger.

## Risks and controls

- **Duplicate or divergent frontier math:** no client-side membership computation; consume the
  server flag strictly.
- **Unbounded attacker-controlled response:** chart only the already bounded page entries.
- **Null interpreted as free:** route null to a separate gutter through the shared cost parser.
- **Logarithm of zero:** log only when all priced costs are positive.
- **Misleading incomplete frontier line:** caption explicitly distinguishes full-board membership
  from visible-page plotting.
- **XSS from community fields:** use `textContent`, `createTextNode`, and attribute setters only.
- **Chart-only accessibility:** retain the table as the named accessible representation and make
  the SVG a visual duplicate.
