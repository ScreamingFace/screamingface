---
ticket: OME-1548
stack: screamingface-engine
status: done
started: 2026-10-28
finished: 2026-10-28
---

# refuse-blind-models — refuse a picture Benchmark run whose Candidate has a model that can't see pictures

## Intent

A picture Benchmark (LAB-Bench FigQA, MMMU, HLE) must never pay for a model that can't see the
picture. Before the first paid call, the Runner checks the Benchmark's Cases. If any Case carries a
picture, it reads each Candidate model's input types from the gateway's `/v1/models` once, and
refuses the whole run with the permanent `intent_error` when any member, synthesizer or reducer
lacks `image`, naming each such model. Text Benchmarks never make the catalogue call.

Owner decisions (2026-10-28): any picture Case in the file makes the Benchmark a picture Benchmark
(the selected count doesn't matter); an unreachable catalogue fails the run before spend, as
retryable; OpenRouter models admitted on the fly report text-only and are refused (accepted, fix
belongs in the gateway); OME-1548 narrows to pictures, and the PDF, office and url4-source rows
move to a line on OME-1681.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/benchmarks/picture_admission.py` (new): the
  rule (does a Cases file need pictures; which Candidate models lack `image`), the run-expression
  scope, and the `ModelSightReader` port plus its per-node registry.
- `apps/screamingface-engine/src/screamingface_engine/benchmarks/case_selection.py`: the Cases
  route becomes async and runs the check after its existing validation.
- `apps/screamingface-engine/src/screamingface_engine/world/connector.py`: the gateway world
  registers a reader that fetches `/v1/models` with the run's identity headers.
- `apps/screamingface-engine/src/screamingface_engine/runner/executor.py`: an expression run binds
  its url4 for the length of the run.

## Test plan

- `tests/unit/test_picture_admission.py` (new): picture detection (v2 image part yes, v1 and plain
  prompt no, a malformed envelope no); Candidate model extraction (one model, Fusion members +
  synthesizer, nested Fusion, grader routes excluded); a text-only member, synthesizer and a model
  missing from the catalogue are each named; a vision lineup passes.
- End to end on a scripted gateway: a blind member fails the whole run with `intent_error` naming
  it and zero chat calls; a mixed Benchmark whose selected Cases are all text is still refused; a
  text Benchmark makes zero `/v1/models` calls; an unreachable catalogue fails the run as
  retryable before any chat call; a run with no bound expression (sync eval path) is not checked.
- Existing Cases-route tests stay green: `test_benchmark_protocol.py`, `test_native_case_index.py`,
  `test_case_positions.py`, `test_benchmark_context_routes.py`.

## Acceptance

- A text-only model in a picture Benchmark's Candidate is refused by name, with no gateway chat
  call made.
- A mixed Benchmark (some Cases text-only) is refused when one member can't take images.
- Text Benchmarks: no `/v1/models` call, no behaviour change.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus the test file `apps/screamingface-engine/tests/unit/test_picture_admission.py`.
- **Commits:** `a7311a7a7` — feat(screamingface-engine): refuse a picture run whose Candidate has a model that can't see pictures.
- **Gates:** owner rule, relevant tests only. `test_picture_admission.py` 25 passed; the Cases-route, connector and executor tests (`test_benchmark_protocol`, `test_native_case_index`, `test_case_positions`, `test_benchmark_context_routes`, `test_aigateway_connector`, `test_frozen_copy_executor`, `test_frozen_copy_normal_run`, `test_direct_run_executor`, `test_fusion_context`, `test_candidate_input`) 240 passed in all; with the inspect extra, `test_inspect_task_replay_benchmarks`, `test_inspect_imported_benchmarks`, `test_one_envelope_reader`, `test_imported_activity_lifecycle` 685 passed. ruff format + check and pyright clean on the touched files; `check_layering.py` clean. Mutations: dropping the Cases-route call or the executor binding each fail 8 end-to-end tests.
- **Deviations:**
  - No `ENGINE_ERROR_CODES` entry for `intent_error`. The SDK reads a run's failure off the websocket stream, which shows the message as written; only the sync `GET /` with `Prefer: wait` scrubs it to `internal_error`. Adding the code would mean auditing every url4 raise site of it, for a surface the SDK doesn't use.
  - The Cases handler stays synchronous for a bad selection (a prior test calls it directly) and returns a coroutine only when it has a node to check.
  - The rule module may not import `world` (shared-leaf layering rule), so the connector hands it each model route's gateway id instead of the core decoding `~`.
  - Not checked, by design: the local sync eval path (binds no run expression); a node with no gateway; a Candidate that names no model and relies on the node's default model.
