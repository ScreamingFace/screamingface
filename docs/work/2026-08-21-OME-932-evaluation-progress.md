---
ticket: OME-932
stack: screamingface-engine
status: done
started: 2026-08-21
finished: 2026-08-23
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
- `docs/diagrams/ome-887-live-evaluation-progress-architecture.html`
- `docs/diagrams/ome-887-live-evaluation-progress.svg`
- `docs/diagrams/ome-887-live-evaluation-progress.png`
- `apps/screamingface-engine/src/screamingface_engine/benchmarks/definition.py`
- `apps/screamingface-engine/src/screamingface_engine/benchmarks/registry.py`
- `apps/screamingface-engine/src/screamingface_engine/benchmarks/progress.py`
- `apps/screamingface-engine/src/screamingface_engine/benchmarks/candidate_adapter.py`
- `apps/screamingface-engine/src/screamingface_engine/benchmarks/case_execution.py`
- `apps/screamingface-engine/src/screamingface_engine/benchmarks/evaluation.py`
- `apps/screamingface-engine/src/screamingface_engine/benchmarks/aggregation.py`
- OME-934's benchmark-agnostic Runner run-context/log port as an integration prerequisite; OME-932
  changes no URL4 package or executor code, while the Engine composition root supplies the exact
  installed Benchmark asset root to the concrete adapter
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

## Pre-implementation baseline — 2026-08-22

- Focused Runner seam, Benchmark protocol, final-result/error, aggregation, identity, and paid-call
  regression suite: **114 passed**.
- Command: `uv run pytest -q tests/unit/test_run_log_seam.py tests/unit/test_benchmark_run_logs.py
  tests/unit/test_benchmark_protocol.py tests/unit/test_benchmark_outcome_conformance.py
  tests/unit/test_benchmark_failure_policy.py tests/unit/test_ifeval_aggregate.py
  tests/unit/test_ifeval_aggregate_case_mapping.py tests/unit/test_draco_aggregate.py
  tests/unit/test_draco_aggregate_case_mapping.py tests/unit/test_healthbench_aggregate.py
  tests/unit/test_draco_corrective_loop_e2e.py`.

## Iteration 1 — exact discovery and terminal tracking

- Added exact structural discovery from one registered revision-pinned aggregate route and one
  canonical literal `aggregate:N`; malformed, unknown, out-of-range, duplicate-route, and
  multi-call expressions remain inert.
- Added one run-local bounded tracker that de-duplicates successful Case envelopes and accounts
  Candidate exceptions without changing their raised object or the successful Case return bytes.
- Declared the exact aggregate route on every built-in Benchmark without publishing it or adding it
  to Benchmark identity.
- TDD evidence: the new test module first failed collection because
  `screamingface_engine.benchmarks.progress` did not exist, then passed **17 tests** after the
  implementation. The baseline suite plus the new tests passes **131 tests**.
- Full gate: `uv run .claude/scripts/run_gates.py screamingface-engine` — **ALL GATES GREEN**
  (append-only check, Ruff check/format, Pyright, layering, Pytest with coverage).

## Iteration 2 — shared grading, scoring, and snapshots

- Extracted one per-Case projector and the existing scorer from each IFEval, DRACO, and
  HealthBench reducer; live projection and final aggregation now call the same functions.
- Benchmark-specific Case-evaluation endpoints register pure projector closures while their
  installed private assets are in scope. The shared Case return remains the terminal trigger, so
  no URL4 node, model/Judge call, or result byte changes.
- Added complete `screamingface.evaluation-progress.v1` snapshots for successful Cases and
  Candidate failures, including native provisional score and exact `graded / total` coverage.
- Covered out-of-order completion, selected-order scoring, integer/string URL4 Case identity,
  graded refusal, ungraded failure, scorer failure recovery, and exact bounded attributes.
- Real HealthBench limit-one URL4 conformance: the one provisional snapshot reconciles exactly to
  the final score and coverage.
- Focused Runner/Benchmark/identity/failure/paid-call suite: **166 passed**.
- Full gate: `uv run .claude/scripts/run_gates.py screamingface-engine` — **ALL GATES GREEN**
  (append-only check, Ruff check/format, Pyright, layering, Pytest with coverage).

## Iteration 3 — observational hardening and review

- Added fail-open regression coverage for pre-execution Candidate contract failures, projection
  registration, projector and scorer failures, non-finite scores, sink failures, concurrent runs,
  equivalent integer/string Case IDs, privacy-bounded diagnostics, and generic Runner layering.
- Review found and fixed four terminal-accounting gaps: Candidate validation failures before model
  execution were not counted; registration was not guarded; projector failure could imply a false
  completion; and equivalent integer/string Case IDs could count twice.
- All observational failure diagnostics are bounded to a safe exception type and warning class;
  no rendered URL4, Case data, answer, rubric, model identity, or raw error text is logged.
- Focused Runner/Benchmark/identity/failure/paid-call suite: **150 passed**.
- Full gate: `uv run .claude/scripts/run_gates.py screamingface-engine` — **ALL GATES GREEN**
  (append-only check, Ruff check/format, Pyright, recursive layering, Pytest with coverage).

## Iteration 4 — Benchmark-owned Evaluation adapter

- **Intent:** replace the unreleased loose aggregate-route and per-Case projector/scorer
  registration with one deep Benchmark Evaluation interface, bound once per run.
- **Planned files:** shared Benchmark definition/progress/run-log modules; one Evaluation adapter
  per IFEval, DRACO, and HealthBench; removal of concrete runtime progress callbacks; contract,
  conformance, failure, privacy, and layering tests; revised spec and plan.
- **Test plan:** RED interface/discovery/binding tests; built-in adapter conformance; immutable
  scorer and selected-order projection; bind/project/score fail-open behavior; no concrete runtime
  progress imports; unchanged URL4, final results, paid calls, and generic Runner diff.
- **Acceptance:** one adapter per Benchmark; no loose compatibility surface; generic tracker owns
  all progress flow after binding; full focused regression and Engine gates green.
- **Result:** every shipped Benchmark now owns one Evaluation adapter that binds its existing
  grader, scorer, private assets, and selected order once per run. Concrete runtime endpoints no
  longer know about progress registration. The production-shaped focused suite passes **161
  tests**.

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

## Iteration 5 — review hardening and redundancy cleanup

- **Intent:** retain canonical URL4 discovery while removing avoidable full-corpus work,
  duplicated Case decoding, ownership interference, and terminal-accounting gaps found in review.
- **Planned files:** shared Benchmark expression traversal, Case outcome contract/endpoint,
  progress tracker/run-log adapter, built-in Evaluation binders, focused unit/conformance tests,
  and this approved spec/plan/ledger.
- **Test plan:** RED coverage for all six review findings plus typed-outcome delivery and
  selection-only/lazy asset binding; focused regression suite; complete Engine gate.
- **Acceptance:** generated URL4, URL4 packages, paid calls, final results, and existing error
  contracts remain unchanged; progress stays fail-open, bounded, and exact.
- **Result:** canonical URL4 discovery now reuses one template-aware registry traversal; projection
  diagnostics retain identified failed terminals; identified terminals reconcile anonymous
  placeholders; progress publication cannot claim generic Log ownership; and the shared Case
  endpoint delivers one typed observation while preserving malformed authoritative returns.
- **Binding:** IFEval loads only a selected instruction spec when its Case finishes, DRACO no
  longer repeats installation's full protocol validation and loads one selected rubric lazily,
  and HealthBench defers rubric points until the matching terminal Case.
- **TDD evidence:** the initial focused run failed seven tests for the six review findings and the
  three eager binders; the typed-observation fail-open regression then failed independently.
  Final focused progress/adapter suite: **57 passed**. Broader Benchmark protocol, aggregation,
  failure-policy, identity, and paid-call regression suite: **141 passed**.
- **Gate:** `uv run .claude/scripts/run_gates.py screamingface-engine --base
  014386e79472d63a3ab21489e4dbf25e1d6a97a4` — **ALL GATES GREEN** (append-only, Ruff
  check/format, Pyright, recursive layering, full Pytest coverage).
- **Deviation:** complete snapshots now explicitly permit `cases.failed` to decrease only when an
  identified terminal replaces an anonymous failure placeholder; `cases.completed` never
  decreases. This is the owner-approved correction that prevents genuine Cases being frozen out.

## Outcome

- **Actual files:** Benchmark definition/registry metadata; run-local progress discovery, tracking,
  and Log adapter; the Engine composition-root asset injection; shared Candidate/Case observation
  seams; IFEval, DRACO, and HealthBench Evaluation adapters over their existing graders/scorers;
  focused unit, conformance, privacy, isolation, and layering tests; approved spec, plan, task
  mirrors, ledger, and architecture diagram.
- **Commits:** `9e5c9cd2` (terminal tracking), `27c9f511` (shared live/final scoring),
  `19d1565d` (observational hardening), plus
  `refactor(screamingface-engine): deepen benchmark evaluation progress` in this iteration.
- **Gates:** `uv run .claude/scripts/run_gates.py screamingface-engine --base
  014386e79472d63a3ab21489e4dbf25e1d6a97a4` — **ALL GATES GREEN** (append-only, Ruff
  check/format, Pyright, recursive layering, full Pytest with coverage); focused production-shaped
  contract regression command — **161 passed**.
- **Deviations:** Iteration 4 replaces OME-932's own unreleased interface and its branch-local
  contract tests with the owner-approved deeper adapter; it carries no compatibility fallback.
  OME-934 remains the integration prerequisite. Before merging OME-932, retarget/rebase it onto the
  merged seam and rerun the same focused suite and full Engine gate. No generic executor,
  generated URL4, `packages/url4`, paid-call, cache-identity, or final-result change is added here;
  `runner/main.py` only wires the concrete adapter with the already-resolved Benchmark asset root.
