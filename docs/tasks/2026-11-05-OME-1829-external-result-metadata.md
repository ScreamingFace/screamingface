---
id: OME-1829
linear_url: https://linear.app/openmined/issue/OME-1829/store-metadata-for-external-leaderboard-results
status: done
type: feature
priority: medium
labels: [scoreboard, autonomous, agentic]
created: 2026-11-05
closed: 2026-11-09
---

# Store metadata for external leaderboard results

Parent: E20 / OME-1309.

Record metric, source-read date, internal attribution and latest import time.
Expose metric/dates on public and private boards; keep attribution internal.
Preserve legacy imports and first-import times, with a nullable migration and
regression tests. Imports replace observations; edit history is separate work.

Implementation and local checks complete; PR publication in progress.

Merged [PR #1683](https://github.com/ScreamingFace/screamingface/pull/1683) on 2026-11-09 as `d052f4718d477dbfe153962eb54c7f6c71c921c0`. Linear is Done.
