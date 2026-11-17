---
ticket: OME-1909
stack: screamingface-engine
status: in_progress
started: 2026-11-17
finished:
---

# regrade-from-pinned-cache — re-grade an old leaderboard entry from its pinned cache after a revision bump

## Intent

A grading fix that keeps every Case (OME-1907's wrapped-letter rule, 47 rows) either mixes two
gradings under one published revision or, if the revision moves, empties the board, because each
board shows only its current revision. This unit adds a **re-grade**: replay an old entry's
pinned cache under the bumped revision at no model cost and submit a new entry linked to the old
one. It ships in one PR stacked on #1783 (OME-1907), together with the bump of OME-1907's 47
revisions and the rule change that makes a grading change move the revision (owner, 2026-11-17).

## Planned changes

- `apps/screamingface-engine/docs/adding-an-imported-benchmark.md`: the revision rule now moves
  the id on a grading change, not only on a changed Case set (owner decision, 2026-11-17).
- `apps/screamingface-engine/scripts/benchmark_bump.py`: the WARNING and checklist say the same,
  with a re-grade step after the deploy.
- `apps/screamingface-engine/tests/unit/inspect/test_benchmark_fingerprints.py`: the docstring
  and failure message say the same (prior-test edit: approval manifest with the bump).
- Re-grade itself: Engine (serve the Case Digest and the revisions a row may be re-graded from),
  SDK (`Client.regrade`), Scoreboard (re-grade route, `regraded_from` / `regraded_by`, team
  allowlist), and the bump of the 47 revisions. Plan to follow on OME-1909 before any code.

## Test plan

- `tests/unit/inspect/test_benchmark_bump.py` still passes with the reworded WARNING.
- Re-grade tests: written with the plan.

## Acceptance

- The rule, the bump command and the fingerprint test all say a grading change moves the id.
- A re-grade of an OME-1907 entry under the bumped revision submits a linked entry at $0.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
- **Commits:**
- **Gates:**
- **Deviations:**
