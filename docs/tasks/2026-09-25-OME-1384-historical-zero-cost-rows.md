---
id: OME-1384
linear_url: https://linear.app/openmined/issue/OME-1384/decide-what-to-do-with-historical-rows-that-published-a-cached-run-as
status: backlog
type: decision
priority: medium
labels: [scoreboard, human, design-session]
parent: OME-1251
created: 2026-09-25
closed:
---

# Decide what to do with historical rows that published a cached run as $0.00

Follow-up on epic `OME-1251`. Rows submitted before the epic carry a cached run's spend, about
$0.00, as a priced `complete` cost, so they sit at the cheap end of the Pareto frontier. The new
work (`OME-1326`, `OME-1382`) fixes only new submissions, and a replay never fills a saving into
a row that already holds an amount.

Options: leave, flag and keep off the frontier, hide from cost surfaces, or ask for resubmission.
First step: count the affected rows on dev.

- 2026-09-25: filed.
