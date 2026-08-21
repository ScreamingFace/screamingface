---
id: OME-933
linear_url: https://linear.app/openmined/issue/OME-933/redesign-live-evaluation-progress
status: pick_immediately
type: improvement
priority: 2
labels: [py-screamingface, agentic, deferred]
created: 2026-08-21
closed:
---

# Redesign live Evaluation progress

Replace the notebook Evaluation panel with a stable SFDS v2 Candidate table driven by the
Engine's strict `screamingface.evaluation-progress.v1` snapshots and existing public Events.

The table keeps Candidate, Status, Case, Score, Cost, and Cache columns in fixed Candidate
order, uses horizontal scrolling on narrow screens, preserves the aggregate cache-provenance
band, and never fabricates activity or evidence. The decoded final Candidate Result remains
authoritative.

Blocked by OME-932. Canonical spec, plan, and ledger will be created in this worktree before
implementation begins.
