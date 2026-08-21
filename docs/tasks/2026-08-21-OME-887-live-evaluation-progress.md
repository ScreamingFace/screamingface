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
benchmark-aware Runner coupling, public Event kind, legacy fallback, and previous UI. It retains
the explicit URL4 pass-through checkpoint concept under OME-932 without changing `packages/url4`.

Delivery units:

- OME-931 / PR #685 — sequential outer Benchmark Cases; prerequisite.
- OME-932 — Engine-owned `screamingface.evaluation-progress.v1` snapshots.
- OME-933 — strict Client decoding and the SFDS v2 Candidate table.

PR #649 remains closed as implementation history.
