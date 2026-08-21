---
id: OME-887
linear_url: https://linear.app/openmined/issue/OME-887/deliver-live-per-candidate-evaluation-progress
status: in_progress
type: epic
priority: 2
labels: []
created: 2026-08-18
closed:
---

# Deliver live per-Candidate Evaluation progress

Coordinate the independently gated Engine and Client work required for a truthful,
always-alive Evaluation experience. The replacement supersedes PR #649's combined landing,
URL4 pass-through checkpoints, benchmark-aware Runner coupling, public Event kind, legacy fallback,
and previous UI.

Delivery units:

- OME-934 — generic run-scoped structured-Log seam.
- OME-932 — terminal Case counts and provisional Benchmark scores.
- OME-933 — existing-Event activity, strict progress decoding, and the SFDS v2 Candidate table.

Generated URL4 and `packages/url4` remain unchanged. OME-931 / PR #685 is independent rather than
a prerequisite. PR #649 remains closed as implementation history.
