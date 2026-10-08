---
id: OME-1384
linear_url: https://linear.app/openmined/issue/OME-1384/decide-what-to-do-with-historical-rows-that-published-a-cached-run-as
status: done
type: decision
priority: medium
labels: [scoreboard, human, design-session]
parent: OME-1251
created: 2026-09-25
closed: 2026-10-05
---

# Decide what to do with historical rows that published a cached run as $0.00

Follow-up on epic `OME-1251`. Rows submitted before the epic carry a cached run's spend, about
$0.00, as a priced `complete` cost, so they sit at the cheap end of the Pareto frontier. The new
work (`OME-1326`, `OME-1382`) fixes only new submissions, and a replay never fills a saving into
a row that already holds an amount.

Options: leave, flag and keep off the frontier, hide from cost surfaces, or ask for resubmission.
First step: count the affected rows on dev.

- 2026-09-25: filed.
- 2026-10-05: resolved for the 7 dev `draco-3pass` rows (the only affected public rows). D7 on
  `OME-1251` made archive-priced cache money publishable, so every unpriced cache entry the
  recipes hit was re-measured and loaded as `archive_matched` (`OME-1469`, $135.09 on the team
  key). The 7 rows were deleted with `scoreboard.delete_scores` and resubmitted from cached
  reruns as `complete` with their full cost ($182.82 to $500.24). Four scores are unchanged;
  `pareto_cross`, `best_open_source` and `pareto_lean` moved by under 0.01 because cases built on
  a 2026-08-22 synthesis are now fully judged. Closed in Linear.
