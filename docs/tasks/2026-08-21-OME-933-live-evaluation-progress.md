---
id: OME-933
linear_url: https://linear.app/openmined/issue/OME-933/redesign-live-evaluation-progress
status: in_progress
type: improvement
priority: 2
labels: [py-screamingface, agentic, autonomous]
created: 2026-08-21
closed:
---

# Redesign live Evaluation progress

Replace the notebook Evaluation panel with a stable SFDS v2 Candidate table driven only by
existing public Events. Exact Case completion comes from terminal spans whose operation is
`RelUrlNode` and whose name is `/benchmarks/case-execution`.

The table keeps Candidate, Status, Progress, Score, Cost, and Cache columns in fixed Candidate
order, uses horizontal scrolling on narrow screens, preserves the aggregate cache-provenance
band, and never fabricates activity or evidence. The decoded final Candidate Result remains
authoritative.

Ordinary Benchmark evaluation knows the selected Case count up front and renders exact `x / N`.
Opaque `sf.evaluate(url4)` replay shows its exact observed numerator while running, then learns
the denominator from the final Report; the Client does not parse URL4.

Blocked by OME-950. Canonical spec, plan, and ledger precede implementation.
