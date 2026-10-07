---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: scoreboard
status: in_progress
started: 2026-10-07
finished:
---

# leaderboard-visual-refresh — tighter, card-led leaderboard portal

## Intent

A set of visual changes to the scoreboard portal, driven in one live-iteration session, to make
the public leaderboard read cleaner and more hierarchy-first. Four slices:

1. **Featured benchmark shortlist.** The benchmark tab strip (and the index catalogue) led with a
   flat wall of ~65 equal-weight benchmarks. Surface a curated five first (DRACO 3-Pass,
   ContractEval, FrontierScience, HealthBench Professional, IFEval); fold the long tail into a
   "More benchmarks" control. **[done]**
2. **Drop "Read this first".** The per-benchmark leaderboard page carries a `.note` callout; remove
   it so the board view is cleaner.
3. **Index catalogue → cards.** Replace the long catalogue table on `index.html` with clickable
   cards (title + focus + ≤100-char description + best reproducible), showing ~10 at first with a
   "more" control to reveal the rest (featured-first order from slice 1 preserved).
4. **Pareto chart origin at 0.** On the per-benchmark page, the cost/score Pareto chart starts its
   axes at the data's lowest value; anchor both axes at 0 instead (never cropping data).

## Planned changes

- `apps/scoreboard/portal/leaderboard-logic.js` — `FEATURED_BENCHMARK_IDS` + `partitionFeatured`
  (slice 1); any pure helper the cards/chart need (slices 3–4).
- `apps/scoreboard/portal/main.js` — `renderTabStrip` + `initIndex` (slice 1); card rendering +
  "more" toggle (slice 3).
- `apps/scoreboard/portal/benchmark.html` — remove the `.note` block (slice 2).
- `apps/scoreboard/portal/index.html` — card container markup replacing the table (slice 3).
- `apps/scoreboard/portal/pareto-chart.js` — axis-domain origin at 0 (slice 4).
- `apps/scoreboard/portal/portal.css` — `.tabstrip-more` (slice 1), card styles (slice 3).
- `apps/scoreboard/tests/portal/featured-benchmarks.test.js` — `partitionFeatured` (slice 1).
- New portal test file(s) for any new pure logic (slices 3–4), named in the gate + CI lists.
- `.claude/sdlc.local.md` + `.github/workflows/scoreboard-tests.yml` — register new portal test
  files by name (OME-798 convention).
- `apps/scoreboard/tests/unit/test_portal_static.py` — update served-asset structural assertions
  the slices change (note removal, table→cards), if the AST append-only check permits.

## Test plan

- slice 1: `partitionFeatured` — featured order, missing-id skip, rest order/disjoint, non-array,
  no in-place mutation; `FEATURED_BENCHMARK_IDS` pins the agreed ids.
- slice 3: pure description-truncation (≤100 chars + ellipsis) and the featured-first + first-N
  slicing, unit-tested; card DOM covered manually.
- slice 4: pure axis-domain helper returns a 0 origin (score min = min(0, dataMin) so a
  negative-score board is never cropped; cost min = 0), unit-tested.

## Acceptance

- `run_gates.py scoreboard` green (append-only, ruff, pyright, pytest ≥80%, node portal tests).
- Manual: tab strip shows 5 featured + "More" dropdown; `index.html` shows ~10 clickable cards
  with title/focus/≤100-char desc/best + a working "more"; benchmark page has no "Read this first"
  note; the Pareto chart's axes meet at 0.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** <vs planned>
- **Commits:** <sha — message>
- **Gates:** <run_gates.py result line / counts>
- **Deviations:** slice 1 note — the `partitionFeatured` tests live in a NEW file
  (`featured-benchmarks.test.js`) rather than appended to `leaderboard-logic.test.js`: the
  append-only gate cannot parse a `.js` edit to prove additivity and fails closed on any
  modification, so a new file (registered by name in the gate + CI) is the sanctioned additive
  path. <plus any further deviations>
