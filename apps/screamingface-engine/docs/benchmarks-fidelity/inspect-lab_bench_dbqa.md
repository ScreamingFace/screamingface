---
benchmark: inspect-lab_bench_dbqa
origin: inspect_evals
verdict: unverified
verdict_reason: "OME-1907 (2026-11-13): grading now reads an answer inside a wrapper, such as 'ANSWER: $B' or 'ANSWER: **B**', that inspect_ai v0.3.263 reads as no answer (our Named Deviation for inspect_ai issue 5055), so a reply with a wrapper can grade differently from inspect's; only a paid run can bound how often that happens, so the rule gives unverified. Verdict before: comparable-to-inspect. "
audited: 2026-11-09
audited_at: 43d3942f6
fingerprint:
  benchmark: 21ff94a2ef9982c5
  harness_url: https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0/src/inspect_evals/lab_bench
references:
  paper: https://arxiv.org/abs/2407.10362v3
  original_harness: https://github.com/Future-House/LAB-Bench/tree/998a8e0a40cf116c80e1b0e7a805ebb5fb9fa838
  inspect_evals: https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0
  inspect_ai: https://github.com/UKGovernmentBEIS/inspect_ai/tree/v0.3.263
parity_test: none
parity_test_reason: "not written yet; this audit's answer sheets (520 Cases x 17 replies through our grade hook and inspect_evals' own solver and scorer) stand in for it"
---

# LAB-Bench DbQA — Fidelity Record

## Verdict

**`comparable-to-inspect`.** Our headline, plain accuracy over the 520 public DbQA questions, can sit beside a run of [inspect_evals' `lab_bench_dbqa` (v0.20.0)](https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0/src/inspect_evals/lab_bench), not beside the [paper's](https://arxiv.org/abs/2407.10362v3) DbQA numbers. On every dimension, ours is the same examiner as inspect_evals:

- **Cases:** Case Preparation reproduces the sealed Case Digest. Every Case is the Sample that inspect_evals' own loader produces with seed 7 at the same position.
- **Prompts:** all 520 Candidate inputs equal the prompt that inspect_evals' own solver builds, byte for byte.
- **Marks:** 8,840 pre-written replies get the same mark from our grade hook as from inspect_evals' solver and scorer.
- **Headline:** our accuracy equals inspect_evals' `accuracy()` and the harness's `compute_metrics` to four decimals on six fixed mark vectors.

The one deviation against inspect_evals is undeclared and cosmetic (D1: its `precision`, `coverage` and `stderr` are not published): `sum of bounds against inspect_evals = 0/520 = 0.0000 ≤ COMPARABLE_TOLERANCE (0.005)`.

inspect_evals itself is a different examiner from the code that produced the published number, [Future-House/LAB-Bench](https://github.com/Future-House/LAB-Bench/tree/998a8e0a40cf116c80e1b0e7a805ebb5fb9fa838). The harness asks for `[ANSWER]X[/ANSWER]` with options written `(A) …`. inspect_evals asks for `ANSWER: X` with options written `A) …`, and each extractor accepts only its own format: on the answer sheets a correct reply in the other examiner's format is marked wrong on 520/520 Cases (Upstream notes U1). With the same Cases, the same marking rule and the same pooled accuracy, how far the two headlines sit apart depends on how each model follows each format, so the inspect-vs-harness bound is `unbounded > 0.005`: `comparable-to-paper` is ruled out and `comparable-to-inspect` holds. The paired run under Recommended paid runs would size that gap; it is not needed for this verdict.

## Dimensions

| dimension | status | severity | bound | evidence |
|---|---|---|---|---|
| dataset | match | — | — | **Ours vs inspect_evals:** our row pins Hub `futurehouse/lab-bench` at `5c77cec6…` (`apps/screamingface-engine/src/screamingface_engine_inspect/prepare.py:1205`). That is inspect_evals' own pin (`inspect_evals:lab_bench/lab_bench.py:33`). Replay gives `cases 520`, and `case_digest 8584a3df… == spec: True` (Checks 3). The Hub split loaded at the pin has `rows 520 subtasks 10`. Every Hub id matches exactly one Case (`hf ids matched exactly once 520 rows never matched 0`), and each Case's keyed choice is the row's `ideal` (`gold/choice problems [] 0`) (Checks 6). **Order:** row order and option order are inspect_evals' own shuffles (`inspect_evals:lab_bench/lab_bench.py:67-68`), with seed 7 forced on both (`prepare.py:1207-1208`). inspect_evals' `hf_dataset(…, shuffle=True, seed=7, shuffle_choices=7)` gives the same order: `Cases whose choices/target != …: [] 0`, `Cases whose question != that Sample at the same position: [] 0` (Checks 7). inspect_evals itself draws unseeded each run (`inspect_ai:dataset/_sources/hf.py:131-132,264-265`), as does the harness (`fork:labbench/utils.py:146`). Our fixed order is one draw from the same process. **Ours vs harness:** Hub rows vs `fork:DbQA/*-public.jsonl`: `hub rows 520 harness rows 520`, ids on one side only `0`/`0`. Question, ideal and distractors differ on no row. Subtask labels equal the harness file stems (`0` mismatches) (Checks 9). The paper's 650 rows are in Upstream notes. |
| prompt | match | — | — | **Ours == inspect_evals:** for all 520 Cases, inspect_evals' own `lab_bench_dbqa()` solver (`multiple_choice(template=MULTIPLE_CHOICE_TEMPLATE, cot=True)`, `inspect_evals:lab_bench/lab_bench.py:152`, template `:47-58`) ran on the Hub question with the Case's option order. The prompt it built equals our Candidate input byte for byte: `Cases whose input bytes != inspect_evals solver prompt: []` (Checks 6). There is one user message and no system message (`task config … system_message=None`). **Differs from the original harness** (`fork:labbench/zero_shot.py:14-25`): rendered for Case 1, it asks for `[ANSWER]…[/ANSWER]` tags, writes options as `(A) …`, has no blank line before "Think step by step.", puts a blank line before "Options:", and spells the opt-out without a final period (`fork:labbench/utils.py:25`) (Checks 10). Upstream notes U1. |
| answer extraction | match | — | — | **Ours == inspect_evals:** our adapter replays inspect_ai's own `parse_answers` + `set_choices_based_on_generated_response` (`apps/screamingface-engine/src/screamingface_engine_inspect/scorer_adapter.py:651`). This is the same pair the solver runs after `generate` (`inspect_ai:solver/_multiple_choice.py:334`, strict regex `:99`). Answer sheets, 520 Cases × 17 replies: `ours vs inspect_evals (accuracy mark): identical 8840 differing 0` (Checks 5, 6, 11). **Differs from the original harness:** chembench's `prepare_mcq_answer` + `run_regex` read only tag formats (`fork:labbench/zero_shot.py:69-79`). `inspect_evals vs harness: identical 4680 differing 4160` across 8 of 17 sheet kinds. Each examiner on its own format agrees: gold `('C','C'): 520`, opt-out `('N','N'): 520`, wrong `('I','I'): 520` (Checks 11). Upstream notes U1. |
| metric | match | — | — | Both sides use the scorer `inspect_evals.lab_bench.lab_bench:precision_choice` with `no_answer="Insufficient information to answer the question."` (`apps/screamingface-engine/src/screamingface_engine_inspect/benchmarks.py:1554-1555` = `inspect_evals:lab_bench/lab_bench.py:153`). Correct means the selected positions equal the target (`inspect_evals:lab_bench/scorer.py:54`). Choosing the opt-out gives `NOANSWER` (`:47-49`). We map `N`→0.0 (`scorer_adapter.py:111`), as inspect_ai's `value_to_float` does (`inspect_ai:scorer/_metric.py:323-324`). Answer sheets: 8,840 of 8,840 identical (Checks 11). Harness rule: `correct = agent_output == target_output` and `sure = agent_output != unsure` (`fork:labbench/evaluator.py:86-87`). On replies in its own format it gives the same C/I/N on all 1,560 gold, opt-out and wrong sheets (Checks 11). |
| roll-up | deviation | cosmetic | 0 (D1) | **Headline equal:** six fixed vectors of 520 marks (all-C, all-I, all-N, alternating C/I, a C/I/N cycle, a mixed vector drawn from the answer sheets) went through our `_accuracy` (`apps/screamingface-engine/src/screamingface_engine_inspect/single_shot.py:1275`, `score=round(sum(values) / len(cases), 4)` at `:1303`, chosen at `:1160`), inspect_ai's `accuracy()` and the harness's `compute_metrics` (`fork:labbench/evaluator.py:127`). The results are equal to four decimals: 1.0000 / 0.0000 / 0.0000 / 0.5000 / 0.3346 / 0.2385 (Checks 12-13). The harness's `metrics_all` (`fork:labbench/evaluator.py:109`) is pooled over all 520 rows, as ours is. **Not published by us:** inspect_evals' precision and coverage (`inspect_evals:lab_bench/scorer.py:17`). See D1. |
| judge | not applicable | — | — | `imported_benchmark("lab_bench_dbqa").judge` is `None`, and the scorer calls no model. The paper parses answers "directly from the models' text completions" (§2.2, p.6). |
| sampling | match | — | — | Ours: `params None`, `declaration=BenchmarkDeclaration(… attempts=1)` (Checks 2). inspect_evals: `task config … max_tokens=None … temperature=None … seed=None`, `epochs 1` with the `mode` reducer (`inspect_evals:lab_bench/lab_bench.py:154`). Neither side fixes a decoding knob. The paper states no temperature or token cap (§2.2, Appendix prompt p.37) and averages three runs. The harness sets `max_tokens=1024` for Anthropic models only (`fork:labbench/anthropic_utils.py:14`) and passes only `model` otherwise (`fork:scripts/score_baseline.py:65`). Per the agent rule, a knob the paper leaves open counts as `match`; see Upstream notes. |

## Deviations

### D1 — we publish accuracy only; inspect_evals and the harness also report precision and coverage

- **Undeclared.** `_accuracy` publishes one score (`single_shot.py:1303`). inspect_evals' scorer declares `accuracy(), precision(), coverage(), stderr()` (`inspect_evals:lab_bench/scorer.py:17`). The harness returns all three (`fork:labbench/evaluator.py:126-131`). The paper reports all three (Fig. 3, p.7).
- **What differs.** Only the extra columns. The headline, accuracy, is inspect_evals' first metric and the paper's top panel, and it is equal to four decimals (Checks 12-13). One more point: the row's description says the opt-out "counts as no answer, not wrong". Under the accuracy headline it adds 0, exactly as a wrong answer does. It differs only for precision, which we do not publish.
- **Severity / bound.** `cosmetic`, `0`: no Case's mark and no headline changes.

## Checks run

- [x] **Read-only on the checkout.**
  - Before: `git status --porcelain` showed one pre-existing line, `?? docs/work/2026-11-09-fidelity-sweep.md`. That is the calling sweep session's ledger, not this audit's.
  - After: the same line, plus eight `?? apps/screamingface-engine/docs/benchmarks-fidelity/*.md` records (arc_agi_2, frames_oracle, inspect-frontierscience, inspect-hle, inspect-mathvista, inspect-mmlu_pro, inspect-mmmu_multiple_choice, musique). The calling session wrote those. None is this audit's.
  - HEAD stayed `43d3942f6`. Every file this audit created lived under `SCRATCH=/private/tmp/claude-501/…/scratchpad/audit-lab_bench_dbqa-92lB`. Our-side calls ran with `PYTHONDONTWRITEBYTECODE=1` (all but the first three read-only `python -c` probes).
  - The audit's `rm -rf "$SCRATCH"` was blocked by a shell-safety hook; the calling session removed the folder afterwards.
- [x] **No keys, no model.** `env -i PATH="$PATH" HOME="$SCRATCH" UV_CACHE_DIR="$SCRATCH/uv-cache" env | grep -iE 'key|token|secret'` printed nothing, `grep exit=1`. Every third-party command (both scratch venvs, the clone, the arXiv fetch) ran under `env -i PATH HOME=$SCRATCH …`, with `python -I`. Stub `generate` / `get_completion` functions stood in for every model. No model, gateway or provider was called, and no Hugging Face token was used: the dataset is not gated.
- [x] **Harness over paper.** The paper reports on the full 650-row DbQA. The public harness reads the 520 public rows. The paper's opt-out text ends with a period and the harness's does not. Both are in Upstream notes, not Deviations.
- [x] **Declared is not a finding.** Nothing on this row is declared. D1 is undeclared and cosmetic; the forced seeds are covered under dataset; the inspect-vs-harness prompt and extraction gap is inspect_evals' (Upstream notes U1), not ours.
- [x] **Every cell has evidence.** Each `match` names its command and output line, or the two source locations compared.
- [x] **Every `file:line` is copied from command output.** Commands used:
  - `grep -n` on `benchmarks.py` (`key="lab_bench_dbqa"`, `scorer=`, `scorer_kwargs=`), `prepare.py` (spec, pin, seeds), `scorer_adapter.py` (`_INSPECT_LETTER_SCORE_VALUES`, `set_choices_based_on_generated_response(state, parse_answers`) and `single_shot.py` (`def _accuracy`, `score=round`, `_accuracy$`).
  - `grep -n` on the installed `inspect_evals/lab_bench/{lab_bench,scorer,record_to_sample_helpers}.py` and `README.md`.
  - `grep -n` on `inspect_ai/solver/_multiple_choice.py`, `scorer/_metric.py`, `scorer/_metrics/accuracy.py` and `dataset/_sources/hf.py`.
  - `grep -n` on `fork:labbench/{zero_shot,utils,evaluator,anthropic_utils}.py`, `fork:scripts/score_baseline.py` and chembench `prompter.py`.
  - `sed -n 1525,1595p benchmarks.py`, `sed -n 1185,1225p prepare.py`, `sed -n 1275,1318p single_shot.py`, `sed -n 1140,1180p single_shot.py`.
- [x] **A verdict never claims more than its evidence.** `prompt`, `answer extraction`, `metric` and `roll-up` all carry evidence; no dimension is `unchecked` and no `possibly-score-changing` deviation against inspect_evals is open.
- No `ours` override was set.

1. `git status --porcelain` (pre-existing ledger line only) and `git rev-parse --short HEAD` → `43d3942f6`.
2. Our side: `uv run --isolated --extra inspect python -c "imported_benchmark('lab_bench_dbqa') …"` → `inspect_evals 0.20.0 inspect_ai 0.3.263`, `fingerprint 21ff94a2ef9982c5`, `origin 'inspect_evals'`, `harness_url '…/v0.20.0/src/inspect_evals/lab_bench'`, `paper_url 'https://arxiv.org/abs/2407.10362'`, `params None`, `declaration=BenchmarkDeclaration(failure_policy='withhold', interaction='single_shot', difficulty='hard', attempts=1)`, `judge None`. The same probe printed `whole_run_metric_factory = None` (so `_accuracy` applies), `multiple_correct = False`, `named_scores = ()`, `extra_scorer_factories = ()`, `inverted_grade = False`.
3. Replay: `PYTHONDONTWRITEBYTECODE=1 HF_HUB_DISABLE_XET=1 uv run --isolated --extra inspect python scripts/replay.py` (`replayed_cases(TASK_REPLAY_CASES["lab_bench_dbqa"])`) → `cases 520 spec case_count 520`, `case_digest 8584a3df081501f949f28a03ff5b058208985ef653a98b88d9946b24e08be17b == spec: True`. Case 1 is shown in Checks 10.
4. Harness: `env -i … git clone https://github.com/Future-House/LAB-Bench harness` → HEAD `998a8e0a40cf116c80e1b0e7a805ebb5fb9fa838 2025-09-27 "[sync] changes from internal repo"`. Then `env -i … UV_PROJECT_ENVIRONMENT=$SCRATCH/venv-harness uv sync --frozen --python 3.12` from its `uv.lock` → `exit=0`, `chembench 0.3.0`, `COT_PROMPT 'Think step by step.'`, `labbench ok`. Reference venv: `env -i … uv pip install inspect_evals==0.20.0 inspect_ai==0.3.263 datasets` → `0.20.0 0.3.263 5.1.0`. The first import failed with `ModuleNotFoundError: No module named 'acp.helpers'` because `agent-client-protocol 1.0.0` was resolved, so it was pinned to `0.12.1`, the Engine env's version (checked through `importlib.metadata`).
5. Answer sheets built (`python3 -I scripts/make_sheets.py`) → `cases 520 sheets/case 17 marks 8840`. Each Case gets:
   - the gold in seven inspect-side forms: `ANSWER: X`, CoT then `ANSWER: X`, bare `X`, `(X)`, `The answer is X.`, `ANSWER: (X)`, `answer: x`;
   - the gold in two harness forms: `[ANSWER]X[/ANSWER]`, with and without CoT;
   - both formats in one reply;
   - a wrong letter in each format;
   - the opt-out letter in each format;
   - two letters;
   - a changed-mind reply;
   - the empty reply.

   No recorded goldens exist for this row (`grep -rl lab_bench tests/unit/inspect/goldens tests/fixtures` → nothing).
6. inspect_evals reference: `env -i … HF_HUB_DISABLE_XET=1 HF_HOME=$SCRATCH/hf INSPECT_EVAL_MODEL=none/none venv-inspect/bin/python -I scripts/inspect_ref.py`. It builds `lab_bench_dbqa()` and runs its own `task.solver` with a stub `generate` and its own `task.scorer[0]` on every Case × sheet. Output: `hf revision 5c77cec6… rows 520 subtasks 10`; `inspect task samples 520 epochs 1 [mode_score]`; `task config … system_message=None max_tokens=None … temperature=None … seed=None`; `cases 520 hf ids matched exactly once 520 rows never matched 0`; `gold/choice problems [] 0`; `Cases whose input bytes != inspect_evals solver prompt: []`. 13 Cases (3, 122, 158, 169, 272, 311, 323, 338, 384, 440, 480, 503, 517) have question and option set repeated on 2 or 5 Hub rows; each was matched to a distinct id.
7. Seed order: `venv-inspect/bin/python -I scripts/seed_order.py` (`inspect_evals.utils.huggingface.hf_dataset(…, shuffle=True, seed=7, shuffle_choices=7)`) → `samples 520 cases 520`; `choices/target mismatches [] 0`; `question mismatches [] 0`; key letters `A 97, B 103, C 91, D 106, E 123`.
8. Our marks: `uv run --isolated --extra inspect python scripts/ours_marks.py` (`imported_benchmark('lab_bench_dbqa').aggregation().grade_case` on a `GradeRequest` per sheet) → `ours marks 8840`. Every `inspect_format`, `cot_then_answer`, `lower_answer` and `both_formats` sheet scored 1.0, and every other sheet 0.0.
9. Dataset vs harness: `python3 -I scripts/dataset_cmp.py hf_rows.json harness/DbQA` → `hub rows 520 harness rows 520`; `ids only on hub [] 0`; `ids only in harness [] 0`; field differences only `subtask` (the Hub carries the `-public` file stem; a recheck against the stems gave `0` mismatches); subtask sizes 40×7 and 80×3; `distractor counts [(3, 520)]`; `ideal == 'null' rows 0`. Harness history: `git log` on `labbench/{zero_shot,evaluator,utils}.py DbQA` goes back to `a767892 2024-07-13`. `git diff a767892 998a8e0` shows import moves, line wraps of the prompt's last sentences, and a `tag` field `seqqa`→`dbqa` on the 40 gene_location rows. Grading logic and Q/A fields are unchanged.
10. Harness prompt for Case 1: `venv-harness/bin/python -I scripts/harness_prompt.py` → `"The following is a multiple choice question about biology.\nPlease answer by responding with the letter of the correct answer.\nThink step by step.\n\nQuestion: Which of the following genes has a DYRK1A binding site … Database? \n\nOptions:\n(A) Insufficient information to answer the question\n(B) RAMAC\n…\n\nYou MUST include the letter of the correct answer within the following tags: [ANSWER] and [/ANSWER].\n…"`. Our Case 1: `"\nThe following is a multiple choice question about biology.\nPlease answer by responding with the letter of the correct answer.\n\nThink step by step.\n\nQuestion: … Database? \nOptions:\nA) Insufficient information to answer the question.\nB) RAMAC\n…You MUST include the letter of the correct answer within the following format: 'ANSWER: $LETTER' …"`.
11. Harness marks: `venv-harness/bin/python -I scripts/harness_marks.py` (a stubbed `BaseZeroShotAgent.run_task`, then `fork:labbench/evaluator.py:86-87`) → `harness marks 8840`; `harness raised {('paren_letter','TypeError'): 520, ('empty','TypeError'): 520}`. Compare: `python3 -I scripts/compare.py` → `ours vs inspect_evals (accuracy mark): identical 8840 differing 0`; `inspect_evals vs harness (C/I/N): identical 4680 differing 4160 by sheet {inspect_format, cot_then_answer, bare_letter, lower_answer, harness_tags, harness_tags_cot, opt_out, opt_out_tags: 520 each}`; own-format pairs `{('C','C'): 520}`, `{('N','N'): 520}`, `{('I','I'): 520}`.
12. Roll-up, references: `venv-inspect/bin/python -I scripts/rollup_ref.py vectors.json inspect` and `venv-harness/bin/python -I … harness`. Both gave identical lines: all_C 1.0000/1.0000/1.0000; all_I 0.0000/0.0000/1.0000; all_N 0.0000/0.0000/0.0000; alternating 0.5000/0.5000/1.0000; C_I_N_cycle 0.3346/0.5014/0.6673; answer_sheets_mixed 0.2385/0.2531/0.9423 (accuracy/precision/coverage).
13. Roll-up, ours: `uv run --isolated --extra inspect python scripts/rollup_ours.py vectors.json` → `score` 1.0000, 0.0000, 0.0000, 0.5000, 0.3346, 0.2385, equal to the accuracy column of step 12 on every vector.
14. Paper: `env -i … curl -sL https://arxiv.org/abs/2407.10362` lists v1–v3. v3 PDF (17 Jul 2024, 40 pp.) read with `pdftotext` and page images. Facts used:
    - Table 1 (p.5): DbQA, 10 subtasks, 650 questions.
    - §2.2 (p.6): accuracy = correct / number of questions; precision = correct / attempted.
    - Fig. 3 (p.7): accuracy, precision and coverage, error bars over three runs.
    - §B.1 (p.26): main results are on the full set (public + private). The public-vs-private difference in mean accuracy is "within five percent".
    - Fig. 7 (p.27): public-subset results, bar charts only.
    - Appendix (p.37): the harness's prompt, "Answer choices were randomly permuted", opt-out text with a final period.
15. `git status --porcelain` after: see the first checkbox. The audit's `rm -rf "$SCRATCH"` was blocked by the hook; the calling session removed the folder.

## Recommended paid runs

- **Optional paired prompt-format run (sizes U1; no judge; not needed for this verdict).** Run all 520 Cases for at least one Candidate, ideally one of the paper's models still served (`gpt-4o` or `claude-3-5-sonnet`) plus one current model. Send each Case twice, in the same option order:
  - (a) our live path: inspect_evals' prompt, graded by our hook;
  - (b) the harness's prompt, rendered by `fork:labbench/zero_shot.py`, graded by the harness's extractor and `fork:labbench/evaluator.py:86-87`.

  That is 1,040 Candidate calls per model. Report the accuracy difference (a − b) with a paired bootstrap CI.
  - Whole CI within ±0.005 → the record could be re-issued `comparable-to-paper`.
  - Otherwise the verdict stays `comparable-to-inspect`.

  Resolving a half-point gap on 520 Cases needs at most 2 net discordant Cases. Repeat the run 3 times, as the paper does, before reading the result.

## Upstream notes

### U1 — the prompt and answer format are inspect_evals', not the authors' harness (inspect_evals vs the harness; ours equals inspect_evals)

- **Not ours.** The row has no `# NAMED DEVIATION` line, no `named_deviations/` scorer, no `dropped_scorers` and no `excluded_sample_ids` (grep of `benchmarks.py:1530-1595` and `prepare.py:1190-1210`; no `lab_bench` file under `named_deviations/`). We inherit it unchanged from inspect_evals, and ours equals inspect_evals byte for byte.
- **Where.** Ours renders through inspect_evals' `MULTIPLE_CHOICE_TEMPLATE` (`inspect_evals:lab_bench/lab_bench.py:47-58`) and extracts with inspect_ai's `parse_answers` (`inspect_ai:solver/_multiple_choice.py:82,99`). The harness uses `MCQ_INSTRUCT_TEMPLATE` (`fork:labbench/zero_shot.py:14-25`) and extracts with chembench `prepare_mcq_answer` + `run_regex` (`fork:labbench/zero_shot.py:69-79`). The paper prints the harness's prompt (Appendix, p.37).
- **What differs.**
  - **Answer instruction:** `ANSWER: $LETTER` vs `[ANSWER]<answer>[/ANSWER]`.
  - **Option labels:** `A) …` vs `(A) …`.
  - **Opt-out wording:** "…the question." vs "…the question" with no final period.
  - **Line layout:** "Think step by step." is on its own paragraph in inspect_evals but follows the instruction line directly in the harness; the harness also puts a blank line before "Options:".
  - **Extraction:** each extractor reads only its own format. inspect_evals marks `[ANSWER]B[/ANSWER]` wrong, and the harness marks `ANSWER: B` wrong.
  - **Unaffected:** marking rule and pooled accuracy are identical (metric and roll-up rows).
- **Severity / bound.** `score-changing`, `unbounded` (inspect_evals vs the harness): every one of the 520 Cases is rendered differently, so any Case's mark can move, and how far the headline moves depends on the model. This is the gap that makes the verdict `comparable-to-inspect` rather than `comparable-to-paper`.
- **Evidence.** Checks 6, 10, 11. Each examiner fed its own format agrees on every gold, opt-out and wrong sheet (1,560 of 1,560). Crossed formats disagree on 4,160 of 8,840 sheets.

- **Paper vs harness: row set (harness wins).** The paper's DbQA numbers (Fig. 3, Table 2) are on 650 rows, 520 public plus 130 private (Table 1; §B.1). The released harness reads only `-public.jsonl` (`fork:labbench/utils.py:27,174`), so its number, like ours, is on the 520 public rows. The paper shows public-only results in Fig. 7 and says mean public-vs-private accuracy differs by at most 5% absolute, a figure averaged over all categories, not DbQA alone. The 130 private rows can't be audited.
- **Paper vs harness: opt-out wording.** The paper prints "Insufficient information to answer the question." with a period (p.37). The harness sends it without the period (`fork:labbench/utils.py:25`). inspect_evals uses the paper's spelling. Cosmetic.
- **Paper vs harness: subtask view.** The paper also breaks DbQA into 10 subtasks (Tables 2-4, Fig. 5). The harness's `metrics_all` pools all rows (`fork:labbench/evaluator.py:109`), and so do inspect_evals and ours. inspect_evals' README says so (`inspect_evals:lab_bench/README.md:104`). Bound 0 against the harness's pooled number. A per-subtask comparison is outside our headline.
- **inspect_evals vs harness: prompt and answer format (the comparable-to-inspect evidence).** This is U1, bound `unbounded`. Everything else agrees with the harness: Cases, gold, the opt-out rule, accuracy, and pooled roll-up. The option shuffle differs only in where the opt-out starts before a uniform permutation (`fork:labbench/utils.py:140` puts it second; `inspect_evals:lab_bench/record_to_sample_helpers.py:21` puts it last). After a uniform shuffle that changes nothing.
- **inspect_evals vs harness: sampling.** The harness fixes `max_tokens=1024` for Anthropic Candidates only (`fork:labbench/anthropic_utils.py:14`). inspect_evals and ours leave it open. A reasoning-heavy Candidate cut at 1,024 tokens would lose answers under the harness that it keeps under inspect_evals. This rides on the same paid run.
- **Harness robustness.** On an empty reply or a bare `(B)`, chembench's `prepare_mcq_answer` falls through and returns `None` (`chembench:prompter.py:857-914`, pinned 0.3.0 in the harness's `uv.lock`). `run_regex` then raises `TypeError` (1,040 of 8,840 sheets, Checks 11). `score_agent` catches only `UnanswerableError` (`fork:labbench/evaluator.py:81`), so one such reply aborts a whole harness run. inspect_evals and ours mark it `I`. This doesn't affect how the paper's number was computed, assuming no such reply occurred in their runs.
- **Harness pin.** The audit read `998a8e0a` (2025-09-27). The earliest commit, `a767892` (2024-07-13), predates paper v3. Between the two, the grading code and the DbQA question/answer fields are unchanged (Checks 9), so either commit is the reference for the published number.
