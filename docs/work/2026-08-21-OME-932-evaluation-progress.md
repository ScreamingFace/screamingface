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
publishes truthful terminal Case counts and provisional scores through OME-934's generic Log seam,
without repeating paid work, exposing Benchmark-private material, changing generated URL4 or
`packages/url4`, or changing the authoritative final Candidate Result.

## Planned changes

- `docs/spec/2026-08-22-OME-932-evaluation-progress.md`
- `docs/plan/2026-08-22-OME-932-evaluation-progress.md`
- `docs/tasks/2026-08-21-OME-932-evaluation-progress.md`
- `docs/diagrams/ome-887-live-evaluation-progress.svg`
- `docs/diagrams/ome-887-live-evaluation-progress.png`
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

- RED tests for terminal snapshots, monotonic accounting, selected-order provisional scoring, and
  final reconciliation.
- Regression tests proving URL4, protocol/revision/cache identity, Case envelope bytes, final
  Candidate Results, failure policy, and paid-call ledgers are unchanged.
- Boundary/error tests for grading failure, refusal, no gradeable Cases, projector/scorer failure,
  event-sink failure, and malformed Benchmark adapter output.
- Registry conformance tests for every shipped Benchmark and zero core imports of plugins.

## Acceptance

- Engine publishes strict `screamingface.evaluation-progress.v1` structured Log snapshots from
  semantic Benchmark execution seams.
- The Client is never required to score, parse URL4, or receive private Case material.
- Progress calculation and publication make no model, judge, network, or paid calls and cannot
  affect execution or final aggregation.
- Generated URL4 and its protocol/revision/cache identity remain byte-identical; no progress node or
  dependency is inserted and `packages/url4` remains unchanged.
- IFEval, DRACO, and HealthBench preserve existing final results under the full Engine gate.
- No production code begins before OME-934 merges, this branch is rebased, and the revised
  spec/plan are explicitly approved.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** pending
- **Commits:** pending
- **Gates:** pending
- **Deviations:** pending
