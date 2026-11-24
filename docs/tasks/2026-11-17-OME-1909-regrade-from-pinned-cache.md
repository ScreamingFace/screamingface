---
id: OME-1909
linear_url: https://linear.app/openmined/issue/OME-1909/re-grade-an-old-leaderboard-entry-from-its-pinned-cache-after-a
status: done
type: feature
priority: medium
labels: [screamingface-engine, human, design-session]
parent: OME-1299
created: 2026-11-13
closed: 2026-11-17
---

# Re-grade an old leaderboard entry from its pinned cache after a revision bump

Each board shows only its Benchmark's current published revision, so moving a revision used to
empty the board. A **re-grade** now replays an old entry's pinned cache, the stored model
replies of its run, under the Benchmark's new revision at no Candidate cost, and submits the
result as a new entry linked to the old one and credited to its submitter. A row declares the
old revisions it may be re-graded from (`regradable_from`, each paired with its Case Digest,
checked at assembly); every call, Candidate and judge, replays from the copy; the Scoreboard accepts
a re-grade only from the identities in `regrade_identities`; the SDK adds `Client.regrade`.

The owner changed the revision rule on 2026-11-17: a grading change now moves the published
revision. The bump of the 47 revisions OME-1907's wrapped-answer-letter change touches moved
out of this PR into OME-1958 (owner, 2026-11-18), so it merges and deploys right before the batch
re-grade that moves their old entries.

- 2026-11-13: filed under epic `OME-1299` as a design session.
- 2026-11-17: rule change, plan and build in one PR stacked on #1783.
- 2026-11-18: #1783 and #1892 landed; merged main in, migration renumbered to 0025, a re-grade keeps its source's cost; the 47-revision bump moved to OME-1958.
- 2026-11-20: the live judge mode moved out to OME-1979 (Filip's review: unnamed Cases missed
  the copy after a judge-cap change); HLE keeps its revision for OME-1939 (owner).
- Pending the owner: set `regrade_identities` (OpenMined/infrastructure#2382); the bump and the
  batch re-grade are OME-1958.
- Ledger: `docs/work/2026-11-17-regrade-from-pinned-cache.md`
