---
id: OME-969
linear_url: https://linear.app/openmined/issue/OME-969/score-submission-metadata-is-unbounded-on-the-public-write-path
status: done
type: bug
priority: 2
labels: [scoreboard, agentic, autonomous, bug]
created: 2026-08-24
closed: 2026-11-05
---

# Score submission metadata is unbounded on the public write path

`_validate_bounded_metadata` (depth ≤ 4, ≤ 4096 bytes) guards the operator baseline paths
but not `ScoreSubmission`. Observed: a 64 KB blob and 10-level nesting both returned 201 on
the effectively unauthenticated public write path, in a repo with no rate limiting.
Prerequisite for putting trace context in `metadata` (the only seam, since the schema is
`extra="forbid"`). Reuse the existing validator.

Canonical artifacts:

- Spec: `docs/spec/2026-08-22-observability-traceability-review.md` (§4)

Implementation ledger: `docs/work/2026-10-30-submission-metadata-limits.md`.

Merged [PR #1623](https://github.com/ScreamingFace/screamingface/pull/1623)
on 2026-11-05, commit `49d0d5312966d377caa3f0e8526314687394e1b0`. Linear is Done.
