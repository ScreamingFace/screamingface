---
id: OME-1976
linear_url: https://linear.app/openmined/issue/OME-1976/publish-the-router-recipe-extension-implementation-spec-and-plan
status: Done
type: task
priority: high
labels: [repo-dev-processes, agentic, autonomous]
parent: OME-1306
created: 2026-11-19
closed: 2026-11-19
---

# Publish the Router Recipe extension implementation spec and plan

Publishes the approved implementation spec and plan for the Router Recipe extension (Router,
Fusion and the BERT reference) designed in screamingface-design PR #35 at `3e903bd`.

The spec pins the contracts that cross delivery Units (C1-C19). The plan orders the Units, their
dependencies and per-Unit acceptance. Both are normative for every Unit: each Unit gets its own
ledger, worktree, tests written first and gates, and pins the items the spec leaves open by
amending the spec before code.

Documentation only. No source, test, dependency or approval-manifest change. No hosted readiness
claim.

Spec: `docs/spec/2026-11-16-router-recipe-extension/`.
Plan: `docs/plan/2026-11-16-router-recipe-extension.md`.
Ledger: `docs/work/2026-11-16-router-recipe-extension-spec.md`.
Branch: `OME-1976-router-recipe-extension-spec`.

Merged [PR #1957](https://github.com/ScreamingFace/screamingface/pull/1957) as `c403ebd33`.
Linear is Done.
