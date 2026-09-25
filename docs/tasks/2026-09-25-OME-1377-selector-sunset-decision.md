---
id: OME-1377
linear_url: https://linear.app/openmined/issue/OME-1377/aigateway-decide-the-profile-selector-sunset-and-disposition-accepted
status: in_progress
type: decision
priority: high
labels: [aigateway, design-session]
parent: OME-1138
blocked_by: []
created: 2026-09-25
closed:
---

# AIGateway: decide the Profile selector sunset and disposition accepted work

Stage D decision and evidence gate of `OME-1138`. Decide the selector contract after the cutover,
the rollout and accepted-work disposition, and the catalog handling; decompose the result into one
landing per issue. No runtime code, production access, deployment change, migration, cache reset
or destructive cleanup happens in this issue.

## Progress

- 2026-09-25: local evidence pass recorded on the issue (no production access).
- 2026-09-25: owner decisions taken — D12 (reject every nonblank selector, literal `default`
  included, with a value-free non-retryable 400; the multi-Connection 409 keeps its code with new
  guidance), D4 rollout (two-phase drain, producer-off Engine as rollback floor), D13 (version bump
  of the existing catalog cards). Recorded on the issue and in the tracked spec/plan. The metamodel
  landing is `OME-1380`; census instrumentation and runtime work wait for its merge.
- 2026-09-25: metamodel merged — screamingface-design PR #25 (`OME-1380`), merge commit
  `3ba6a3d`; recorded on the issue, in the tracked plan and in the ledger
  `docs/work/2026-09-25-OME-1377-selector-sunset-decision.md`. The metamodel-first gate is passed.
  Still open: the census landing (production evidence needs `OME-1333` permission), the evidence
  window and sunset date, and the remaining landings.
