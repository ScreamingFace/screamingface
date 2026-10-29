---
id: OME-1775
linear_url: https://linear.app/openmined/issue/OME-1775/do-not-mark-a-capture-partial-for-a-call-cancelled-in-a-failed-case
status: todo
type: feature
priority: medium
labels: [screamingface-engine, agentic, autonomous]
parent: OME-1307
created: 2026-10-29
---

# Do not mark a capture partial for a call cancelled in a failed Case Attempt

A fusion capture run with one failed case is `partial` today, because the Engine counts each
sibling call it cancelled as `error`. The copy replays exactly all the same (prod check,
2026-10-29). The Engine stops counting a call that was cancelled before it gave an answer, in a
Case Attempt that ended failed. Spec:
`docs/spec/2026-10-29-OME-1775-cancelled-call-not-partial.md`.

- 2026-10-29: filed; spec written (waiting for owner approval).
