# Spec — DRACO 3-pass variant (`draco-3pass`) for the cache-seeded replay

Status: DRAFT for approval
Date: 2026-08-20
Ticket: OME-<TBD> (owner creates the Linear issue; no Linear MCP in this session)

## 1. Purpose

The `draco-cache-seed` archive (`draco-cache-seed/rows.jsonl`, 177,653 rows) covers
**grading rounds 1–3 only** of canonical DRACO. Canonical DRACO grades every answer 5
times (`JUDGE_PASSES = 5`), so a canonical re-run still pays ~116,270 judge calls at
rounds 4–5 (RUNBOOK.md).

We introduce a **3-pass DRACO variant** whose protocol emits exactly the 3 judge
passes the archive covers. Replaying the archived candidates against this variant
hits cache for every verdict call: candidate answers, syntheses, and judge verdicts
rounds 1–3 are all in the seed, and criterion/case evaluation and aggregation are
engine-side routes that cost nothing. The canonical 5-pass DRACO stays untouched so
published 5-pass scores stay comparable (OME-775: a different revision is a different
benchmark).

## 2. Decisions

| Decision | Value | Why |
|---|---|---|
| Benchmark id | `draco-3pass` | Flat id matches SDK rule `[a-z0-9][a-z0-9._-]*` (`_benchmark_identity.py`); follows the `healthbench-worst30` / `healthbench-professional` board naming convention |
| Judge passes | `3` | Matches the archive's rounds 1–3 exactly |
| Protocol revision | `three-pass-reproduction-v1` | New identity; canonical keeps `five-pass-reproduction-v1` |
| Assets | **Shared** with canonical (`assets/draco/`) | Same dataset, cases, criteria, rubrics — the archive IS canonical's data |
| Check surface | Same criterion `draco-pass.v1`, same `DRACO_CHECK` | The check is an independent steering instrument with its own batched judge (`check_policy.py`); it does not depend on judge passes |
| Candidate/synthesis | Identical to canonical | The protocol's candidate invocation, retrieval policy, and excluded domains are unchanged |
| Canonical identity | Byte-for-byte unchanged | `draco` keeps the same revision hash, routes, and behavior (frozen, like `healthbench-worst30`) |

## 2. Design — mirror the HealthBench board factory

HealthBench already solves "several identities over one shared protocol":

- `healthbench/exam.py`: `Routes` (7 revision-pinned addresses), `Exam` (id, revision, routes, mean), `exam_revision(...)` fingerprint, `build_exam_protocol(...)`, and the `healthbench_benchmark(...)` factory returning `(exam, benchmark)`.
- `healthbench/definition.py`: two boards, one call each to the factory.
- `healthbench/runtime.py`: `install(node, assets, exam)` — consumes the exam, not module constants.

DRACO gets the same shape:

- **New `draco/exam.py`** (mirrors `healthbench/exam.py`):
  - `Routes` frozen dataclass: `cases`, `tasks`, `verdict`, `criterion_evaluation`,
    `case_evaluation`, `aggregate`, `check_surface` under `/benchmarks/{id}/{revision}/`.
  - `DracoExam` frozen dataclass: `id`, `revision`, `routes`, `judge_passes`.
  - `draco_revision(...)` — the fingerprint. Input tuple is **identical to today's**
    `REVISION` hash (definition.py:52–70), with `protocol_revision`, `judge_passes`,
    and `judge_seeds` as per-variant parameters. For canonical inputs (5, `five-pass-reproduction-v1`)
    it MUST produce the current revision — this keeps the canonical routes frozen.
  - `build_draco_protocol(routes, judge_passes, case_count)` — the current `_build(case_count)`
    body, parameterized on `judge_passes` (verdict calls `range(1, judge_passes+1)`,
    `evidence_{1..N}` struct fields).
  - `draco_benchmark(...)` factory returning `(exam, benchmark)`; `benchmark.install`
    is a closure that calls `install_runtime(node, assets / "draco", exam)`.

- **`draco/definition.py`** becomes the boards module:
  - `DRACO = draco_benchmark(id="draco", judge_passes=5, protocol_revision="five-pass-reproduction-v1", ...)` — all constants and the revision hash remain as today; exports stay backwards-compatible for the tests that import `REVISION`, routes, etc.
  - `DRACO_3PASS = draco_benchmark(id="draco-3pass", judge_passes=3, protocol_revision="three-pass-reproduction-v1", ...)`.

- **`draco/runtime.py`** — `install(node, root, exam)`:
  - `_criterion_evaluation` expected fields use `exam.judge_passes`.
  - The aggregate closure passes `judge_passes=exam.judge_passes`, `benchmark_revision=exam.revision`.
  - Module-level route imports move to `exam.routes`.

- **`benchmarks/builtins.py`** — add `DRACO_3PASS` to `BUILTIN_BENCHMARKS`.

- **`benchmarks/registry.py`** — no change: it already calls `benchmark.install(node, assets_root)` per benchmark, and route validation is per protocol.

## 3. What stays untouched

- `JUDGE_MODEL`, `JUDGE_PARAMS`, `JUDGE_INSTRUCTIONS`, `DATASET*`, `EXCLUDED_DOMAINS`,
  `RETRIEVAL_POLICY_ID`, `CHECK_CRITERION`, `DRACO_CHECK`, assets, tasks, verdict binding,
  case/check records, scoring arithmetic, aggregate math.
- Canonical `draco`'s `id`, `title`, `description`, `revision`, `routes`, and behavior —
  byte-identical (the spec's frozen-revision invariant, same as `healthbench-worst30`).
- SDK: no code change. `benchmark="draco-3pass"` flows through `_engine/benchmark.py`
  as a flat id; the catalog resource and `check_surface` come from the engine's registry.
- Scoreboard: `scoreboard_seed_json` iterates the registry, so the variant appears in the
  catalogue automatically. Deployed environments sync `SCOREBOARD_SEED_BENCHMARKS` via their
  own values file — that is a platform-team deploy step, out of this unit.

## 4. File change surface

| File | Change |
|---|---|
| `apps/screamingface-engine/src/screamingface_engine/benchmarks/draco/exam.py` | NEW — factory, `Routes`, `DracoExam`, revision fingerprint, protocol builder |
| `.../draco/definition.py` | Rewrite as boards module (canonical + 3-pass); keep module-level constants for canonical compat |
| `.../draco/runtime.py` | `install(node, root, exam)`; judge-pass and route reads from the exam |
| `.../draco/aggregate.py` | Parameterize `judge_passes`/`revision` (keep module-level canonical defaults) |
| `.../benchmarks/builtins.py` | Add `DRACO_3PASS` |
| `apps/screamingface-engine/tests/unit/test_draco_3pass_definition.py` | NEW — variant tests (below) |
| `apps/screamingface-engine/tests/unit/test_draco_definition.py` | Extend: canonical revision unchanged; variant revision distinct; route set distinct |
| `apps/screamingface-engine/tests/unit/test_draco_case_evaluation_route.py` | Update `install(...)` call signature (single call site) |
| `draco-cache-seed/RUNBOOK.md` | Document the 3-pass variant as the fully-cached path; update "half a re-run" paragraph |
| `.claude/task-board.local.md` / `docs/tasks/` mirror, `docs/work/` ledger, this spec → `docs/spec/` | Process artifacts |

## 5. Test plan

Write these first (they fail on the current code):

1. **Canonical revision is frozen** — `DRACO.revision` equals today's value and is pinned in
   the test (like `healthbench-worst30`); the 3-pass revision differs.
2. **Protocol shape** — `DRACO_3PASS.protocol(1)` renders exactly 3 verdict calls and
   `evidence_1..evidence_3`; canonical still renders 5 (existing tests keep passing).
3. **Route separation** — every 3-pass route is under `/benchmarks/draco-3pass/{rev}/` and
   no route collides with canonical's.
4. **Registry install** — `BenchmarkRegistry((DRACO, DRACO_3PASS)).install(node, assets_root)`
   validates both protocols against their own declared routes (the existing
   "references uninstalled endpoint(s)" check must pass for both).
5. **End-to-end cache shape** — the criterion evaluation handler accepts exactly 3
   evidence records for the 3-pass exam and 5 for canonical; aggregate with
   `judge_passes=3` produces a CandidateResult with `n_runs == 3` and the same
   verdict-coverage arithmetic as `judge_passes=5` at reduced `N`.
6. **Registry/lineup** — `BUILTIN_BENCHMARKS` now contains both; `test_draco_lineup_declared.py`
   (if it iterates builtins) still green.
7. **Compatibility** — existing `test_draco_*` files stay green with zero functional change
   (they exercise the canonical paths).

## 6. Docs

- `draco-cache-seed/RUNBOOK.md`: add a section — "To replay the archive fully from cache,
  run `benchmark="draco-3pass"`; canonical `draco` still grades 5 times and pays rounds 4–5."
- `draco-cache-seed/manifest.json`: no change (it describes the archive as-is). Optional:
  note the variant that consumes it.

## 7. Out of scope

- Regenerating the seed with real rounds 4–5 (option C) — canonical 5-pass remains paid.
- Scoreboard registration on deployed environments (platform values-file sync).
- Changing canonical `draco` in any way.

## 8. Open items for approval

1. **Variant id**: `draco-3pass` (recommended) vs `draco-cache-seed`.
2. **Title/description**: propose title "DRACO 3-Pass (cache-seeded)" and a description
   that states 3 judge passes and the fully-cached replay property.
3. **Linear ticket**: owner creates `OME-N` in Linear (no Linear MCP here); I mirror it in
   `docs/tasks/` and the work ledger.
4. Approval of this spec in plain words before I draft the plan and write code.
