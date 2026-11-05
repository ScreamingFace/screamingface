---
id: OME-1829
linear_url: https://linear.app/openmined/issue/OME-1829/store-metadata-for-external-leaderboard-results
status: in_progress
type: feature
priority: medium
labels: [scoreboard, autonomous, agentic]
created: 2026-11-05
closed:
---

# Store metadata for external leaderboard results

Parent: E20 / OME-1309.

Record metric, source-read date, internal attribution and latest import time.
Expose metric/dates on public and private boards; keep attribution internal.
Preserve legacy imports and first-import times, with a nullable migration and
regression tests. Imports replace observations; edit history is separate work.

Implementation and local checks complete; PR publication in progress.
