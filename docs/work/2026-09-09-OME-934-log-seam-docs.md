---
ticket: OME-934
stack: screamingface-engine
status: in_progress
started: 2026-09-09
finished:
---

# OME-934 — Review the generic Log seam before implementation

## Intent

Land a focused docs-only design PR before a separate implementation PR. The user authorized this split. OME-934 remains open until the generic infrastructure is delivered; merging these documents is not feature completion.

## Planned changes

- docs/spec/2026-09-09-OME-934-log-seam.md
- docs/plan/2026-09-09-OME-934-log-seam.md
- docs/tasks/2026-09-09-OME-934-log-seam.md
- This ledger.

## Test plan

Compare against the current Linear contract and origin/main executor/bridge/composition code; check document links, whitespace and scope. Run repository hooks and applicable CI. No Python changes or paid tests.

## Acceptance

One optional generic factory, ordinary Log delivery, explicit lifecycle/validation/failure contracts, fake-adapter verification plan, and no concrete producer or Benchmark ownership machinery. Reviewable independently of implementation and OME-1153.

## Outcome

- **Actual files:** Four planned Markdown files; no production/test/config changes.
- **Commits:** This docs-only commit, docs(engine): specify the generic run Log seam; Refs: OME-934.
- **Gates:** Four-document whitespace/conflict-marker/local-link validation passed; scope checked against live Linear and current executor. Repository hooks and PR CI run at publish. No Engine gates required for a docs-only diff.
- **Deviations:** None. New worktree from origin/main ad0c965d; no commits imported from closed PRs 689/692.
