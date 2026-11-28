---
id: OME-2001
linear_url: https://linear.app/openmined/issue/OME-2001/show-on-each-leaderboard-why-a-benchmarks-revision-changed
status: Done
type: feature
priority: medium
labels: [scoreboard, user-request, agentic, autonomous]
parent: OME-1286
created: 2026-11-23
closed: 2026-11-23
---

# Show on each leaderboard why a Benchmark's revision changed

A Benchmark's published revision moves when its Cases or its grading change, and the
leaderboard showed the new revision as a date, a hash and a result count. A reader could not
tell what changed or whether old scores still compare.

A Benchmark can now declare a **revision note** beside its revision id: one short plain-text
line. About 120 characters is the target the author aims for, not a limit. The Engine serves it in the public catalogue, the Scoreboard seed job
stores it on the revision's record, the revisions list returns it, and the Benchmark page shows
the selected revision's note under the revision selector, after the date the leaderboard first
saw that revision. A revision without a note shows what it showed before.

A new or moved revision without a note fails the Engine's check
(`apps/screamingface-engine/tests/unit/inspect/test_revision_notes.py`). The revisions already
published on main carry no note and need none; that set is frozen.

No score, ranking or revision id changes. No existing revision got a note.

Ledger: `docs/work/2026-11-23-revision-note.md`.
Branch: `OME-2001-revision-note`.
