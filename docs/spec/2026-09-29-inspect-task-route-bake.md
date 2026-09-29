# Spec — bake the exact questions an inspect eval keeps after loading (question filter)

- Status: approved for build (user, 2026-09-29: "implement OME-1269").
- Component: `apps/screamingface-engine` (`screamingface_engine_inspect`).
- Ticket: OME-1269 (absorbs OME-1270). Parent epic: OME-1299.
- Ledger: `docs/work/2026-09-29-inspect-task-route-bake.md`. Plan:
  `docs/plan/2026-09-29-inspect-task-route-bake.md`.
- Scope of THIS unit: PR 1 of the ticket's 3-PR stack. It adds the mechanism and the
  `onet_m6` board (owner, 2026-09-29: "ship it with 391 questions and a named deviation from
  inspect, and add multiple_choice(cot=True) in the PR itself"). PR 2 adds the `pubmedqa`
  board. PR 3 adds the CI token and the two `xstest` boards.

## 1. Problem

Some inspect evals drop questions AFTER they load the dataset: the task function calls
`dataset.filter(...)` with a lambda. The importer probes a task with one dummy question. The
dummy has no id and no metadata, so every keep-test drops it, and inspect then raises
`ValueError: The specified dataset is empty` before the importer can read the task. The bake
also has no step that runs such a filter, so a hand-written row would bake every raw row: a
different exam from the one inspect runs.

Evidence (spike 2026-09-29, inspect-evals 0.20.0): onet_m6 435 → 397, pubmedqa 1000 → 500,
xstest safe 450 → 250, xstest unsafe 450 → 200. The question filter below reproduces the same ids and
the same input, target and choices for all four.

## 2. Requirements

- R1. A `SnapshotSpec` row can name the eval's task function (`question_filter_task`, a `"module:attr"`
  reference) and its arguments (`question_filter_task_args`). The bake then gives the task this board's
  pinned, converted, seed-ordered samples in place of its `hf_dataset` load, calls the task,
  and keeps exactly the samples the Task holds. The eval's filter runs; we never copy it.
- R2. On a question-filter row, `case_count` is the KEPT count, and the bake enforces it after the
  question-filter step. The raw-row check does not apply to that row.
- R3. The question-filter step refuses by name (never bakes) when:
  the task module has no `hf_dataset` binding; the task raises; the task calls `hf_dataset`
  a number of times other than one; or the kept samples are not an in-order subset of the
  samples we gave it (the task added, reordered or duplicated a sample).
- R4. `question_filter_task` and `question_filter_task_args` join the board's revision pins only when `question_filter_task` is set. Every
  live board keeps its revision and its baked assets byte for byte.
- R5. The importer detects a filter on the exam load. The probe's stub records each
  `filter` predicate and keeps the dummy, so the task still builds. A filter that is not
  inspect_evals' duplicate-id remover
  (`inspect_evals.utils.deps_utils:filter_duplicate_ids.<locals>.is_unique_id`) marks the
  import as filtering after load. A filter on a different load (a fewshot load) is ignored.
- R6. A question-filter import emits `question_filter_task=` and, when not empty, `question_filter_task_args=` on the
  `SnapshotSpec` row. Its case count is the kept count: the importer downloads the pinned
  rows, converts them, and runs the question-filter step.
- R7. The importer refuses by name a question-filter import that also (a) loads more than one
  dataset (the question filter hands the same samples to every load), or (b) has an upstream-seeded
  choice shuffle (upstream draws each case's choice order over all rows before the filter,
  the bake over the kept rows).
- R8. Dedupe-only tasks (wmdp_bio, wmdp_chem, wmdp_cyber, mmlu, race_h, winogrande with
  `fewshot=0`) import exactly as today, with no `question_filter_task=` field.
- R9. The importer maps `multiple_choice(cot=True)` with no custom template to inspect's own
  CoT template (`inspect_ai.solver._multiple_choice:SINGLE_ANSWER_TEMPLATE_COT`) as the row's
  `choice_template`. `cot` with `multiple_correct` gets a review flag. Answer parsing is the
  same for both templates, so grading does not change.
- R10. A row can name a deviation from inspect: `excluded_sample_ids`, sample ids the bake
  leaves out although inspect keeps them. Every id must be in the dataset, or the bake
  refuses. `case_count` is the count left after the exclusion. The ids join the revision.
- R11. The `onet_m6` board: question filter, CoT template, policy row seed 7, and six excluded
  ids. inspect keeps 397 questions; six have an answer letter past their last choice
  (upstream split the numbered choices wrongly). The board serves 391.

## 2b. PR 3 — CI token and `xstest_safe` (owner decisions 2026-09-29)

- R12. `SnapshotSpec.needs_hf_token`: a dataset behind a Hugging Face gate. The bake refuses it by
  name when no token is available (`HF_TOKEN` or a cached login), unless
  `SCREAMINGFACE_SKIP_BENCHMARKS_NEEDING_HF_TOKEN=1`, which skips the board with a warning and writes
  nothing. Not exam identity. The importer reads the gate from the Hub (`dataset_info.gated`).
- R13. `SnapshotSpec.has_answer_key=False`: a judged board whose judge grades from the
  question and the reply alone. The bake accepts an empty target for a case with no
  choices; every other board keeps refusing one. Assembly refuses the opt-in on a board with
  no judge, or whose judge prompt reads `{criterion}` (inspect's `model_graded_*` default
  prompts do). This is the mechanism OME-1371 asked for.
- R14. CI: `Dockerfile.benchmark` reads an optional BuildKit secret `hf_token` into the bake
  step's environment. Main and release builds pass the `HF_TOKEN_BENCHMARKS` repo secret
  with no skip switch; PR builds (preview, tests) pass it plus the skip switch and whether a
  token was present (so a re-run after the secret is added misses the build cache); the paid
  smoke passes it as `HF_TOKEN` to its bake step only. Local builders (kind `up.sh`, the SDK
  `justfile`) pass `HF_TOKEN` when set and otherwise skip gated boards on purpose. A skipped
  bundle holds a `SKIPPED` marker, so running its board names the reason. A test pins that
  every repo builder of the image passes the secret.
- R15. The `xstest_safe` board: question filter with `subset=safe` (250 of 450), gated, no answer
  key, judged by the house judge gpt-5.4 (a named deviation from inspect's default gpt-4o),
  with the eval's own judge prompt copied verbatim and pinned by a drift test. Its score is
  the mean grade (C=1, P=0.5, I=0), a second named deviation: upstream reports
  `refusal_rate` = 100 × (P + I) / N, lower is better. The board description gives the
  conversion from its own metrics, `100 × (1 − correct / scored cases)`; a test pins
  upstream's metric and generate config. The importer now flags any eval's own `metrics=`
  for review, since every imported board reports the mean. The unsafe
  subset waits for OME-1400 (safety-board scoring: refusing is the right answer there).

## 3. Out of scope (this unit)

- The `pubmedqa` board (PR 2) and the `xstest` boards (PR 3). The CI token and the
  `Dockerfile.benchmark` secret (PR 3).
- Post-load trims other than `.filter()` (slicing, sort then truncate). The ticket lists
  this as a known limitation.
