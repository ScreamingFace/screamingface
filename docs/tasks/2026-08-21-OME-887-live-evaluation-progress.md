---
id: OME-887
linear_url: https://linear.app/openmined/issue/OME-887/deliver-live-per-candidate-evaluation-progress
status: pick_immediately
type: epic
priority: 2
labels: []
created: 2026-08-18
closed:
---

# Deliver live per-Candidate Evaluation progress

Coordinate the independently gated Engine and Client work required for a truthful,
always-alive Evaluation experience. The replacement supersedes PR #649 and does not add
URL4 checkpoints, a new public Event kind, or a legacy progress fallback.

Delivery units:

- OME-931 / PR #685 — sequential outer Benchmark Cases; prerequisite.
- OME-932 — Engine-owned `screamingface.evaluation-progress.v1` snapshots.
- OME-933 — strict Client decoding and the SFDS v2 Candidate table.

PR #649 remains closed as implementation history.
