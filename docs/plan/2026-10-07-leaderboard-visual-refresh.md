# portal-featured-benchmarks — plan

Spec: `docs/spec/2026-10-07-portal-featured-benchmarks.md`. Branch
`portal-featured-benchmarks` from `origin/main`.

1. **RED.** Add `partitionFeatured` cases to `tests/portal/leaderboard-logic.test.js` (order,
   missing-id skip, rest-excludes-featured + order, non-array, no in-place mutation, the
   `FEATURED_BENCHMARK_IDS` id guards). Run `node --test tests/portal/leaderboard-logic.test.js`;
   confirm they fail (function undefined).
2. **GREEN.** Add `FEATURED_BENCHMARK_IDS` + `partitionFeatured` to `portal/leaderboard-logic.js`
   beside `listedBenchmarks`; export both. Re-run — new + all prior green.
3. **Tab strip.** `portal/main.js` `renderTabStrip`: partition, render featured `<a>` tabs
   (active keeps `aria-current="page"`), append a `<select class="tabstrip-more">`
   (`aria-label="More benchmarks"`, disabled placeholder, one option per rest board, navigate on
   `change`, select the active board when it is non-featured). Update the function comment.
4. **Catalogue.** `portal/main.js` `initIndex`: after `listedBenchmarks`, reorder with
   `partitionFeatured(...).featured.concat(.rest)`; drive the board fan-out + rendering off it.
5. **Styling.** `portal/portal.css` `.tabstrip-more` — tokens only (`--f-mono`, `--text-sm`,
   `--ink-2`, `--line`, square corners), sits at the strip's end. Confirm against `screamingface-design`.
6. **Gates.** `run_gates.py scoreboard` green. Manual check per the spec's Tests note. Ledger
   outcome, `docs/tasks/` mirror + Linear filing at PR-open, PR `Refs: OME-N`.
