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
checked at assembly); the Engine can send chosen Cases' judge calls live; the Scoreboard accepts
a re-grade only from the identities in `regrade_identities`; the SDK adds `Client.regrade`.

The owner changed the revision rule on 2026-11-17: a grading change now moves the published
revision. This PR, stacked on #1783 (OME-1907), moves the 47 revisions OME-1907's
wrapped-answer-letter change touches; their old ids are in the comments of
`test_published_revisions.py`.

- 2026-11-13: filed under epic `OME-1299` as a design session.
- 2026-11-17: rule change, plan and build in one PR stacked on #1783.
- Pending the owner: post to the team before merging, set `regrade_identities`, and after the
  deploy (and the Scoreboard seed showing the new revision) re-grade the cached entries the live
  board lists (130 of 138 on 30 boards on 2026-11-17) and rerun the 8 with no pinned cache.
- Ledger: `docs/work/2026-11-17-regrade-from-pinned-cache.md`
