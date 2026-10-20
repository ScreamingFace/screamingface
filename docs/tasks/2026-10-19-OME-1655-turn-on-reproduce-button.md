---
id: OME-1655
linear_url: https://linear.app/openmined/issue/OME-1655/turn-on-the-reproduce-button-on-the-leaderboard
status: backlog
type: task
priority: medium
labels: [scoreboard, agentic, deferred]
parent: OME-1307
created: 2026-10-19
closed:
---

# Turn on the Reproduce button on the leaderboard

`OME-1596` ships the Reproduce button in the board's Run column behind `SHOW_REPRODUCE_BUTTON` in
`apps/scoreboard/portal/benchmark.js`, off. This ticket turns it on, once the SDK release with
`sf.evaluate(pinned_cache=…)` (`OME-1613`) is out, so the copied snippet runs as written.
Blocked by `OME-1613`.

- 2026-10-19: filed by the owner, split out of `OME-1596`'s acceptance.
