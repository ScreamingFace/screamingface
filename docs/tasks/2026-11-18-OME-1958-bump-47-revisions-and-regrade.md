---
id: OME-1958
linear_url: https://linear.app/openmined/issue/OME-1958/move-the-old-leaderboard-entries-onto-the-new-revisions-once-the-re
status: in_progress
type: task
priority: medium
labels: [scoreboard, human, task]
parent: OME-1299
created: 2026-11-18
closed:
---

# Move the old leaderboard entries onto the new revisions once the re-grade is deployed

OME-1907 changed how 47 Benchmarks read a wrapped answer letter and held their revisions. This
PR moves the 47 published revisions (each row lists its old id in `regradable_from`), and after
the deploy the batch re-grade moves every old entry with a pinned cache onto the new id at no
model cost (`Client.regrade`, OME-1909).

- 2026-11-18: filed as the reminder for the batch; the bump moved here from #1896 (owner).
- 2026-11-20: the batch script ships here; live judging moved to OME-1979 and HLE keeps its
  revision (owner), so no HLE re-judge runs in this batch. Open until the batch has run.
- 2026-11-20 review follow-up: batch scope is the explicit 47 board/source/target pairs.
  One operator machine and persistent log path serialize scheduled runs; uncached and refused
  entries keep exit status 1 until an owner resolution is recorded. Use the script docstring
  for `--resolve ENTRY_KEY=NOTE`. The log is tied to the Scoreboard URL and target revisions.
- Pending the owner: merge after #1896 is deployed and right before the batch, then the steps
  in the Linear issue (seed check, one cyse4 entry first, batch re-grade, the uncached entries).
- Ledger: `docs/work/2026-11-18-bump-47-revisions.md`
