---
id: OME-1586
linear_url: https://linear.app/openmined/issue/OME-1586/add-the-judge-combine-operators-and-the-scorejudge-signal
status: in_progress
type: feature
priority: 3
labels: [screamingface-engine, agentic, autonomous]
created: 2026-10-12
closed:
---

# Add the judge combine operators and the score:judge signal

Mirror of OME-1586 (parent epic OME-1289). PR 9 of 16 in the E4a stack, branch
`OME-1586-e4a-judge-pick-engine` on `OME-1585-e4a-weighted-vote`.

One judge model call labels or scores the members, then a fixed rule picks: `label@1`, `scores@1`, `by_label@1`, `max_score@1`. The reply format is strict; a bad reply fails with `judge_reply_invalid`. `score:judge` can weight a vote. Over a quorum panel the judge is read against the members that answered.

Ledgers: `docs/work/2026-10-01-e4a-judge-pick-engine.md`, `docs/work/2026-10-02-e4a-gap-closure-unit8e.md`.
