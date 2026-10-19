---
ticket: OME-1642
spec: ../spec/2026-10-19-OME-1642-all-case-denominator.md
status: proposed — waiting for owner approval to start code
date: 2026-10-19
stack: python (apps/screamingface-engine)
branch: all-case-denominator (renamed OME-1642-all-case-denominator at PR-open)
---

# Plan: count failed Cases in the score of a mean-score Benchmark

All paths are under `apps/screamingface-engine/` unless they start with `docs/`, `.claude/` or
`CONTEXT.md`. Each unit is one commit. Tests are append-only (`run_gates.py`); an existing
test changes only through the owner-approved manifest in U5.

## Row assignment (spec §5, owner-approved D1–D6)

77 imported rows (`src/screamingface_engine_inspect/benchmarks.py`) plus medxpert:

| Policy | Rows | Count |
| --- | --- | --- |
| `withhold` | gsm8k mmlu arc_easy arc_challenge commonsense_qa paws boolq mmlu_pro winogrande race_h aime24 aime25 aime26 musr wmdp_bio wmdp_chem wmdp_cyber hellaswag lab_bench_litqa lab_bench_suppqa lab_bench_dbqa lab_bench_protocolqa lab_bench_seqqa lab_bench_cloning_scenarios frontierscience onet_m6 pubmedqa agieval_lsat_ar agieval_lsat_lr agieval_lsat_rc agieval_sat_math agieval_sat_en agieval_sat_en_without_passage agieval_aqua_rat agieval_logiqa_en medqa mgsm_en bbq piqa cybermetric_80 cybermetric_500 cybermetric_2000 cybermetric_10000 sevenllm_mcq_zh sevenllm_mcq_en worldsense sad_facts_llms sad_facts_human_defaults sad_influence sad_stages_oversight sad_stages_full pre_flight bbeh uccb infinite_bench_math_find squad math musique gdpval-text frames_oracle, and medxpert | 61 |
| `coverage_declare` (D: reference rule) | draco draco-3pass | 2 |
| `coverage_declare` (E: refusal-measuring) | xstest_safe xstest_unsafe coconot_original coconot_contrast fortress_benign strong_reject air_bench cyse4_mitre_frr | 8 |
| `coverage_declare` (F: whole-run metric) | arc_agi_2 contracteval healthbench-professional ifeval simpleqa simpleqa_verified | 6 |
| `coverage_declare` (G: open) | healthbench-worst30 | 1 |

## U1 — Declare the policy on each row

- `BenchmarkSpec` (`benchmarks.py:66`): add the REQUIRED field
  `failure_policy: FailurePolicy` directly after `difficulty` (same reason as `difficulty`:
  a declared axis has no default, OME-1039 / OME-1257).
- Each of the 77 rows declares its value from the table above (mechanical edit).
- The factory (`single_shot.py:~597`) passes `spec.failure_policy` into
  `BenchmarkDeclaration` instead of the literal `"coverage_declare"`.
- Registration guards in the factory, each a `ValueError` naming the row:
  `withhold` with `whole_run_metric` set (F needs a per-metric rule); `withhold` with
  `inverted_grade=True` (E).
- medxpert: `benchmarks/medxpert/definition.py:225` → `"withhold"`.
- `definition.py:30–43` comment and the `BenchmarkDeclaration` docstring (:149–152): state the
  implemented `withhold` rule (failed Case = 0, all selected Cases in the denominator) and
  that coverage stays "graded / selected" under both policies (R2). Remove "Coverage always
  reads 100%".

New test `tests/unit/inspect/test_failure_policy_rows.py`: pins the policy of all 77 rows +
medxpert to the table; checks both guards.

**Owner decision (2026-10-19, after the first U1 run stopped):** the field and the factory
keyword stay REQUIRED. Consequences, both part of U1:

- **Construction-only test edits.** Every existing test that builds `BenchmarkSpec(...)` or
  calls the single-shot factory directly (about 101 tests in 14 files, plus 5 files with direct
  factory calls: `test_benchmark_stage_installation.py`, `test_local_task_arc_agi_2.py`,
  `test_published_revision.py`, `test_inspect_single_shot.py`, `test_whole_run_metric.py`)
  gets ONLY the added keyword `failure_policy="coverage_declare"`, so each test keeps today's
  behavior. No other edit, no assertion change. These files join the U5 manifest.
- **Row renderer.** `src/screamingface_engine_inspect/task_replay_rows.py` writes
  `failure_policy="TODO"` with a review comment, the same pattern as `difficulty="TODO"`
  (OME-1257): registration refuses the literal by name, so an unreviewed imported row cannot
  ship. The renderer's signature does not change, so no caller or test changes (verified: the
  14 importer/renderer tests pass unchanged).
- Gate runs before U5 may use `--skip-append-only`; the U5 run must pass without it.
- pyright and the full suite run in the CI environment (`uv sync --dev`). The inspect lane runs
  as CI does (`uv run --extra inspect pytest tests/unit/inspect`), followed by `uv sync --dev`
  before the next pyright run (the extra makes pyright report errors that CI does not see).

## U2 — The reduction

- `finalize_candidate_result` (`benchmarks/aggregation.py:79`): new REQUIRED keyword
  `failure_policy: FailurePolicy`. `coverage_declare` → `scorer(gradeable)` (today).
  `withhold` → `scorer(typed_cases)` (all selected Cases, failed ones included), still only
  when `gradeable` is non-empty (R4: no graded Case → `score=None`). Docstring states both.
- `BenchmarkAggregation` (`shared_grading/benchmark_aggregation.py:181`): new REQUIRED field
  `failure_policy` (keyword-only), passed to `finalize_candidate_result` (:326).
  The incremental path (`shared_grading/incremental.py:68`) passes it the same way.
  Constructors: `single_shot.py:321` (from the row) and `medxpert/aggregate.py:250`.
- `_accuracy` (`single_shot.py:1186`) and `_column_means` (:1495): the mean is over the Cases
  the scorer is given; a Case with no numeric grade adds 0 to the headline and to every
  Named Score column. A graded Case that cannot fill a column still makes that column
  unknown (OME-1268 rule unchanged). `scored_cases` and `correct` stay counts of graded Cases;
  verdict counts stay over graded Cases.
  Under `coverage_declare` the scorer only ever receives graded Cases, so its numbers do not
  change.
- medxpert `_accuracy` (`benchmarks/medxpert/aggregate.py:221`): same rule.
- `_whole_run_tally` (`single_shot.py:1217`): no change. It only runs on F rows, which stay
  `coverage_declare` (U1 guard).
- `contract.py:563–567` docstring: "the score is over the selected Cases the declared failure
  policy counts". `_candidate_outcome` logic does not change (a scored Candidate still needs
  ≥1 numeric grade; coverage formula unchanged).

New tests `tests/unit/test_withhold_reduction.py` (spec V1–V4): 3 graded (1.0, 0.5, 0.0) + 1
failed → `withhold` 0.375 / coverage 0.75, `coverage_declare` 0.5 / 0.75; Named Scores under
`withhold`; no graded Case → `None`, coverage 0, under both; a textless content-filter refusal
(`refusal_case_result`) adds 0 under `withhold`; medxpert all-Case mean.

## U3 — Revision identity

- Fingerprint (`single_shot.py:511–545`): add the conditional pin
  `*(("failure_policy=withhold",) if failure_policy == "withhold" else ())`, with a WHY comment
  in the style of the judge pins (OME-1240): the denominator is Benchmark identity; a
  `coverage_declare` row adds nothing, so its revision stays byte-identical.
- medxpert `compute_revision` (`medxpert/definition.py:72`): same conditional input.
- Each of the 61 `withhold` Benchmarks gets a new revision. The 17 others keep theirs.

New test `tests/unit/inspect/test_failure_policy_revisions.py`: the 17 `coverage_declare`
rows keep their origin/main revisions (literal table); each `withhold` row's revision differs
from its origin/main value (literal table of the old values).

## U4 — Copy

- `CONTEXT.md`: add **Failure Policy** (`withhold`: a failed Case counts 0, all selected Cases
  in the denominator; `coverage_declare`: failed Cases leave the score, coverage shows them)
  next to **Coverage** (:274); Coverage text unchanged in meaning.
- `packages/screamingface/src/screamingface/report.py:327` comment: "averaged over the Cases
  the Benchmark's failure policy counts". (Comment only; the SDK reads the score as given.)

## U5 — Existing tests that pin old values (owner-approved change)

These existing tests assert values that this change moves on purpose:

- `tests/unit/inspect/test_published_revisions.py` (`_PUBLISHED_REVISIONS`, the `withhold`
  rows' literals) and `tests/unit/inspect/test_published_revision.py` /
  `test_inspect_frontierscience_benchmark.py:187` (FrontierScience literal).
- `tests/unit/inspect/test_benchmark_declaration.py:140–175` (the `coverage_declare` table).
- `tests/unit/test_medxpert_migration_golden.py` if it pins the medxpert revision.

Each is updated to the new value only (no other edit). The U1 construction-only edits (the
`failure_policy=` keyword in direct `BenchmarkSpec`/factory calls, and the renderer test
expectation) are in the same manifest. The approval manifest
`.claude/test-change-approvals/OME-1642.json` pins each file's base and approved blob (format of
`OME-1134.json`; approver: the owner; scope "revision literals, the policy table, and the
construction-only `failure_policy=` keyword").
Any other failing existing test is a STOP: it means a behavior change outside the spec.

## U6 — Verification and ledger

1. Gates: `uv run .claude/scripts/run_gates.py screamingface-engine --base origin/main` (and
   `screamingface` for the U4 comment).
2. Design review of U1–U5 against the spec (design-reviewer).
3. V7 replay on the kind stack, after the two bug-fix workflows stop using it:
   `SF_REPO=<this worktree> ~/sf-kind/up.sh` (the gateway cache survives an upgrade), then
   replay each published FrontierScience candidate and GDPval-text `sota_cheap_synth` on the
   new revision with the Recipe path (the url4 embeds the old revision). Expected: spec §6
   values, all cache hits, $0, with the cost guard (gateway scaled to 0 on a miss). A DRACO
   replay keeps its revision and score.
4. Ledger outcome filled; spec status → implemented.

## Delegation

- U1 row edit (77 rows): `mechanic`, from the table above.
- U1 guards, U2, U3: `implementer` with this plan as the spec, one unit per run, RED test
  first; `design-reviewer` after each.
- U4, U5, U6: main loop (U5 needs blob ids after the final test edits).

## Risks

- **Leaderboard reset.** 61 Benchmarks get a new revision; their current rows stop ranking on
  the default board after deploy until the D5 re-run unit. Deploy and the re-run belong
  together.
- **Hidden aggregators.** A path that calls a scorer without `finalize_candidate_result` would
  keep the old rule. U2 makes `failure_policy` a required argument, so pyright finds every
  caller.
- **Rounding.** Scores keep `round(..., 4)` once, at the end; the V7 values must match spec §6
  exactly.
