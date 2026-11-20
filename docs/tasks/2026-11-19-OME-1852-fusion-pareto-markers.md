---
id: OME-1852
linear_url: https://linear.app/openmined/issue/OME-1852/visually-distinguish-fusions-from-single-models-on-leaderboard-pareto
status: in_review
type: feature
priority: 3
labels: [scoreboard, agentic, autonomous]
created: 2026-11-19
closed:
---

# Visually distinguish fusions from single models on the leaderboard Pareto chart

Owner decision: **Option A — shape.** Circle = single model, square = fusion. Keep the
existing blue frontier line and gold highest-score ring as-is.

## Requirements

- Expose `candidate_kind` on leaderboard rows, derived from metadata — never from names or
  model count.
- A missing/unknown composition type reads as "Unknown"; never mislabeled as a fusion.
- The circle/square type is in the chart legend and in accessible point details (title/ARIA
  text), not only a visual shape.
- The frontier line, the highest-score ring, and the missing-cost marker stay visually
  distinct from the new shape encoding. Checked in both themes and at mobile width.
- Visual encoding only — no change to scores, ranking, or frontier membership.

## Note

OME-1972 duplicates part of this scope; OME-1852 is the authoritative ticket being
implemented here.

## Status (2026-11-20)

Owner approved the two pinned-test edits directly (`.claude/test-change-approvals/OME-1852.json`).
Implemented, gates green, committed (`0db73dad0`), pushed, and PR opened:
https://github.com/ScreamingFace/screamingface/pull/1986. Awaiting review + green CI, then
squash-merge. Close this mirror and the Linear issue once merged.

## Ledger

`docs/work/2026-11-19-OME-1852-fusion-pareto-markers.md`
