# Plan — DRACO 3-pass variant (`draco-3pass`)

Ticket: none (owner decision — no Linear issue for this unit)
Spec: `docs/spec/2026-08-20-draco-3pass-variant.md` (approved 2026-08-20)
Branch: `draco-3pass-variant` (from `origin/main` @ 43c743da)

## Approach

Mirror the HealthBench board factory (`benchmarks/healthbench/exam.py` → `definition.py`):
one shared protocol builder, several `Benchmark` identities. DRACO gains `exam.py`
(factory, `Routes`, `DracoExam`, revision fingerprint, protocol builder) and
`definition.py` becomes a boards module producing `DRACO` (5-pass, byte-identical
revision) and `DRACO_3PASS` (3-pass, own revision).

## Changes

1. NEW `src/screamingface_engine/benchmarks/draco/exam.py`
   - Move shared pins from `definition.py`: `DATASET`, `DATASET_REVISION`,
     `DATASET_PREPARER_REVISION`, `CASE_COUNT`, `JUDGE_MODEL`, `RETRIEVAL_POLICY_ID`,
     `EXCLUDED_DOMAINS`, `JUDGE_PARAMS`, `CHECK_CRITERION`; import
     `JUDGE_INSTRUCTIONS` from `draco.prompts`.
   - `Routes` dataclass (7 addresses under `/benchmarks/{id}/{revision}/`) with
     `for_exam` classmethod.
   - `DracoExam` dataclass: `id`, `revision`, `routes`, `judge_passes`.
   - `draco_revision(*, protocol_revision, judge_passes)` — EXACT current hash tuple
     (definition.py:52–70), so canonical inputs reproduce today's revision.
   - `build_draco_protocol(routes, case_count, judge_passes)` — current `_build`
     parameterized.
   - `draco_benchmark(...)` factory returning `(exam, benchmark)`; install closure:
     `install_runtime(node, assets / "draco", exam)` (SHARED canonical assets).

2. **`src/screamingface_engine/benchmarks/draco/definition.py`** → boards module
   - `CANONICAL_EXAM, DRACO = draco_benchmark(id="draco", judge_passes=5,
     protocol_revision="five-pass-reproduction-v1", ...)`
   - `THREE_PASS_EXAM, DRACO_3PASS = draco_benchmark(id="draco-3pass",
     judge_passes=3, protocol_revision="three-pass-reproduction-v1", ...)`
     with title "DRACO 3-Pass".
   - Backwards-compatible canonical aliases (tests/runtime import them):
     `BENCHMARK_ID`, `REVISION`, `JUDGE_PASSES`, `JUDGE_SEEDS`, `ROUTE_PREFIX`,
     `CASES_ROUTE`, `TASKS_ROUTE`, `VERDICT_ROUTE`, `CRITERION_EVALUATION_ROUTE`,
     `CASE_EVALUATION_ROUTE`, `AGGREGATE_ROUTE`, `CHECK_SURFACE_ROUTE`,
     `JUDGE_MODEL`, `JUDGE_PARAMS`, `CHECK_CRITERION`.

3. **`src/screamingface_engine/benchmarks/draco/runtime.py`**
   - `install(node, root, exam)` — routes from `exam.routes`; aggregate closure
     passes `exam.id` / `exam.judge_passes` / `exam.revision`.
   - `_criterion_evaluation(judge_passes)` closure for the expected-evidence fields.

4. **`src/screamingface_engine/benchmarks/draco/aggregate.py`** — unchanged
   (canonical defaults `JUDGE_PASSES`/`REVISION` remain valid; the variant passes
   explicit values from the runtime).

5. **`src/screamingface_engine/benchmarks/builtins.py`** — add `DRACO_3PASS`.

6. **Tests**
   - NEW `tests/unit/test_draco_3pass_definition.py`:
     - canonical revision pinned (equals today's value, computed pre-change);
       variant revision differs.
     - `DRACO_3PASS.build(1)` renders exactly 3 verdict calls, `evidence_1..3`,
       seeds `seed=1..3`; canonical still 5.
     - routes under `/benchmarks/draco-3pass/{rev}/`, no overlap with canonical.
     - `BenchmarkRegistry((DRACO, DRACO_3PASS))` install + route validation.
     - aggregate with `judge_passes=3` → CandidateResult `benchmark_id="draco-3pass"`,
       `n_runs == 3`.
   - `tests/unit/test_benchmark_protocol.py`: catalogue tuple gains `"draco-3pass"`.
   - `tests/unit/test_draco_case_evaluation_route.py`: pass the canonical exam to
     `install(node, root, exam)` (2 call sites).

7. **Docs** — `draco-cache-seed/RUNBOOK.md`: fully-cached replay section.

## Test gate

- `uv run pytest apps/screamingface-engine/tests/unit` green in the worktree.
- New tests fail before the change (write-first order).
