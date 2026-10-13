---
ticket: OME-1476
stack: client-sf
status: done
started: 2026-10-13
finished: 2026-10-13
---

# OME-1476-pr2-arc-notebook-cost-warning — two SDK follow-ups to the ARC-AGI-2 PR

## Intent

Two SDK changes made on the first ARC-AGI-2 branch after its last push, so #1357 merged without
them:

1. The catalogue chip for a Benchmark with origin `screamingface` linked to the dev Leaderboard.
   It now links to https://leaderboard.screamingface.ai/, the host the SDK already uses as its
   default Scoreboard URL.
2. The ARC-AGI-2 notebook now shows the model and the Fusion first, then a "this will cost money"
   note, then each paid run in its own cell, so Run All up to the warning spends nothing. The
   Fusion smoke run drops from 5 grids to 2.

## Planned changes

- `packages/screamingface/src/screamingface/_ui/cards.py`: the chip's link.
- `packages/screamingface/tests/test_benchmark_catalogue_grouping.py`,
  `packages/screamingface/tests/test_benchmark_origin_tabs.py`: the two tests that pin that link
  (owner-approved edit, `.claude/test-change-approvals/OME-1476.json`, branch field moved to this
  branch).
- `packages/screamingface/scripts/build_notebooks.py` + the regenerated
  `packages/screamingface/examples/16_arc_agi_2.ipynb`.

## Test plan

- The two chip tests pin the public Leaderboard URL.
- The SDK notebook tests check the generated notebooks; the ARC notebook regenerates with no diff.

## Acceptance

- The chip opens the public Leaderboard; Run All on the ARC notebook stops before any paid call.

## Outcome

- **Actual files:** as planned, plus this ledger and the `docs/tasks` mirror line.
- **Commits:** `4e4b13272` link the ScreamingFace origin chip to the public Leaderboard;
  `21b468a91` put each paid ARC-AGI-2 run behind a cost warning (moved from the first branch onto
  main); plus the approval-branch and docs commit.
- **Gates:** `test_benchmark_catalogue_grouping.py`, `test_benchmark_origin_tabs.py` and the SDK
  notebook tests: 66 passed. The generator reproduces `16_arc_agi_2.ipynb` byte for byte.
- **Deviations:** the approval file's `branch` moved from the first branch to this one, because
  the gate matches approvals by branch name.
