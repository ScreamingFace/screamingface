# OME-1148 — ContractEval implementation plan

**Ticket:** [OME-1148](https://linear.app/openmined/issue/OME-1148/onboard-contracteval-as-a-deterministic-span-extraction-benchmark)
· **Spec:** `docs/spec/2026-09-09-OME-1148-contracteval-span-extraction.md`
· **Ledger:** `docs/work/2026-09-09-OME-1148-contracteval-span-extraction.md`
· **Stack:** screamingface-engine, screamingface · **Date:** 2026-09-09

The spec's facts (F-1…F-10) and decisions (D-1…D-8) are binding here and not restated. This
document is the ORDER of work and the exact files each step touches.

## Global constraints

- **RED before GREEN.** Every task writes its failing tests first. The append-only test check
  (`run_gates.py`) will reject a deletion, so tests land in the shape they keep.
- **Mirror, do not reinvent** (D-4) — by CITATION, not by vendoring. AMENDED 2026-09-09: the
  plan said `.refs/contracteval/`, but that directory is not a repo convention (I invented it)
  and nothing excludes it from ruff/pyright, so the paper's matplotlib-importing analysis script
  would fail this stack's gates. The house rule is `benchmarks/<board>/vendor/`, and ifeval uses
  it because it EXECUTES those verifiers. We execute nothing from ContractEval — we reproduce
  four small functions. So each function carries the reference's file + line range and the exact
  quoted snippet in its `WHY:` anchor, and the spec §2 holds the full transcription.
- **ruff limits** the Engine enforces: `PLR0911` max 3 returns, `PLR0912` max 7 branches,
  `C901` complexity 8, line length 100.
- **Never** edit `benchmarks/aggregation.py` or `benchmarks/contract.py` — OME-932/OME-934 own
  them (the `spine/__init__.py` INVARIANT).
- **No `spine.CaseGrader`** — it is rubric-shaped (`points: list[int]`). Use `spine.RowReader`
  only, exactly as `medxpert/aggregate.py` does.
- Gates green per stack before each commit: `uv run .claude/scripts/run_gates.py <stack>`.

## File structure

```
apps/screamingface-engine/
  src/screamingface_engine/benchmarks/contracteval/
    __init__.py  pins.py  prompts.py  answering.py  grading.py
    prepare.py  case_evaluation.py  definition.py  runtime.py  aggregate.py
  src/screamingface_engine/benchmarks/builtins.py            (edit: register)
  Dockerfile.benchmark                                        (edit only if a dep is needed)
  tests/unit/test_contracteval_grading.py
  tests/unit/test_contracteval_prepare.py
  tests/unit/test_contracteval_case_evaluation.py
  tests/unit/test_contracteval_aggregate.py
  tests/unit/test_contracteval_definition.py
  tests/unit/test_benchmark_declaration.py                    (edit: both guard tables)
packages/screamingface/
  src/screamingface/_runtime/cli.py                           (edit: _BENCHMARKS + manifest)
  scripts/build_notebooks.py                                  (edit: _contracteval_e2e)
  examples/12_contracteval.ipynb                              (generated)
```

## Task 1 — the grading core (pure, no I/O)

`answering.py`, `grading.py` + `test_contracteval_grading.py`.

- `normalized(text) -> str` — the reference's `.strip(" \n`")`, used on BOTH sides everywhere.
- `is_abstention(output) -> bool` — `"no related clause" in normalized(output).casefold()`.
  A test names F-3 explicitly: substring, **not** `startswith`, because `Evaluation.py` ignores
  `classification` on negative rows and recomputes with `in`.
- `verdict(output, gold_spans) -> bool` — empty gold → `is_abstention`; else
  `all(normalized(span) in normalized(output) for span in gold_spans)`.
- `jaccard(gold_spans, output) -> float` — reproduces `get_jaccard` byte-for-byte: remove
  `. , ; :`, casefold, `/`→space, `split(" ")` into a set (empty tokens included — the union
  inflation is the reference's behaviour and a test asserts it), over `" ".join(gold_spans)`.

Deliberately NOT here: any F1. F1 is aggregate-level (F-2).

## Task 2 — pins, prompts, prepare

`pins.py`, `prompts.py`, `prepare.py` + `test_contracteval_prepare.py`.

- `pins.py`: `DATASET = "theatticusproject/cuad-qa"`, `DATASET_REVISION =
  "d9c4ee0250ae2eb97bdb5b50773ab14ea62d0631"` (the `refs/convert/parquet` commit),
  `DATASET_SPLIT = "test"`, `PREPARER_REVISION`, `PROTOCOL_REVISION`, `MAX_TOKENS`,
  `TEMPERATURE = "0"`, `MAX_CONTEXT_TOKENS = 120_000` (D-7 guard).
- `prompts.py`: the system prompt and user template verbatim from `proprietary_model.py`
  (F-8), with the reference file+lines cited.
- `prepare.py`: load the pinned parquet (NOT the dead script loader — F-6); validate each row's
  `answers.text` is a list of strings; emit
  - public `cases.json` — `[{"id", "input"}]`, `input` = the rendered context+question
  - private `answers/<id>.json` — `{source_id, title, question, gold_spans, is_positive}`
  and return the audit summary including `case_count`, `positive_cases`, `negative_cases`.
  The context guard raises `BenchmarkAssetPreparationError` above `MAX_CONTEXT_TOKENS`.

Tests: the public/private split (no gold span may appear in `cases.json`), positive/negative
counts, the guard passing on a normal row and raising on a synthetic over-budget one.

## Task 3 — envelope, board, runtime, aggregate

`case_evaluation.py`, `definition.py`, `runtime.py`, `aggregate.py`, `builtins.py` +
`test_contracteval_case_evaluation.py`, `test_contracteval_aggregate.py`,
`test_contracteval_definition.py`, and the two guard tables in
`test_benchmark_declaration.py`.

- `case_evaluation.py`: `CHECK_SCHEMA`/`CASE_EVALUATION_SCHEMA`, `bind_case_evaluation`,
  `decode_case_evaluation` — the `attempt_1..N` object shape.
- `definition.py`: `compute_revision()` over the prompt bytes + pins; the **single-shot**
  expression — one `candidate()`, then `check`, then `case-evaluation`;
  `BenchmarkDeclaration(failure_policy="coverage_declare", interaction="single_shot")`;
  `check_surface` with `expected_check_cost="free"`.
- `runtime.py`: cases data route, `_check` (runs `verdict` + `jaccard`, emits the record),
  case-evaluation via **`attempt_records_endpoint`** — the object-shaped helper (the
  array-shaped `case_evaluation_endpoint` is for rubric `iterate` fan-outs and would fail here
  exactly as it did on MedXpertQA), and `aggregate_endpoint`.
- `aggregate.py` — the only genuinely new reducer shape we have. Each case grade carries
  `metrics: {is_positive, correct, abstained, jaccard}`; the scorer folds those into TP/TN/FP/FN
  and publishes `score = f1` with `accuracy`, `precision`, `recall`, `f2`,
  `no_related_clause_rate`, `false_no_related_clause_rate`, `jaccard_mean` (D-2, D-3, F-5).
  Guard the degenerate denominators the reference does not: `f1` and `f2` divide by
  `precision+recall`, which is 0 for an always-abstaining model — return 0.0, never raise.

Tests to write first: the confusion matrix over a mixed set with hand-computed F1/F2; laziness
divided by *selected* positives (D-3); `jaccard_mean` skipping negatives; the always-abstain
model scoring F1 0.0 rather than dividing by zero; unanswered case 0.0 and in the denominator
(D-5); errored case `None`.

## Task 4 — SDK registration and the notebook

`cli.py` (`_BENCHMARKS` + the asset-manifest entry `("cases.json", "answers")`),
`build_notebooks.py` (`_contracteval_e2e`), regenerate `examples/12_contracteval.ipynb`.
Notebook must be output-free and deterministic — that is a gated check on this stack.

## Task 5 — live pilot, then close

`limit=5` against the local stack, confirming a graded case end to end and a non-degenerate
confusion matrix. Then fill the ledger Outcome, close the `docs/tasks/` mirror, and post the
close-comment (commits · gates · ledger · deviations) on OME-1148.

## Deliberately deferred

- The `py-screamingface` landing-label split (D9). Filed as one ticket, following GDPval and
  MedXpertQA; noted so it is a choice, not an oversight.
- FS-Research and the repeats/epochs epic it needs.
- Any partial-credit grader — the protocol has none (F-1).

## Execution record (filled during implementation)

### Task 1 — grading core (2026-09-09)

Files: `contracteval/__init__.py`, `contracteval/grading.py`,
`tests/unit/test_contracteval_grading.py` (20 tests). Gates: ALL GREEN.

Deviations from the plan:

1. **No `answering.py`.** The plan split normalisation into its own module; it is one function
   (`normalized`) used only by `grading`, so splitting it would be structure for its own sake.
   Folded into `grading.py`. If the check endpoint later needs answer-time parsing that is not
   grading, that is when the module earns its existence.
2. **The reference is cited, not vendored** (see Global constraints, amended). `.refs/` was not
   a repo convention and nothing excludes it from ruff/pyright, so the paper's
   matplotlib-importing analysis script would have failed this stack's gates.

Note for Task 3: `jaccard` deliberately does NOT know that it applies to positive rows only —
that population rule (spec F-5) belongs to `aggregate.py`, and a test there must pin it.

### Tasks 2+3 — pins, prompts, prepare, board, runtime, aggregate (2026-09-09)

Forced into one landing: `test_the_family_guard_covers_every_family_preparer_package` (OME-1095)
asserts that the preparer packages on disk are exactly the families the registered boards deploy
from, so `prepare.py` cannot exist for a commit without its `builtins.py` registration. Same
merge MedXpertQA's plan made for its Tasks 3+4+5.

Files: `pins.py` `prompts.py` `prepare.py` `case_evaluation.py` `definition.py` `aggregate.py`
`runtime.py`, `builtins.py` (registration), and four test modules (12 + 8 + 13 tests).
Revision: `f9a076a10a6ae4c6`. Gates: ALL GREEN (2,654 tests).

Deviations and findings:

1. **The public/private boundary is NOT what it is on MedXpertQA.** A first-draft test asserted
   no gold span may appear in `cases.json`; that is impossible here and the test was wrong. A
   CUAD gold span is by construction a quotation FROM the contract, so its text is unavoidably
   inside the public input — that is the task. What must stay private is WHICH sentences are the
   answer, so the assertion is now that the public Case exposes exactly `{id, input}` and no
   `gold_spans`/`answer_start`/`is_positive` marker.
2. **The reference's F1 has no zero guard.** `2PR/(P+R)` raises `ZeroDivisionError` for a model
   that never scores a true positive. With 70.3% of rows negative, an always-abstaining model is
   realistic rather than hypothetical, so the reducer returns the limit 0.0. Named deviation,
   pinned by `test_an_always_abstaining_model_scores_zero_instead_of_dividing_by_zero`.
3. **`refused_case_result` no longer exists** on `main` — it is `refusal_case_result` (OME-1037),
   which also changed the semantics: a refusal WITH text is graded 0.0 and keeps its cell in the
   confusion matrix; a textless refusal fails the Case. Adopted as-is.
4. **Prior-test edit, approved by the owner.** One row added to the `expected` table in
   `test_every_builtin_board_declares_its_actual_policy`. Purely additive; the test's own note
   requires each new board to add its row. Committed with `--skip-append-only`.
5. **The pinned parquet revision was verified end to end** before being written into `pins.py`:
   `load_dataset("theatticusproject/cuad-qa", revision="d9c4ee02…", split="test")` on
   `datasets 5.0.1` returns 4,182 rows with the expected columns.
