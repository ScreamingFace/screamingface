---
id: OME-1775
linear_url: https://linear.app/openmined/issue/OME-1775/do-not-mark-a-capture-partial-for-an-outcome-its-replay-reproduces
status: in_review
type: feature
priority: medium
labels: [screamingface-engine, agentic, autonomous]
parent: OME-1307
created: 2026-10-29
---

# Do not mark a capture partial for an outcome its replay reproduces exactly

A fusion capture run with one failed Case was `partial`, because the Engine counted each sibling
call it cancelled as `error`. The copy replays exactly all the same (prod check, 2026-10-29). The
Engine now forgives a no-answer outcome in a Case that failed (not on time), when no later
occurrence of the same request answered (R1). A `max-age` re-issue that returned takes its last
status (R2), and a connect-phase failure is not `ambiguous` (R3). Spec:
`docs/spec/2026-10-29-OME-1775-cancelled-call-not-partial.md`; plan:
`docs/plan/2026-10-29-OME-1775-replay-exact-not-partial.md`.

- 2026-10-29: filed; spec written; owner decisions D1–D5.
- 2026-10-29: plan approved (P1–P3); code, tests and design-doc Q32 done; reviews done and
  fixed; R1 skips a Case that failed on time (owner). Gates green. Local branch
  `OME-1775-replay-exact-not-partial`.
- 2026-10-29: found the MedXpert turn-2 replay defect; filed as OME-1786 (bug, Triage).
- 2026-10-29: second review (tiered-build workflow) found and fixed the nested `source_error`
  time codes and later-Attempt timeouts. PR opened; status In Review.
