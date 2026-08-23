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

The table keeps Candidate, Status, Cases, Score, Cost, and Cache hit columns in fixed Candidate
order, fits the available notebook width without its own horizontal scrollbar, shows only the
Candidate display name, omits redundant aggregate cache/Run activity sections, and never
fabricates activity or evidence. The decoded final Candidate Result remains authoritative.

Cases renders exact `completed / total` text without a redundant per-row progress bar.
The benchmark name remains the stable heading; Candidate rows own lifecycle and elapsed detail.
Genuinely Running rows use the canonical static blue SFDS status square without a widget-specific
animation.

One overall SFDS track reports exact completed Candidate-Case runs over all planned Candidate-Case
runs. Its denominator is uncapped and it is omitted when the denominator is unknown. It reuses the
canonical anchored fusion gradient and width transition, while compact `state · percent` text is
right-aligned on the benchmark-title row. Exact aggregate counts remain on the progressbar for
accessibility; the Candidate table owns the visible Case fractions. Successful completion removes
the redundant full track and 100% label and shows `complete · duration`; partial stopped/failed
states retain the known progress evidence.

Running cost, model calls, and tokens remain visible as one compact evidence-only receipt rather
than three large boxes. Cost appears first. The receipt shows no placeholder values before evidence
exists, while its one-line height is reserved to prevent the table shifting when evidence arrives.

Partial coverage is explicit (`1/2 graded`) rather than a vague `Partial` label. Running and
finished rows retain per-Candidate duration in Status, using authoritative Candidate Result
timestamps after reconciliation. Numeric table columns are right-aligned for scanning.

Cache hit distinguishes `Bypassed` (reported outcomes but no cacheable request) from
`Not reported` (no cache outcome evidence). Hit/miss traffic remains a percentage.
When every observed model call is provably a hit with no contradictory cost/token evidence, the
receipt reads `model calls · fully cached · no tokens billed` instead of presenting a wall of
zeroes. The Candidate Cost cell still reports `$0.00`.

Visual styling is pinned to `OpenMined/screamingface-brand` commit `7ea35a1` (2026-08-18),
including its current shared notebook light/dark aliases and canonical table typography, spacing,
separators, weights, and semantic state colors.

Ordinary Benchmark evaluation knows the selected Case count up front and renders exact `x / N`.
Opaque `sf.evaluate(url4)` replay shows its exact observed numerator while running, then learns
the denominator from the final Report; the Client does not parse URL4.

Draft PR: https://github.com/ScreamingFace/screamingface/pull/694

Blocked by OME-950 until its relative-route span name lands.
