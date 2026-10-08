---
ticket: OME-1512
stack: scoreboard
status: done
started: 2026-10-07
finished: 2026-10-07
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

Scope grew in a live-iteration session from the featured shortlist into a full leaderboard-portal
visual refresh (featured tabs + searchable overflow, card-led landing with a research-register
hero, Pareto axes at 0, the "about" note moved to the per-board page, gold+blue accents).

- **Actual files:** `portal/leaderboard-logic.js` (`FEATURED_BENCHMARK_IDS`, `partitionFeatured`,
  `truncate`, `filterBenchmarks`), `portal/main.js` (tab strip overflow menu, card rendering +
  batch reveal), `portal/index.html` (hero + card grid), `portal/benchmark.html` (drop note/caption;
  add "about" note under description), `portal/pareto-chart.js` (axis origin at 0),
  `portal/portal.css` (hero, cards, dropdown, accents, spacing), `portal/spec.html` (url4 casing);
  tests `tests/portal/featured-benchmarks.test.js`, `pareto-origin.test.js`, `index-cards.test.js`
  (new), `tests/unit/test_portal_static.py` (updated); `.claude/sdlc.local.md` +
  `.github/workflows/scoreboard-tests.yml` (register new portal test files);
  `.claude/test-change-approvals/OME-1512.json` (append-only approval).
- **Commits:** 11 conventional commits `d80f3cb09 … 685d37b76` on `OME-1512-leaderboard-visual-refresh`.
- **Gates:** `run_gates.py scoreboard` green — ruff · ruff format · pyright · pytest (929 passed,
  90% cov, ≥80 floor) · node portal tests (6 files). Append-only `--base origin/main` passes via
  the OME-1512 approval manifest.
- **Deviations:** (1) new portal pure-logic tests live in NEW files (`featured-benchmarks`,
  `pareto-origin`, `index-cards`) registered by name in the gate + CI — the append-only gate cannot
  parse a `.js` edit to prove additivity, so a new file is the sanctioned additive path. (2) The
  Pareto cost axis only anchors at 0 on the linear scale; wide-cost boards keep a log axis (0 has no
  logarithm) — the existing log-scale contract/test is preserved. (3) `test_portal_static.py` guard
  assertions were updated to the new structure/copy (owner-directed), pinned by the approval
  manifest. (4) The opt-in brand-mockup drift smoke test now diverges from the external mockup at
  `brand.screamingface.ai` (copy/structure changed); excluded from the default gate — the mockup
  update is a separate owner action.
