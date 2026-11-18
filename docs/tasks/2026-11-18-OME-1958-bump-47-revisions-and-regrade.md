---
id: OME-1958
linear_url: https://linear.app/openmined/issue/OME-1958/move-the-old-leaderboard-entries-onto-the-new-revisions-once-the-re
status: done
type: task
priority: medium
labels: [scoreboard, human, task]
parent: OME-1299
created: 2026-11-18
closed: 2026-11-18
---

# Move the old leaderboard entries onto the new revisions once the re-grade is deployed

OME-1907 changed how 47 Benchmarks read a wrapped answer letter and held their revisions. This
PR moves the 47 published revisions (each row lists its old id in `regradable_from`), and after
the deploy the batch re-grade moves every old entry with a pinned cache onto the new id at no
model cost (`Client.regrade`, OME-1909).

- 2026-11-18: filed as the reminder for the batch; the bump moved here from #1896 (owner).
- Pending the owner: merge after #1896 is deployed and right before the batch, then the steps
  in the Linear issue (seed check, batch re-grade, HLE re-judge after OME-1939, the 8 uncached).
- Ledger: `docs/work/2026-11-18-bump-47-revisions.md`
