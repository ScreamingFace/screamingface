---
benchmark: inspect-lab_bench_litqa
origin: inspect_evals
verdict: comparable-to-inspect
verdict_reason: ""
audited: 2026-11-09
audited_at: 43d3942f6
fingerprint:
  benchmark: 109142a4408d3f4b
  harness_url: https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0/src/inspect_evals/lab_bench
references:
  paper: https://arxiv.org/abs/2407.10362v3
  original_harness: https://github.com/Future-House/LAB-Bench/tree/a767892307ad38a5f4f77cd00d30c2442aaea791
  inspect_evals: https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0
  inspect_ai: https://github.com/UKGovernmentBEIS/inspect_ai/tree/v0.3.263
parity_test: none
parity_test_reason: "No checked-in test grades LitQA2 Cases through both scorers. The two existing LitQA2 tests only pin the choice shuffle. For this record the answer sheets ran inspect_evals' own Task solver and scorer against our grade hook in scratch: 3,184 marks, all identical."
---

# LAB-Bench LitQA2 — Fidelity Record

## Verdict

**`comparable-to-inspect`.** Our LitQA2 headline is plain accuracy over the 199 public Cases. It can sit beside a number from [inspect_evals' `lab_bench_litqa` (v0.20.0)](https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0/src/inspect_evals/lab_bench). The row's frontier score, DeepSeek-V3 0.423 from [arXiv 2505.06108](https://arxiv.org/pdf/2505.06108), is described on the row as produced "via Inspect". This audit did not open that paper. It cannot sit beside the [LAB-Bench paper's](https://arxiv.org/abs/2407.10362v3) LitQA2 numbers.

Ours matches inspect_evals on every dimension that can change a mark:
- **Prompt:** every one of the 199 Case inputs equals the user message inspect_evals' own solver renders, byte for byte. inspect_evals sends no system message.
- **Marks:** 199 Cases × 16 pre-written replies = 3,184 marks, all identical to inspect_evals' own `precision_choice` scorer.
- **Headline:** our mean equals inspect's `accuracy()` to four decimals on 9 fixed mark vectors.

The one difference against inspect_evals is cosmetic (D1). We do not publish its secondary `precision`, `coverage` and `stderr` metrics. Arithmetic: `sum of bounds against inspect_evals = 0/199 = 0.0000 ≤ COMPARABLE_TOLERANCE (0.005)`.

Against the [authors' harness](https://github.com/Future-House/LAB-Bench/tree/a767892307ad38a5f4f77cd00d30c2442aaea791), inspect_evals differs beyond tolerance:
- **Prompt:** a different template that asks for a different answer format.
- **Answer extraction:** a different extractor. On every Case, a correct reply in the harness's own format is marked wrong by inspect_evals, and the reverse.
- **Dataset:** the paper's tables cover the full 248-question set (public plus private), averaged over three runs. We and inspect_evals run the 199 public questions.

The bound on the prompt and extraction difference is `unbounded` (it depends on the model), so the rule gives `comparable-to-inspect`, not `comparable-to-paper`. Details are in Upstream notes.

## Dimensions

| dimension | status | severity | bound | evidence |
|---|---|---|---|---|
| dataset | match | — | — | **Same pin as inspect_evals.** Ours: `"futurehouse/lab-bench": "5c77cec648430f30611808808861eb86f81d5eaa"` (`apps/screamingface-engine/src/screamingface_engine_inspect/prepare.py:1163`). inspect_evals: `LAB_BENCH_DATASET_REVISION = "5c77cec…"` (`inspect_evals:lab_bench/lab_bench.py:33`), split `train`, config `LitQA2` (`:70-78`, `:85`).<br>**Seal holds.** Our production replay child (`replayed_cases`) → `ours: cases 199 digest == pinned: True` (Checks 4).<br>**Rows equal the authors' files.** Every Case equals the harness's `LitQA2/litqa-v2-public.jsonl`, at HEAD and at `a767892`: `ids only ours 0 only harness 0; ideal differs on Cases []; distractor set differs on Cases []; question differs on Cases []`, and `every Case has exactly one opt-out option: True` (Checks 7).<br>**Order.** Row order and option order are inspect's own shuffles (`hf_dataset(shuffle=True, shuffle_choices=True)`, `inspect_evals:lab_bench/lab_bench.py:64-78`). The seeds `shuffle_seed=7, choice_shuffle_seed=7` (`prepare.py:1165-1166`) are forced in by `fetch_pins.py:134` (spec D1, `prepare.py:1150`). inspect_evals itself passes no seed, so each inspect run is a fresh draw from the same shuffle. Ours is the seed-7 draw. Accuracy is a plain mean, so row order cannot change it. `test_lab_bench_benchmarks_pin_a_choice_order` and `test_lab_bench_never_keys_every_case_to_one_letter[lab_bench_litqa]` pass (Checks 9). |
| prompt | match | — | — | **All 199 Cases rendered both ways.** Ours: the Case input bytes from the replay child. Theirs: inspect_evals' own `lab_bench_litqa().solver` (`multiple_choice(template=MULTIPLE_CHOICE_TEMPLATE, cot=True)`, `inspect_evals:lab_bench/lab_bench.py:152`, template `:47-58`). Theirs ran over a dataset rebuilt with inspect_evals' own `hf_dataset` plus explicit `seed=7, shuffle_choices=7`, without our seed-forcing code. The text was captured at `generate()`.<br>Result: `cases whose Candidate input bytes != inspect_evals' rendered user message (or choices/target differ): []`. Message roles at `generate()`: `[('user',)]`, so there is no system message on either side (Checks 5).<br>Rendering: `inspect_ai:solver/_multiple_choice.py:57-79` (`A) …` options, leading `\n`, curly `’` quotes, all kept). |
| answer extraction | match | — | — | **Same code, same results.** Ours replays inspect's own `parse_answers` + `set_choices_based_on_generated_response` (`apps/screamingface-engine/src/screamingface_engine_inspect/scorer_adapter.py:651`). Theirs runs them inside the solver (`inspect_ai:solver/_multiple_choice.py:334-340`, regexes `:98-110`).<br>Answer sheets, 16 replies per Case: gold as `ANSWER: X`, CoT then `ANSWER: X`, bare `X`, `(X)`, `The answer is X.`, `ANSWER: x`, `ANSWER: X.`, `[ANSWER]X[/ANSWER]`, `’ANSWER: X’`, a wrong letter, the opt-out letter, empty, two letters, wrong-then-gold, gold-then-wrong, and out of range `Z`.<br>Result: `identical 3184 differing 0`. Under both, bare `X`, `(X)`, the sentence form and the harness tags extract nothing and are marked `I` (Checks 5). No recorded goldens exist for this Benchmark (`tests/unit/inspect/goldens`, `tests/fixtures`: 0 matches). |
| metric | match | — | — | **Same scorer.** Ours: the row names inspect_evals' own `precision_choice` with `no_answer="Insufficient information to answer the question."` (`apps/screamingface-engine/src/screamingface_engine_inspect/benchmarks.py:1428-1429`). The letters map as `{"C": 1.0, "I": 0.0, "P": 0.5, "N": 0.0}` (`scorer_adapter.py:111`). Theirs: `inspect_evals:lab_bench/scorer.py:17-61`, where choosing the opt-out gives `NOANSWER` (`:39-52`). inspect's `accuracy()` reads `N` as 0.0 (`inspect_ai:scorer/_metric.py:323-324`).<br>On the 3,184 sheets every Case float is equal. Theirs per sheet: gold forms → `(1.0, 'C')` ×199, opt-out → `(0.0, 'N')` ×199, wrong → `(0.0, 'I')` ×199 (Checks 5). |
| roll-up | deviation | cosmetic | 0 | **Headline equal.** Ours: `_accuracy` = `round(sum(values) / len(cases), 4)` (`apps/screamingface-engine/src/screamingface_engine_inspect/single_shot.py:1275`, `:1303`). Theirs: `accuracy()` (`inspect_ai:scorer/_metrics/accuracy.py:29-37`), the first of `metrics=[accuracy(), precision(), coverage(), stderr()]` (`inspect_evals:lab_bench/scorer.py:17`).<br>9 vectors (all-C, all-I, all-N, alternating C/I, C/I/N cycle, and the marks from 4 answer-sheet columns): ours = inspect accuracy on each, e.g. `C/I/N cycle ours 0.3367`, inspect `(0.3367, 0.5038, 0.6683)` (Checks 6).<br>**The difference (D1):** `precision`, `coverage` and `stderr` are not published. The `withhold` failure policy (`apps/screamingface-engine/src/screamingface_engine/benchmarks/aggregation.py:106`) counts a failed Candidate call as 0. That only matters when a call fails. Under its default, inspect errors the whole run instead. No grade differs. |
| judge | not applicable | — | — | `imported_benchmark("lab_bench_litqa").judge` → `None` (Checks 3). `precision_choice` is deterministic. |
| sampling | match | — | — | **Ours:** `declaration=BenchmarkDeclaration(… interaction='single_shot', … attempts=1)` (Checks 3). No `max_tokens` or `temperature` on the row (`benchmarks.py:1404-1466`).<br>**Theirs:** `multiple_choice(… max_tokens=None)` (`inspect_ai:solver/_multiple_choice.py:247`), no `GenerateConfig` on the Task, `epochs=Epochs(1, "mode")` (`inspect_evals:lab_bench/lab_bench.py:154`). The mode of one epoch equals our single attempt.<br>**Harness and paper:** the harness fixes no temperature; only its Anthropic wrapper defaults `max_tokens` to 1024 (`fork:labbench/anthropic_utils.py:14`, HEAD). The paper states only "0-shot chain-of-thought" (§2.2). A knob left open. |

## Deviations

### D1 — inspect_evals' secondary metrics not published

- **Undeclared, cosmetic.** The row's description says "Benchmark score = plain accuracy over the cases run" (`benchmarks.py:1416`). That is not one of the declared forms (no `# NAMED DEVIATION` line, no README paragraph).
- **Where.** Ours: `single_shot.py:1275-1310` publishes the mean plus `correct` and `scored_cases`. Theirs: `inspect_evals:lab_bench/scorer.py:17` also reports `precision()` (`inspect_evals:lab_bench/metrics.py:62-90`), `coverage()` (`:93-118`) and `stderr()`.
- **What differs.** LitQA2's own measure is precision: correct out of attempted, where choosing "Insufficient information" is not an attempt. We do not compute it, though the per-Case marks we keep are enough to. The headline (accuracy) is unchanged.
- **Severity / bound.** `cosmetic`, `0`. No Case's mark and no headline digit changes (Checks 6).

## Checks run

- [x] **Read-only on the checkout.** Nothing in the checkout is from this audit. `git status --porcelain` was **not empty before**: it showed `?? docs/work/2026-11-09-fidelity-sweep.md`, the calling session's ledger. After, it showed that file plus eight `?? apps/screamingface-engine/docs/benchmarks-fidelity/*.md` records the calling session wrote during the audit. This audit wrote nothing under the checkout. Every file lived under `$SCRATCH=/private/tmp/claude-501/…/scratchpad/audit-lab_bench_litqa-7O6i`, deleted at the end (`ls` → `No such file or directory`).
- [x] **No keys, no model.** `env -i PATH="$PATH" HOME="$SCRATCH" UV_CACHE_DIR="$SCRATCH/uv-cache" env | grep -iE 'key|token|secret'` → empty output, `grep exit=1`. Every command, ours and third-party, ran under that prefix. The harness's `get_completion` was replaced by a stub returning pre-written replies, and inspect's `generate` by a stub that sets the reply. No model, gateway or provider was called. The harness's `.env` holds only `HF_DATASET_REPO` and `PUBLIC_RELEASE`.
- [x] **Harness over paper.** Their disagreement is recorded in Upstream notes, not Deviations: the paper's full 248-question set against the harness's public 199.
- [x] **Declared is not a finding.** No `# NAMED DEVIATION` line, `named_deviations/` scorer, `dropped_scorers` or `excluded_sample_ids` touches this row. D1 is undeclared and cosmetic, bound 0. The seed pin (spec D1) is not counted as a deviation, because inspect's own shuffle produces it (dataset row).
- [x] **Every cell has evidence.** Each `match` names its command and output lines or its two source locations.
- [x] **Every `file:line` copied from command output.** Commands: `grep -n` on `benchmarks.py` (`lab_bench_litqa|precision_choice|Benchmark score = plain accuracy…`), `prepare.py` (`"lab_bench_litqa": TaskReplayCasesSpec|shuffle_seed=7|choice_shuffle_seed=7|"futurehouse/lab-bench": "5c77|Fold: row and answer-option order`), `scorer_adapter.py` (`_INSPECT_LETTER_SCORE_VALUES: Mapping|set_choices_based_on_generated_response(state, parse_answers`), `single_shot.py` (`^def _accuracy|score=round(sum(values) / len(cases), 4)`), `fetch_pins.py` (`if forced.get("shuffle_choices") is True`), and `aggregation.py` (`return tuple(cases) if failure_policy == "withhold"`). `cat -n` on each inspect_evals `lab_bench/*.py` file copied from the installed package. `grep -n` on `inspect_ai:solver/_multiple_choice.py`, `scorer/_metric.py`, `scorer/_metrics/accuracy.py` and `dataset/_sources/hf.py`. `grep -n` on the harness's `labbench/{utils,zero_shot,evaluator,anthropic_utils}.py` at HEAD, and the same on a scratch checkout of `a767892`. `grep -n` on the two test files for the test names.
- [x] **A verdict never claims more than its evidence.** No dimension is `unchecked`, and no `possibly-score-changing` deviation is open.
- No `ours` override was set.

1. Checkout `…/.claude/worktrees/fidelity-sweep-pr1`: `git rev-parse --short HEAD` → `43d3942f6`. `git status --porcelain` → `?? docs/work/2026-11-09-fidelity-sweep.md`.
2. `SCRATCH=$(mktemp -d …/audit-lab_bench_litqa-XXXX)` → `…/audit-lab_bench_litqa-7O6i`. Key grep → empty (above).
3. Our side, from the Engine root: `env -i … HF_HUB_DISABLE_XET=1 uv run --isolated --extra inspect python -c "imported_benchmark('lab_bench_litqa') …"` printed:
   - `fingerprint 109142a4408d3f4b`, `origin inspect_evals`, `harness_url https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0/src/inspect_evals/lab_bench`
   - `judge None`, `declaration BenchmarkDeclaration(failure_policy='withhold', interaction='single_shot', difficulty='hard', attempts=1)`
   - `whole_run_metric_factory None`, `epoch_reducer_factory None`, `named_scores ()`, `multiple_correct False`
   - `inspect_evals 0.20.0 inspect_ai 0.3.263`

   The installed `inspect_evals/lab_bench/` and `inspect_ai/` were copied into scratch to read.
4. `env -i … uv run --isolated --extra inspect python -I $SCRATCH/scripts/audit.py`, stage 1: `replayed_cases(TASK_REPLAY_CASES["lab_bench_litqa"])`, the production replay child → `ours: cases 199 digest == pinned: True`.
5. Same script, stages 2-3: the reference built with inspect_evals' `hf_dataset(path="futurehouse/lab-bench", name="LitQA2", split="train", sample_fields=record_to_sample_base, shuffle=True, seed=7, shuffle_choices=7, revision=…)`. The solver and scorer came from `lab_bench_litqa()`, unseeded. Output:
   - `inspect: samples 199`
   - `prompt: … != …: []`, roles `[('user',)]`
   - `target letters: {'A': 37, 'B': 34, 'C': 43, 'D': 38, 'E': 33, 'F': 11, 'G': 2, 'H': 1}`, `option counts: {3: 7, 4: 20, 5: 106, 6: 40, 7: 16, 8: 4, 9: 4, 10: 1, 11: 1}`
   - Answer sheets through our `imported_benchmark(...).aggregation().grade_case(GradeRequest(...))` and through inspect_evals' solver + `precision_choice` + `value_to_float()`: `cases 199 sheets/case 16 marks 3184`, `identical 3184 differing 0 []`
6. Same script, stage 4, roll-up. Ours `single_shot._accuracy` vs inspect `accuracy()/precision()/coverage()`:

   | vector | ours | inspect accuracy / precision / coverage |
   |---|---|---|
   | all-C | 1.0000 | (1.0, 1.0, 1.0) |
   | all-I | 0.0000 | (0.0, 0.0, 1.0) |
   | all-N | 0.0000 | (0.0, 0.0, 0.0) |
   | alternating C/I | 0.5025 | (0.5025, 0.5025, 1.0) |
   | C/I/N cycle | 0.3367 | (0.3367, 0.5038, 0.6683) |
   | sheet gold_cot | 1.0000 | (1.0, 1.0, 1.0) |
   | sheet wrong | 0.0000 | (0.0, 0.0, 1.0) |
   | sheet opt_out | 0.0000 | (0.0, 0.0, 0.0) |
   | sheet gold_harness_tags | 0.0000 | (0.0, 0.0, 1.0) |

   On the first run, the stand-in objects (no `scores` field) made `_accuracy` raise a TypeError. It passed after fixing the stand-in, not our code.
7. `env -i PATH="$PATH" HOME="$SCRATCH" git clone https://github.com/Future-House/LAB-Bench harness` → HEAD `998a8e0a40cf116c80e1b0e7a805ebb5fb9fa838` (2025-09-27). Earliest commit `a767892` (2024-07-13 "mirroring repo", one day before arXiv v1 on 2024-07-14).
   - `git diff a767892 HEAD -- labbench/{zero_shot,evaluator,utils}.py`: imports moved, asserts became raises, and the template's last sentence was re-wrapped onto three lines. The grading lines are the same.
   - `python3 -I dataset_cmp.py` (stdlib only) → both commits: `rows 199; ids only ours 0 only harness 0; ideal … []; distractor set … []; question … []`.
8. Harness install: `env -i … uv venv $SCRATCH/venv --python 3.12` + `uv pip install -e . chembench==0.3.0` (the version `uv.lock` pins) → `install exit=0`. `env -i … $SCRATCH/venv/bin/python -I -u harness_side.py`, with the harness at HEAD, `random.seed(k)` per row, and `get_completion` stubbed. Output as (correct, sure) counts:

   | sheet | harness result |
   |---|---|
   | `gold_harness_tags` | (True, True) ×199 |
   | `gold_cot_tags` | (True, True) ×199 |
   | `gold_inspect_format` (`ANSWER: X`) | (False, True) ×199 |
   | `gold_inspect_cot` | (False, True) ×199 |
   | `gold_bare` | (True, True) ×199 |
   | `wrong_tags` | (False, True) ×199 |
   | `opt_out_tags` | (False, False) ×199 |
   | `opt_out_inspect_format` | (False, True) ×199 |
   | `empty` | raises TypeError ×199 |

   Harness roll-up on the same five synthetic vectors gives the same accuracy, precision and coverage as inspect to four decimals (e.g. `C/I/N cycle (0.3367, 0.5038, 0.6683)`). The rendered prompt for row 0 is quoted in Upstream notes.
9. `env -i … uv run --isolated --extra inspect pytest "tests/unit/inspect/test_inspect_task_replay_benchmarks.py::test_lab_bench_never_keys_every_case_to_one_letter[lab_bench_litqa]" "tests/unit/inspect/test_inspect_imported_benchmarks.py::test_lab_bench_benchmarks_pin_a_choice_order" -q -p no:cacheprovider` → `2 passed, 1 warning in 260.14s` (tests at `test_inspect_task_replay_benchmarks.py:643`, `test_inspect_imported_benchmarks.py:344`).
10. Paper: `env -i … curl -sL https://arxiv.org/abs/2407.10362` → v1 14 Jul 2024, v2 16 Jul, v3 17 Jul. Read `v3.pdf` via `pdftotext`:
    - Table 1: LitQA2 248 questions.
    - §1: "Main results are reported for the full set".
    - §2.2: 0-shot CoT, a decline option, accuracy and precision defined.
    - Supplement Tables 2-4: "entire dataset (both public and private splits), and averaged over three runs per model".
    - B.1: public-subset results only in Supplemental Figure 7.
11. `rm -rf "$SCRATCH"`. `git status --porcelain` → the ledger plus 8 concurrent-audit records, none from this audit. HEAD still `43d3942f6`.

## Recommended paid runs

None are needed for this verdict. One optional run would size the inspect-vs-harness gap described in Upstream notes. It would answer whether a number from us or inspect_evals can be read against the paper's public-subset Supplemental Figure 7. Run one model on the 199 public Cases twice: once with inspect_evals' template and extractor (our Benchmark as served), once with the harness's template and chembench extractor. Report the accuracy and precision difference. Total: 398 Candidate calls and no judge.

## Upstream notes

- **inspect_evals vs the authors' harness: the prompt template differs.** Score-changing, bound `unbounded`.
  - Harness: [`fork:labbench/zero_shot.py:15-24`](https://github.com/Future-House/LAB-Bench/blob/a767892307ad38a5f4f77cd00d30c2442aaea791/labbench/zero_shot.py) at `a767892`. It asks for `[ANSWER]<letter>[/ANSWER]`, puts "Think step by step." right after the instruction line, formats options as `(A) …`, and writes the opt-out as "Insufficient information to answer the question" with no full stop (`fork:labbench/utils.py:24`).
  - inspect_evals: `inspect_evals:lab_bench/lab_bench.py:47-58`. It asks for `ANSWER: $LETTER`, puts "Think step by step." in its own paragraph, formats options as `A) …`, and adds a full stop to the opt-out (`inspect_evals:lab_bench/record_to_sample_helpers.py:13`).
  - The same question rendered both ways. Harness, HEAD `998a8e0`, row 0: `…correct answer.\nThink step by step.\n\nQuestion: Acinetobacter lwoffii … antibiotics?\n\nOptions:\n(A) meropenem\n(B) Insufficient information to answer the question\n…\nYou MUST include the letter of the correct answer within the following tags: [ANSWER] and [/ANSWER].…`. Ours = inspect, Case 1: `\nThe following is … correct answer.\n\nThink step by step.\n\nQuestion: Acinetobacter lwoffii … antibiotics?\nOptions:\nA) Insufficient information to answer the question.\nB) ciproflaxin\n…\n\nYou MUST include the letter of the correct answer within the following format: 'ANSWER: $LETTER' (without quotes). …`.
  - Different words sent to the model can change its replies. No free check can bound that.
- **inspect_evals vs the authors' harness: answer extraction differs.** Score-changing, bound `unbounded`.
  - Harness: chembench 0.3.0 `prepare_mcq_answer(MCQ_REGEX_TEMPLATE_1)` then `run_regex(…, return_first=True)` (`fork:labbench/zero_shot.py:68-77`). The regex only reads `[ANSWER]`/`<ANS>`-style tags; with no tag, it falls back to a bare letter. No LLM extractor is passed.
  - On the same pre-written replies, a correct answer written in inspect's format `ANSWER: X` is marked wrong by the harness on 199/199 Cases. A correct `[ANSWER]X[/ANSWER]` is marked wrong by inspect_evals on 199/199. A bare `X` passes the harness and fails inspect_evals on 199/199. An opt-out written `ANSWER: U` is counted as an attempted wrong answer by the harness, which lowers precision (Checks 5, 8).
  - Each side marks its own requested format alike, so the gap shows up only in replies that break the format. How often that happens depends on the model.
- **Paper vs harness/public data: different Case set.**
  - The paper's main results and Supplement Tables 2-4 use all 248 LitQA2 questions (public plus a 20% private split), averaged over three runs (Table 1; §1; Tables 2-4 captions).
  - The public harness, the Hub dataset, inspect_evals and we all run the 199 public questions. The only paper figure on the same Cases is Supplemental Figure 7.
  - The harness wins, so this is recorded here, not as ours. Bound `unbounded` against the paper's tables, because 49 Cases are not visible to us.
- **Roll-up formulas agree.** Harness `compute_metrics` (`fork:labbench/evaluator.py:128-130`: accuracy = correct/total, precision = correct/sure, coverage = sure/total) equals inspect_evals' `accuracy`/`precision`/`coverage` to four decimals on five vectors (Checks 6, 8). Our row's `human_baseline=0.7` equals the paper's LitQA2 human accuracy (Table 2, 0.70). Bound 0.
- **Shuffling agrees in distribution.** The harness shuffles `[ideal, REFUSE, *distractors]` with the unseeded global `random` (`fork:labbench/utils.py:131-139`). inspect_evals shuffles `[ideal, *distractors, UNCERTAIN]` with inspect's unseeded `shuffle_choices`. Both draw a uniform random order per run. Bound 0.
- **The harness raises on an empty reply.** chembench's `prepare_mcq_answer("")` returns `None`, and `run_regex` then raises `TypeError` (199/199, Checks 8). In `Evaluator.score_agent` that exception is not `UnanswerableError`, so it escapes `asyncio.gather` and aborts the whole run. inspect_evals and we mark an empty reply `I`. This is recorded only to explain why one empty reply ends a harness run. It cannot have changed a published mark, because a published run had no empty replies.
- **Harness commits.** `references.original_harness` pins `a767892` (2024-07-13), the earliest public commit, one day before arXiv v1. The code that produced the paper's number was synced from an internal repo and is not public. The run used HEAD `998a8e0`. Its grading lines differ from `a767892` only in import paths and in re-wrapping the template's last sentence. The prompt bytes therefore differ slightly between the two harness commits. The extraction regex and the metrics are the same. `a767892` pins no chembench version; HEAD's `uv.lock` pins 0.3.0, which is what ran.
