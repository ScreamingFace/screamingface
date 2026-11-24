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

## Status (2026-11-23)

HupBaHa reviewed PR #1986 and requested changes: rebase onto main + regenerate the stale
test-change approval (P1), give Unknown its own marker shape with a rendered-SVG regression
(P2), and expose candidate kind per table row for accessibility with a regression (P2).

This round: merged current main (conflicts resolved, keeping every target test on both
sides), fixed both P2s with new regression tests, reconfirmed every other gate green against
real `origin/main`. Pushed to `origin/OME-1852-fusion-pareto-markers`.

## Status (2026-11-24)

Filip confirmed the manifest values directly; `.claude/test-change-approvals/OME-1852.json`
updated and committed. Pushing surfaced main had moved another 7 commits, requiring a second
rebase — resolved (four more textual-only conflicts, nothing semantic). All gates green,
including the append-only check via the real branch name (confirmed through the `pre-push`
hook, which resolves it correctly unlike a direct CLI run from these differently-named
worktrees). PR `mergeable: MERGEABLE`. Full detail in the ledger's "Sixth update".

Still waiting on: HupBaHa's re-review (not a new ask — same review, now addressed).

Close this mirror and the Linear issue once re-review lands, CI is green, and the PR is
squash-merged.

## Ledger

`docs/work/2026-11-19-OME-1852-fusion-pareto-markers.md`
