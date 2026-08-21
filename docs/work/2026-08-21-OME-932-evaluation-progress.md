---
ticket: OME-932
stack: screamingface-engine
status: in_progress
started: 2026-08-21
finished:
---

# OME-932 — publish benchmark-native Evaluation progress

## Intent

Define and, after explicit approval, implement an Engine-owned semantic progress module that
publishes truthful per-Candidate Case lifecycle snapshots through explicit URL4 checkpoints,
without repeating paid work, exposing Benchmark-private material, changing `packages/url4`, or
changing the authoritative final Candidate Result.

## Planned changes

- `docs/spec/2026-08-22-OME-932-evaluation-progress.md`
- `docs/plan/2026-08-22-OME-932-evaluation-progress.md`
- `docs/tasks/2026-08-21-OME-932-evaluation-progress.md`
- `apps/screamingface-engine/src/screamingface_engine/benchmarks/definition.py`
- `apps/screamingface-engine/src/screamingface_engine/benchmarks/registry.py`
- `apps/screamingface-engine/src/screamingface_engine/benchmarks/progress.py`
- `apps/screamingface-engine/src/screamingface_engine/benchmarks/candidate_adapter.py`
- `apps/screamingface-engine/src/screamingface_engine/benchmarks/case_execution.py`
- `apps/screamingface-engine/src/screamingface_engine/benchmarks/evaluation.py`
- `apps/screamingface-engine/src/screamingface_engine/benchmarks/aggregation.py`
- one benchmark-agnostic Runner run-context/log port and its executor wiring, as fixed by the
  approved plan
- Benchmark-owned IFEval, DRACO, and HealthBench grading/aggregation adapters as identified by
  the approved plan
- focused Engine contract and regression tests identified by the approved plan

## Test plan

- RED tests for exact phase snapshots, monotonic accounting, selected-order provisional scoring,
  and final reconciliation.
- Regression tests proving the URL4 delta is limited to checkpoints and derived revisions, while
  Case envelope bytes, final Candidate Results, failure policy, and paid-call counts are unchanged.
- Boundary/error tests for grading failure, refusal, no gradeable Cases, projector/scorer failure,
  event-sink failure, and malformed Benchmark adapter output.
- Registry conformance tests for every shipped Benchmark and zero core imports of plugins.

## Acceptance

- Engine publishes strict `screamingface.evaluation-progress.v1` structured Log snapshots from
  semantic Benchmark execution seams.
- The Client is never required to score, parse URL4, or receive private Case material.
- Progress calculation and publication make no model, judge, network, or paid calls and cannot
  affect execution or final aggregation.
- The benchmark URL4 changes intentionally to carry explicit pass-through lifecycle checkpoints;
  `packages/url4` remains unchanged and the added text is constant in the selected Case count.
- IFEval, DRACO, and HealthBench preserve existing final results under the full Engine gate.
- No production code begins before OME-931 merges, this branch is rebased, and the spec/plan are
  explicitly approved.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** pending
- **Commits:** pending
- **Gates:** pending
- **Deviations:** pending
