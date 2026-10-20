---
title: Plan — a spec-faithful URL4 expression for imported benchmarks and MedXpertQA
spec: docs/spec/2026-10-20-url4-benchmark-expression-spec.md
ticket: unfiled
branch: url4-benchmark-expression
created: 2026-10-20
---

# Plan

Three stacks: `packages/url4` (one export), `apps/screamingface-engine` (the change), and
`packages/screamingface` (linking and progress). The work goes in the order below, and each step
is RED → GREEN. Prior tests that pin the old expression text change only where this plan names
them (owner approval: spec §6, D1–D5).

## Proven before the plan (prototype, 2026-10-20)

- The §3.1 shape runs on `packages/url4` unchanged (toy node: data route, code mounts, slice,
  `$candidate`/`$index` deep in the body, packed context, collected error rows).
- The new Candidate input (`'$item.input'` as the intent) is byte-identical to the old struct
  path for plain, multi-line, `$`-bearing, JSON-envelope and non-JSON text.
- The MedXpertQA turn-2 input is `json.dumps({"question", "reasoning", "trigger"})` with
  defaults, where `reasoning` is the turn-1 record text. A code step reproduces it.

## Step 1 — `url4`: export the collected-error payload

- `packages/url4/src/url4/dag/nodes/_shared.py`: keep `_error_payload` as the one
  implementation; expose it as `collected_error(exc) -> dict` from `url4.dag` (public).
- Test: `packages/url4/tests/unit/test_collected_error.py` — code/retryable kept; a plain
  exception gives kind/message only; equal to the row that `iterate(on_error=collect)` writes.

## Step 2 — Engine: the Candidate request

- `benchmarks/case_request.py`: replace the `case-v1` decoders with one
  `candidate_request(request) -> CandidateRequest(input_text, recipe, case_id, position)`.
  - The context is the packed lines `case_id: …`, `case_index: …`, `case_count: …`, then
    `recipe: <rest>`. The recipe is last and may hold new lines.
  - `input_text` is `request.intent`.
  - A context that does not match raises `candidate_contract_error` (permanent).
  - `candidate_attempt` is unchanged.
- `world/candidate_adapter.py`: evaluate `recipe` with `input_text`; the scopes do not change.
  `context_format` leaves `_METADATA_PARAMS`.
- `benchmarks/definition.py`: `candidate_call` / `candidate` become one
  `candidate_invocation(prompt, *, case_count, web_search, web_search_exclude=(), attempt=1)`
  that returns the `RelExpr` of §3.1. `link_candidate` inserts the binding (Step 5 rule).
- Tests: rewrite `tests/unit/test_case_activity.py`, `test_case_positions.py`,
  `test_benchmark_context_routes.py` callers to the new request; add decoder tests (recipe with
  new lines, missing line, bad position).

## Step 3 — Engine: the shared protocol

- `benchmarks/protocol.py` keeps `EVALUATION_PROTOCOL_REVISION` (value unchanged, D5) and
  replaces the helpers with:
  - `evaluation_protocol(*, routes, case_count, steps, case_terminal, run_terminal) -> Node`
    (§3.1/§3.2 outer shape: data-route collection, `case` binding, `steps`, slice,
    `concurrency=1`, `on_error=collect`, top-level `selected`).
  - `attempt_steps(prompt, *, attempts, case_count, web_search, …) -> tuple[Node, ...]`
    (`attempt_1..N`; `attempt=i` on i ≥ 2).
- `benchmarks/case_evaluation.py` (new): the code-mount adapters.
  - `case_evaluation_code(*, check, build_case_grade, extra_inputs=()) -> CodeHandler`: reads
    `case` and `attempt_1..N`; for each Attempt runs `check` and `build_case_grade` in process;
    a failure becomes `collected_error(exc)`; returns the `case-execution.v1` row (N = 1) or the
    `case-attempts.v1` row (N ≥ 2); reports `report_case_grading` as today.
  - `aggregate_code(*, label, available_case_count, aggregate)`: reads `evaluations` and
    `selected`; passes the JSON array text and the count to today's adapter; async, awaited on
    the run's loop.
- `benchmarks/case_selection.py`: `install_cases` registers a data route
  (`application/json`).
- `benchmarks/graded_answer.py`: keep `graded_answer_payload`, `graded_answer`,
  `case_attempts` (readers); delete the two endpoints and their install.
- `benchmarks/grading_endpoints.py`: `attempt_records_endpoint` and the endpoint variants of
  aggregate leave; `_aggregate_selection` takes an int.

## Step 4 — Engine: the two builders

- `screamingface_engine_inspect/single_shot.py`:
  - `_build` renders §3.1 through `evaluation_protocol` + `attempt_steps`.
  - `install_imported_benchmark` mounts `cases` (data), `case-evaluation` and `aggregate`
    (code). `_check` becomes the in-process check (`case_id`, `invocation`) with its phase and
    `case_scope(recording=True)` kept. `check_surface` stays an endpoint (corrective loop).
- `benchmarks/medxpert/definition.py`: `_build` renders §3.2.
- `benchmarks/shared_grading/serving.py` / `incremental_routes.py`: `install_benchmark` mounts
  `cases` (data), `case-evaluation`, `commit-prompt` (MedXpertQA only), `aggregate`,
  `aggregate/case-result`, `aggregate/graded` (code).
- `benchmarks/medxpert/runtime.py`: the in-process check (`case_id`, `reasoning`, `commit`).
- Tests to change (they pin the old text or call the old endpoints):
  `test_benchmark_protocol.py` (MedXpertQA sha pin → the new text), `test_early_grade_*`,
  `test_medxpert_migration_golden.py`, `test_medxpert_protocol_turns.py`,
  `test_case_attempts_protocol.py`, `test_attempt_fold.py`, `test_native_case_index.py`,
  `tests/unit/inspect/*` that call `aggregate:N`, and the fixture
  `tests/fixtures/early_grade_compatibility.json`.
- New tests: the rendered expressions obey R7 (no quoted intent that is not a prompt); the
  revision ids of every imported board and MedXpertQA are unchanged; `commit-prompt` equals the
  old turn-2 bytes; a grader failure keeps the Candidate answer in the row.

## Step 5 — Client (`packages/screamingface`)

- `_evaluation/linking.py`: `bind` inserts `candidate:0.0:'<recipe>'` as the first source of the
  top-level `Expression`; the `(…)!''` wrapper and the `Iteration` wrap go away (a top-level
  `Iteration` is wrapped as `(candidate…, benchmark_result:0.0:<it>)!<…>` only if a Benchmark
  ever ships one — none does; refuse it instead).
- `_ui/evaluation_state.py`: count `CodeCallNode` spans whose name ends in `/case-evaluation`.
- Tests: `test_shape_adaptive_linking.py`, `test_benchmark_compilation.py`,
  `test_pipeline_compilation.py`, `test_live_candidate_progress.py`,
  `packages/url4/tests/unit/test_observe.py` (span names).

## Step 6 — Gates, review, kind validation

1. `uv run .claude/scripts/run_gates.py <stack>` for each of the three stacks.
2. `design-reviewer` against the spec.
3. kind: build this branch, run 3-case ContractEval and 3-case MedXpertQA with the same
   Candidate as the `origin/main` baseline, through the seeded prod cache. Compare per-case
   answers, per-case scores, headline metric, and the aigateway cache-miss count (must be 0).
