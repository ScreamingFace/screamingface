---
ticket: OME-1602
stack: screamingface-engine
status: done
started: 2026-10-16
finished: 2026-10-16
---

# OME-1602-pr4-single-turn-rows: import the single-turn packages that need rows, not mechanisms

## Intent

PR 4 of 7 for OME-1602. PRs 1 to 3 turned every silent import shape into a named refusal. This
unit adds the Benchmarks whose decisions are all made on the ticket: aime2026, simpleqa,
simpleqa_verified, fortress_benign, strong_reject and uccb by Task replay, plus two local
Tasks: infinite_bench math_find (one fixed 128k-token cut, so no Case depends on the model
name) and air_bench (the solver only answers; the judge prompt moves into the scorer, because
upstream's solver chain makes the Candidate grade itself). Owner decisions: the ticket's table
and its 2026-10-16 comment.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine_inspect/prepare.py`,
  `benchmarks.py`: one TaskReplayCasesSpec and one BenchmarkSpec per Benchmark, written by the
  importer, prose and TODOs filled by hand.
- `local_tasks/infinite_bench/` and `local_tasks/air_bench/` (new): the two local Tasks.
- `importer.py`, only if simpleqa's scorer is still unreachable by name.
- Tests: `test_benchmark_declaration.py`, `test_inspect_imported_benchmarks.py`, and the
  Task-replay and local-Task test modules the existing rows use.

## Test plan

- Every new row assembles; each declaration states its actual policy and grading family.
- Judged rows pin a declared gateway judge, matching their `screamingface/` scorer kwarg.
- infinite_bench: the same Cases under every model name; the cut is 128k tokens.
- air_bench: the solver chain makes one Candidate call and no judge call; the scorer makes
  the judge call.

## Acceptance

- 8 new Benchmarks assemble; 0 of the existing rows change.
- The named test files, ruff, and both pyright passes are green.

## Outcome

- **Actual files:** as planned, plus `test_single_turn_judged_imports.py` (new), the README of
  each local Task, and the expected-value tables in `test_benchmark_answer_rules.py`,
  `test_inspect_imported_benchmarks.py` (families, the seeded-shuffle set) and
  `test_whole_run_metric.py` (the whole-run opt-in list). `importer.py` needed no change: the
  simpleqa scorer now resolves by name.
- **Commits:** the six Task-replay rows plus infinite_bench; then air_bench on its own.
- **Gates:** the inspect unit lane plus the row-reading tests outside it (`tests/unit/inspect`,
  `test_benchmark_stage_installation`, `test_declared_models_match_aigateway`,
  `test_draft_feedback_offer_is_owner_opt_in`, `test_inspect_deployment_discovery`,
  `test_inspect_envelopes`, `test_named_scores_contract`, `test_benchmark_provenance`): 2276
  passed with the inspect extra; extra-less 204 passed, 79 skipped. ruff check and format, and
  pyright on the touched files with and without the extra: clean. All 77 rows assemble.
- **Deviations:**
  - SimpleQA's headline is the share correct, not the paper's F-score (owner decision,
    2026-10-16): the Engine publishes a run's headline as its first Named Score column, so an
    F-score headline would read as the share correct. The F-score rides beside it as a run
    metric. Found by grading the row end to end, where the F-score headline first collided
    with the tally's own `correct` count.
  - air_bench's judge also pins `reasoning_effort=none` (owner decision, 2026-10-16): with
    reasoning on, gpt-5.4's hidden reasoning counts against the 64-token cap.
  - infinite_bench and air_bench are local Tasks, so their origin is `screamingface` and their
    ids are bare keys, as the plugin's origin test requires.
  - strong_reject carries no upstream case count: eval.yaml says 324, the pinned CSV and the
    paper hold 313.
  - The fixed 128k cut never fires on Math.Find today (longest input 120,155 characters), so
    its Cases are upstream's whole inputs (41 MB in all).
- **Owner verify:** a small paid run per judged row before trusting its numbers: the SimpleQA
  pair (Gemini judge through the grader role), fortress_benign, strong_reject, uccb, and
  air_bench (whether gpt-5.4 answers HELM's format within 64 tokens at reasoning none).
