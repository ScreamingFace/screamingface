---
id: OME-1609
linear_url: https://linear.app/openmined/issue/OME-1609/make-the-leaderboard-list-filter-hide-rows-that-do-not-match
status: done
type: bug
priority: medium
labels: [bug, client-sf, agentic, autonomous]
parent: none (bug exception)
created: 2026-10-15
closed: 2026-10-20
---

# Make the leaderboard list filter hide rows that do not match

Typing into the filter above `sf.leaderboards.list()` set `row.hidden` on non-matching rows, but
the row's `display:grid` outranked the browser's `[hidden]` rule, so every row stayed visible. One
rule in the leaderboard style lets a hidden row drop out of the list.

- 2026-10-15: filed at PR-open. Owner verify: type into the filter in JupyterLab; only matching rows remain.
