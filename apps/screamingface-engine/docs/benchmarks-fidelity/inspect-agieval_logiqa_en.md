---
benchmark: inspect-agieval_logiqa_en
origin: inspect_evals
verdict: unverified
verdict_reason: "One possibly-score-changing deviation is open, and it is undeclared. The inspect_evals Task fixes the Candidate's sampling with GenerateConfig(temperature=0, max_tokens=2048, top_p=1), the paper's own settings. Our importer never carries a Task's GenerateConfig, so the Candidate's own model parameters decide. Only a real Candidate run can bound this. Every deterministic dimension matches inspect_evals: the Case Digest and the 651 keys and options; the prompt bytes on 651 of 651 Cases; the per-Case marks on 11,718 of 11,718 answer sheets; and the roll-up to four decimals on 8 of 8 vectors. Closing D1 would still give comparable-to-inspect at best. inspect_evals itself differs from the authors' harness by an unbounded amount (prompt and answer extraction), and on 12 Cases it keys a different option text than the harness does."
audited: 2026-11-09
audited_at: 48fe0ec5b
fingerprint:
  benchmark: 884951da7ad9e2e1
  harness_url: https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0/src/inspect_evals/agieval
references:
  paper: https://arxiv.org/abs/2304.06364v2
  original_harness: https://github.com/ruixiangcui/AGIEval/tree/84ab72d94318290aad2e4ec820d535a95a1f7552
  inspect_evals: https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0
  inspect_ai: https://github.com/UKGovernmentBEIS/inspect_ai/tree/v0.3.263
parity_test: none
parity_test_reason: "No test puts the reference's marks beside ours for this Benchmark. The closest pins are tests/unit/inspect/test_inspect_task_replay_benchmarks.py::test_a_multiple_choice_benchmark_grades_with_no_network[agieval_logiqa_en] (two canned replies through our grader), ::test_declaration_is_sealed_licensed_and_registered[agieval_logiqa_en], ::test_every_judge_less_benchmark_grades_with_no_network[agieval_logiqa_en], and tests/unit/inspect/test_benchmark_fingerprints.py (the fingerprint). All passed in this audit. The parity evidence is the answer sheets below: 11,718 marks per examiner."
---

# AGIEval LogiQA (English) — Fidelity Record

## Verdict

**`unverified`.** Our headline is plain accuracy over the 651 LogiQA-en questions of [AGIEval](https://github.com/ruixiangcui/AGIEval/tree/84ab72d94318290aad2e4ec820d535a95a1f7552). Our examiner and [inspect_evals v0.20.0 `agie_logiqa_en`](https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0/src/inspect_evals/agieval) mark identically on every deterministic check:

- the Case Digest and Case Set Digest equal the pins;
- the prompt bytes are identical on 651 of 651 Cases;
- the marks are identical on 11,718 of 11,718 answer sheets;
- the roll-up equals to four decimals on 8 of 8 vectors.

The two examiners differ in **sampling**. inspect_evals' Task pins `GenerateConfig(temperature=0, max_tokens=2048, top_p=1)`, citing the paper's §4.2.4. Our importer never carries a Task's `GenerateConfig`, so the Candidate's own model parameters decide. Nothing on the row declares this (D1). The difference is `possibly-score-changing` with bound `unknown` until a paid run, and that open deviation forces `unverified`:

`sum of bounds against inspect_evals = 0/651 (deterministic dimensions) + unknown (D1) → unverified`.

Closing D1 would still allow only **`comparable-to-inspect`**, never `comparable-to-paper`. inspect_evals and the authors' harness are different examiners, and the gap is `unbounded` (Upstream notes):

- **Prompt.** inspect_evals uses a zero-shot `ANSWER: $LETTER` template. The harness uses `Among A through D, the answer is`, sends a second-stage re-ask, and has a few-shot variant.
- **Answer extraction.** inspect_evals reads an `ANSWER:` line. The harness takes the first capital letter A–F, or matches `answer is .*?([A-G])`.
- **Keys.** On 12 Cases the two key different option texts. The bound on that alone is `12/651 = 0.0184 > 0.005`.

The row's Frontier Score (0.639) is the paper's **few-shot** GPT-4 number (Table 3). The setting inspect_evals serves by default is zero-shot, and the paper reports GPT-4 at 49.3 for it (Table 2).

## Dimensions

| dimension | status | severity | bound | evidence |
|---|---|---|---|---|
| dataset | match | — | — | **Replay with the pins enforced (Checks 6):** `task built: samples 651`, `captured 651 Cases`, `case_digest computed 7c80ae3e pinned 7c80ae3e equal True`, `case_set_digest computed e143841e pinned e143841e equal True`. The pins are at `apps/screamingface-engine/src/screamingface_engine_inspect/prepare.py:295-302`, with the source URL at commit `84ab72d9` at `:290-294`.<br>**Same file as inspect_evals:** inspect_evals reads `ROOT_URL` at the same revision (`inspect_evals:agieval/utils.py:32`, `:34`) through `load_json_dataset` (`:167-172`). It applies no shuffle and no few-shot split at the default `fewshot=None` (`:175-181`).<br>**Against the raw file in the cloned harness at the same commit:** `raw rows 651`; `sample ids == raw-derived ids in order: True unique ids 651`; `target != raw label: [] count 0`; `choices != raw options minus '(X)': [] count 0`. Keys: `{'A': 132, 'B': 159, 'C': 179, 'D': 181}`. Every row has 4 options and a passage.<br>**Versions:** the v1 and v1_1 files are byte-identical (`cmp` → `SAME`), and `fork:README.md:11` says "AGIEval-en datasets remain the same as Verison 1.0".<br>**Rows malformed in the raw file:** 28 rows are malformed. inspect_evals' `o[3:]` mishandles them (`inspect_evals:agieval/utils.py:95`), and our capture reproduces that byte for byte. This is a difference between inspect_evals and the harness (Upstream notes), not between us and inspect_evals. |
| prompt | match | — | — | **Two independent renders, 651 of 651 Cases (Checks 6, 7):**<br>(1) inspect_ai's own `prompt()` (`inspect_ai:solver/_multiple_choice.py:71-79`), given the eval's `MULTIPLE_CHOICE_TEMPLATE_EN` (`inspect_evals:agieval/utils.py:68-76`) formatted as `agieval_solver` does (`:147-155`): `Cases whose Candidate input bytes != inspect_ai prompt() with the eval's template: [] count 0`. Rebuilt from the raw jsonl with `record_to_sample`'s rules (`:84-109`): `[] count 0`.<br>(2) The Task's own `multiple_choice` solver, run with a stub `generate`: `solver-rendered prompt != our Case input on Cases: [] count 0`.<br>**Shape:** there is no system message. Every input begins with the template's two newlines (`inputs starting with two newlines then the instruction: 651 of 651`), because the empty `{fewshot_string}` is substituted after `.strip()`. sha256 of all inputs `b2faa75661f96047`. Case 1 was printed in full (`… where LETTER is one of A,B,C,D. \n\n<passage>\n\n<question>\n\nA) …\nD) …`). |
| answer extraction | match | — | — | **Ours replays inspect's own functions:** `apps/screamingface-engine/src/screamingface_engine_inspect/scorer_adapter.py:651` calls `set_choices_based_on_generated_response(state, parse_answers(state, multiple_correct))` with `multiple_correct False` (Checks 2). That is the pair inspect's solver calls (`inspect_ai:solver/_multiple_choice.py:82-152`: strict regex `:98-102`, lenient regex `:107-110`, last match wins `:115`, uppercased `:121`).<br>**Answer sheets (Checks 7):** 18 replies × 651 Cases = 11,718 marks per examiner. `ours vs inspect — sheets with any differing mark: none (identical on every mark)`. |
| metric | match | — | — | **Same scorer:** the row's scorer is `inspect_ai.scorer:choice` (`apps/screamingface-engine/src/screamingface_engine_inspect/benchmarks.py:2581`), resolved by `_scorer_factory` (`benchmarks.py:8483-8492`). That is the Task's own `choice()` (`inspect_evals:agieval/utils.py:189`; `inspect_ai:scorer/_choice.py:60-61`, `:107`).<br>**Same mark values:** `C`/`I` map to 1.0/0.0 on both sides (`scorer_adapter.py:111`; `inspect_ai:scorer/_metric.py:279`).<br>**Evidence:** the 11,718 marks above, identical. `test_a_multiple_choice_benchmark_grades_with_no_network[agieval_logiqa_en]` passed (Checks 8). |
| roll-up | match | — | — | **Ours:** `_accuracy`, `round(sum(values) / len(cases), 4)` (`apps/screamingface-engine/src/screamingface_engine_inspect/single_shot.py:1275`, `:1303`). `whole_run_metric_factory None`.<br>**inspect:** `accuracy()`, `total / float(len(scores))` (`inspect_ai:scorer/_metrics/accuracy.py:15`, `:34-37`).<br>**Harness:** `correct_numer / len(result_for_human)` (`fork:post_process_and_evaluation.py:117-118`).<br>**Eight vectors through all three (Checks 9):** all-1 → 1.0000; all-0 → 0.0000; alternating → 0.5008; every-3rd → 0.3333; sheet `ANSWER_gold` → 1.0000; sheet `ANSWER_wrong` → 0.0000; sheet `ANSWER_paren_gold` → 0.0000; key-is-A → 0.2028. `equal4 True` on all eight.<br>**Note (no mark changes):** under `failure_policy="withhold"` (`benchmarks.py:2576`), a Case with no grade counts 0. |
| judge | not applicable | — | — | `judge None` (Checks 2). The Task's scorer is `choice()` for every non-cloze subset (`inspect_evals:agieval/utils.py:189`). The model-graded `expression_equivalence` applies only to `math`. The paper grades by accuracy, with no model (§4.2.3). |
| sampling | deviation | possibly-score-changing | unknown | D1. **Ours:** `declaration BenchmarkDeclaration(failure_policy='withhold', interaction='single_shot', difficulty='hard', attempts=1)`. No sampling knob on the row: `awk` for `NAMED DEVIATION\|params\|max_tokens\|temperature\|top_p\|dropped_scorers\|excluded\|attempts` over `benchmarks.py:2558-2618` printed nothing (Checks 3). The importer does not read `task.config`. Capture accepts and ignores the generation config (`apps/screamingface-engine/src/screamingface_engine_inspect/capture.py:247`), and the house rule says "an eval that pins `temperature=0` (worldsense) is run at the Candidate's temperature" (`apps/screamingface-engine/docs/importing-an-inspect-eval.md:106`).<br>**inspect_evals:** `config=GenerateConfig(temperature=0, max_tokens=2048, top_p=1)` (`inspect_evals:agieval/utils.py:196`, commented "from source paper 4.2.4"). The built Task printed `max_tokens=2048 top_p=1.0 temperature=0.0` (Checks 6).<br>**Attempts:** 1 = 1. |

## Deviations

### D1 — the Task's pinned sampling (temperature 0, 2,048 tokens, top_p 1) is not carried

- **Undeclared (a finding).** The row has no `# NAMED DEVIATION` line, and its description does not mention sampling (`apps/screamingface-engine/src/screamingface_engine_inspect/benchmarks.py:2558-2618`, Checks 3). The importer doc describes the behaviour for every imported Benchmark (`apps/screamingface-engine/docs/importing-an-inspect-eval.md:106`), but the row does not link to it, so under the agent's rule it does not count as a declaration. The row-level `params` tuples in this file are `JudgeSpec` params. A Benchmark row has no Candidate sampling knob.
- **Where.**
  - Theirs: `inspect_evals:agieval/utils.py:196`, merged into every model call by inspect's Task runner.
  - Ours: `apps/screamingface-engine/src/screamingface_engine_inspect/capture.py:247`. The generation config is ignored at Case Preparation, and the Candidate's own model parameters reach the provider.
- **What differs.**
  - Under `inspect eval`, every Candidate call is greedy (temperature 0, top_p 1) and capped at 2,048 output tokens. A reply that runs past the cap loses its trailing `ANSWER:` line and is marked 0.
  - Under ours, the Candidate's own Model Config decides. That is often a provider default temperature of 1.0, and a different cap or none.
  - The paper fixes the same three values (§4.2.4: "temperature of zero … maximum number of tokens for generation to 2048 … top p to 1").
- **Severity / bound.** `possibly-score-changing`, `unknown`. How far sampling moves the marks depends on the Candidate and cannot be computed without a run.

## Checks run

- [x] **Read-only on the checkout.** `git status --porcelain` before: `?? docs/work/2026-11-09-fidelity-sweep.md`. After: the same line. That is the sweep ledger the calling session writes concurrently, as expected; this audit created nothing in the checkout. Every file of this audit lived under `$SCRATCH=/private/tmp/claude-501/…/scratchpad/audit-inspect-agieval_logiqa_en-zRDU`, deleted at the end with `shutil.rmtree`. The only file written outside it is this report, in the scratchpad's `reports/` folder.
- [x] **No keys, no model.** `env -i PATH="$PATH" HOME="$SCRATCH" UV_CACHE_DIR="$SCRATCH/uv-cache" env | grep -iE 'key|token|secret'` → empty (`grep exit=1`). Every command that ran third-party code ran under that prefix: the clone, the arXiv fetches, and every `uv run --isolated --extra inspect` call, whose packages were installed fresh into `$SCRATCH/uv-cache`. The harness's grading code (`src/post_process.py`, `src/evaluation.py`, `src/math_equivalence.py`) was copied verbatim into a scratch package. Its `dataset_loader` was stubbed to the dataset-name lists (`fork:src/dataset_loader.py:13-22`) because the real module imports `pandas` and calls `tiktoken.encoding_for_model`, which downloads. The harness was not installed: its runner needs Azure OpenAI credentials (`fork:openai_api.py:15-36`), and its grading needs only `re`. No model, gateway or provider was called. The harness's second-stage re-ask is a model call, so it was not run (see Upstream notes).
- [x] **Harness over paper.** The paper's Figure 2 describes the zero-shot prompt in one step. The harness's chat-mode zero-shot is two calls, with the second-stage suffix `Therefore, among A through E, the answer is` (`fork:src/dataset_loader.py:250-277`, `:255`; `fork:run_prediction.py:166`, `:190-198`). The harness is the reference, and the difference is in Upstream notes.
- [x] **Declared is not a finding.** No declared deviation exists for this row (no `# NAMED DEVIATION`, `dropped_scorers` or `excluded_sample_ids`; `excluded_sample_ids=None` in the spec). D1 is undeclared, so it is a finding.
- [x] **Every cell has evidence.** Each `match` names its command and output lines below.
- [x] **Every `file:line` is copied from command output.**
  - Ours: from `/usr/bin/grep -n`, `sed -n` and `awk` on the checkout files (Checks 3).
  - `inspect_evals:` and `inspect_ai:`: from `cat -n`, `/usr/bin/grep -n` and `sed -n` on copies of the installed v0.20.0 / v0.3.263 files (Checks 4).
  - `fork:`: from `cat -n` and `/usr/bin/grep -n` on the clone at `84ab72d9` (Checks 5).
- [ ] **A verdict never claims more than its evidence.** No dimension is `unchecked`. D1 is an open `possibly-score-changing` deviation, so the verdict is `unverified`, by rule.
- No `ours` override was set.

1. **Checkout and scratch.** `git rev-parse --short HEAD` → `48fe0ec5b`; `git status --porcelain` → the one ledger line above. `SCRATCH=$(mktemp -d …/audit-inspect-agieval_logiqa_en-XXXX)`, then the key check above.
2. **Our side**, from the Engine root: `uv run --isolated --extra inspect python scripts/ours.py`. Output:
   - `fingerprint 884951da7ad9e2e1`, `origin inspect_evals`
   - `harness_url https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0/src/inspect_evals/agieval`, `paper_url https://arxiv.org/abs/2304.06364`
   - `params None`, `declaration BenchmarkDeclaration(failure_policy='withhold', interaction='single_shot', difficulty='hard', attempts=1)`
   - `judge None`, `multiple_correct False`, `inverted_grade False`, `whole_run_metric_factory None`, `epoch_reducer_factory None`, `named_scores ()`
   - `TaskReplayCasesSpec(task='inspect_evals.agieval.agieval:agie_logiqa_en', case_count=651, case_digest='7c80ae3e…', task_args=None, …, excluded_sample_ids=None, license='mit', source_pins={}, shuffle_seed=None, choice_shuffle_seed=None, …, case_set_digest='e143841e…')`
   - `inspect_evals 0.20.0 inspect_ai 0.3.263`
3. **Our citations:**
   - `/usr/bin/grep -n "agieval_logiqa_en" src/screamingface_engine_inspect/benchmarks.py src/screamingface_engine_inspect/prepare.py` → `benchmarks.py:2559`, `prepare.py:290`, `:295`.
   - `sed -n '2550,2620p' benchmarks.py` gives the row `2558-2618`: description `2562-2570`, `failure_policy` `2576`, `scorer` `2581`, `harness_url` `2600`, the Frontier Score comment `2608` ("few-shot (5-shot, no CoT) (Table 3)"), `score=0.639` `2611`.
   - `sed -n '180,305p' prepare.py` gives the spec `295-302`.
   - `awk 'NR>=2558 && NR<=2618 && /NAMED DEVIATION|params|max_tokens|temperature|top_p|dropped_scorers|excluded|attempts/' benchmarks.py` → no line.
   - Single-line greps: `grep -n "def _scorer_factory"` → `8483`; `grep -n "set_choices_based_on_generated_response(state, parse_answers" scorer_adapter.py` → `651`; `_INSPECT_LETTER_SCORE_VALUES` → `111`; `grep -n "def _accuracy"` → `1275`; `"score=round(sum(values) / len(cases), 4)"` → `1303`; `grep -n "generation config are accepted and ignored" capture.py` → `247`; ``grep -n "| `config`" docs/importing-an-inspect-eval.md`` → `106`.
   - Recorded replies: `grep -rl "agieval\|logiqa" tests/unit/inspect/goldens tests/fixtures` → none. `tests/unit/inspect/goldens` does not exist, so the answer sheets carry no recorded real replies.
4. **Installed reference** copied into scratch (`shutil.copytree(Path(inspect_evals.__file__).parent/'agieval', …)` plus the inspect_ai helpers) and read with `cat -n`:
   - `inspect_evals:agieval/agieval.py:162-178`: `agie_logiqa_en`, `cot=False`, `fewshot=None`.
   - `inspect_evals:agieval/utils.py`: revision `32`; `ROOT_URL` `34`; template `68-76`; `CHOICE_PREFIX` `78`; `record_to_sample` `84-109` (`o[3:]` `95`); `multiple_choice(template=…)` `155`; `load_json_dataset` `167-172`; few-shot split `175-181`; `choice()` `189`; `GenerateConfig(temperature=0, max_tokens=2048, top_p=1)` `196`.
   - `inspect_evals:agieval/eval.yaml:12-13`: `agie_logiqa_en`, `dataset_samples: 651`.
   - `inspect_evals:agieval/README.md`: `:63` (`--temperature 0.5` option example), `:205-211` (Scoring); no evaluation-report section.
   - `inspect_ai:solver/_multiple_choice.py`: `71-79`, `82-152`, `242`, `247`.
   - `inspect_ai:scorer/_choice.py:60-61`, `:107`; `inspect_ai:scorer/_metrics/accuracy.py:15-37`; `inspect_ai:scorer/_metric.py:279`.
5. **Original harness.** `env -i … git clone --quiet https://github.com/ruixiangcui/AGIEval harness` → HEAD `84ab72d94318290aad2e4ec820d535a95a1f7552 2024-06-13 "update AGIEval scripts for ver. 1.1."`, which is also the dataset pin.
   - `git log -- src/post_process.py src/dataset_loader.py …` → `84ab72d`, `05c8189`, `54887c3` (2023-05-25), `9a11e1e` (2023-04-25, "limit parsed QA answer to A-F"), `666a489`.
   - `git diff 54887c3 84ab72d -- src/post_process.py` changes only `remove_few_shot_prefix` and `parse_math_answer`. The single-answer MCQ path used for LogiQA-en (`find_first_capital_letter`, `answer is .*?([A-G])`) is unchanged since before the paper's v2 (Sep 2023).
   - `git show 54887c3:openai_api.py` → the same `system` message and `temperature=0`.
   - `cat -n`:
     - `fork:src/dataset_loader.py`: English QA list `14-15`; `convert_zero_shot` `25-35` (`Among A through {}, the answer is` `35`); `combine_prompt` `87-142` (`The answer is therefore` `118`); `Here are the answers for the problems in the exam.` `147`; `convert_few_shot` `190-217`; `generate_second_stage_input` `250-277` (`:255`).
     - `fork:src/post_process.py`: `try_parse_few_shot_qa_single_answer` `29-43` (`:33`); `parse_few_shot_qa_single_answer` `64-69`; `find_first_capital_letter` `72-78`; `post_process` `179-196` (`zero-shot` branch `187-189`, few-shot `194`).
     - `fork:src/evaluation.py:17-25` (`prediction == label`); `fork:post_process_and_evaluation.py:117-118`.
     - `fork:openai_api.py`: `88` (`You are a helpful AI assistant.`), `101` (`temperature=0`), no `max_tokens` on the chat call (`98-103`).
     - `fork:run_prediction.py`: `166`, `190-198`.
   - `cmp data/v1/logiqa-en.jsonl data/v1_1/logiqa-en.jsonl` → `SAME`.
6. **Render and dataset**, ours vs inspect: `env -i … uv run --isolated --extra inspect python -I scripts/render.py "$SCRATCH"`. The script follows `_replay_in_this_process` (`task_replay.py:414-448`) minus the prefetch: `CaseSourceRecorder(cache_root).install(fetch_pins_of(spec))`, the eval's task function, then `captured_case_records(task, spec)`, with `XDG_CACHE_HOME` in scratch and `INSPECT_EVAL_MODEL=none/none`. Output:
   - `task built: samples 651 in 0.9 s`, `captured 651 Cases in 0.2 s`
   - `case_digest … equal True`, `case_set_digest … equal True`
   - `task.config … max_tokens=2048 top_p=1.0 temperature=0.0 …`
   - `Cases whose Candidate input bytes != inspect_ai prompt() with the eval's template: [] count 0`
   - `raw rows 651 labels {'A': 132, 'B': 159, 'C': 179, 'D': 181}`
   - `raw rows with passage None 0 with answer field set 0 option counts {4: 651}`
   - `rows with an option not prefixed (X): 28 [3, 6, 8, 11, 16, 109, 115, 141, 145, 146, 148, 149, 151, 173, 186, 193, 194, 195, 196, 198, 199, 200, 201, 202, 353, 525, 545, 595]`
   - `sample ids == raw-derived ids in order: True unique ids 651`
   - `target != raw label: [] count 0`, `choices != raw options minus '(X)': [] count 0`
   - `Cases whose input != prompt rebuilt from the raw file: [] count 0`
   - `inputs starting with two newlines then the instruction: 651 of 651`
   - `sha256 of all inputs: b2faa75661f96047`

   Then `python3 -I scripts/options.py "$SCRATCH"` (stdlib only, on the raw file):
   - `rows with an option written 'X text' (inspect's o[3:] drops the first character of the text): 5 [(3, 4), (6, 4), (8, 4), (353, 1), (595, 4)]`
   - `rows whose written letters are out of order: 19`, all `ACBD`
   - `of those, rows where the keyed option sits at a different position than its letter: 12`: Cases `109, 115, 141, 146, 148, 149, 173, 186, 193, 195, 199, 200`
   - `rows with an option carrying no letter prefix: 4 [(11, …'A? Many'…), (16, …'C? Geng'…), (525, ['When the', …]), (545, [… 'Storehou' …])]`

   A spot check on the Case material: Case 193 is served `A) F / B) L / C) G / D) M` with target `B` (keyed text `L`); the harness's keyed option is `(B)G`. Case 109: ours keys `No.3 valve and No.5 valve.`, the harness `(B)No.2 valve and No.3 valve.`.
7. **Answer sheets:** `env -i … uv run --isolated --extra inspect python -I scripts/sheets.py "$SCRATCH"`. 18 replies per Case: gold as `ANSWER: X`, `ANSWER: X.`, CoT then `ANSWER: X`, `ANSWER: (X)`, `Answer: X`, `**ANSWER: X**`, `ANSWER: x`, `The answer is X.`, `The answer is therefore X`, bare `X`, `(X)`, ` X` (the zero-shot continuation), `Based on the passage, ANSWER: X`; the next letter as `ANSWER: wrong`; empty; `ANSWER: gold` then `ANSWER: wrong`; `The answer is (gold). Option wrong was tempting.`; and a reply with no answer.

   The examiners:
   - **Ours:** `inspect_grade_case(ib.scorer_factory(), multiple_correct=False)` on a `GradeRequest` with the Case input and the Grading Material.
   - **inspect:** the Task's own `multiple_choice` solver with a stub `generate` returning the reply, then the Task's `choice()`, then `value_to_float()`.
   - **Harness:** `post_process("logiqa-en", "zero-shot" | "few-shot", reply)` then `evaluate_single_sample`, applied to the reply as if it were the final-stage output.

   Results:
   - `cases 651 sheets per case 18 marks per examiner 11718`
   - `solver-rendered prompt != our Case input on Cases: [] count 0`
   - `ours vs inspect — sheets with any differing mark: none (identical on every mark)`
   - inspect vs harness, both settings alike:
     - **disagree 651/651:** `The answer is X.`, `The answer is therefore X`, bare `X`, `(X)`, ` X`, `The answer is (gold). …` (harness 1, inspect 0); CoT then `ANSWER: X` (inspect 1, harness 0: the first capital A–F in the reasoning is the wrong letter).
     - **disagree 519, agree 132** on `ANSWER: X` and its variants: the harness reads the `A` of `ANSWER` and is right only on the 132 Cases keyed A. The same 132 split shows on `ANSWER: wrong` and on two `ANSWER:` lines.
     - **disagree 492, agree 159** on `Based on the passage, ANSWER: X`: the harness reads the `B`.
     - **agree 651:** the empty reply and the reply with no answer.
     - **inspect 0 on all 651** for `ANSWER: (X)`: the regex admits no parenthesis.
8. **Tests:**
   - `env -i … uv run --isolated --extra inspect pytest tests/unit/inspect/test_benchmark_fingerprints.py -q -p no:cacheprovider -k agieval_logiqa_en` → `1 passed, 94 deselected`.
   - `… pytest tests/unit/inspect/test_inspect_task_replay_benchmarks.py -q -p no:cacheprovider -k agieval_logiqa_en` → `3 passed, 143 deselected`: `test_declaration_is_sealed_licensed_and_registered`, `test_a_multiple_choice_benchmark_grades_with_no_network` (`:161`), `test_every_judge_less_benchmark_grades_with_no_network`.
9. **Roll-up:** `env -i … uv run --isolated --extra inspect python -I scripts/rollup.py "$SCRATCH"` → `cases 651`; `all-1 1.0000 ×3`; `all-0 0.0000 ×3`; `alternating 0.5008 ×3`; `every-3rd-correct 0.3333 ×3`; `sheet:ANSWER_gold 1.0000 ×3`; `sheet:ANSWER_wrong 0.0000 ×3`; `sheet:ANSWER_paren_gold 0.0000 ×3`; `key-is-A (132 Cases) 0.2028 ×3`; `equal4 True` on all eight.
10. **Paper:**
    - `env -i … curl -sL https://arxiv.org/abs/2304.06364` → "Submitted on 13 Apr 2023 … last revised 18 Sep 2023 (this version, v2)".
    - `curl -sL https://arxiv.org/pdf/2304.06364v2`, then `pdftotext -layout`:
      - §4.2.3: accuracy for multiple choice.
      - §4.2.4: "temperature of zero … maximum number of tokens for generation to 2048 … top p to 1"; chat completion API for GPT-4.
      - Few-shot construction: "For AQuA-RAT, LogiQA and LSAT, we randomly sample five examples … from the provided training set".
      - Table 2, LogiQA (English): human Avg 86, Top 95; zero-shot GPT-4 49.3; zero-shot CoT GPT-4 57.8.
      - Table 3: few-shot GPT-4 63.9; few-shot CoT GPT-4 62.7.
11. **End:** `git status --porcelain` → the same single ledger line; `git rev-parse --short HEAD` → `48fe0ec5b`; `python3 -c "import shutil, sys; shutil.rmtree(sys.argv[1])" "$SCRATCH"`.

## Recommended paid runs

- **D1: our sampling vs inspect_evals' pinned sampling, on all 651 Cases.**
  - **Arms.** Use one non-reasoning Model that accepts `temperature` and `top_p`; reasoning models refuse them, and that refusal is itself the D1 situation. Arm A is the Model as a Candidate with Model Config `temperature=0, top_p=1, max_tokens=2048` (the Task's `GenerateConfig`). Arm B is the same Model at the Model Config a researcher would submit by default. Grade both arms with our scorer, which is byte-equal to inspect's (Checks 7).
  - **Reading the result.** Report `|acc_A − acc_B|`, and the count of Cases whose reply in Arm B was cut at 2,048 tokens or later. One sitting of 651 Cases has a sampling standard error near 0.02 at a provider-default temperature. A single Arm B cannot show a difference below 0.005, so plan 3 Arm B sittings and compare their mean.
  - **Cost.** About 651 × 4 short calls, zero-shot with no CoT. Prompts are about 300 tokens each.
- **Cheaper alternative (owner call, not a fix this audit makes).** Declare D1 on the row as a `# NAMED DEVIATION`, citing the house rule in `apps/screamingface-engine/docs/importing-an-inspect-eval.md:106`. That makes it declared, but it stays `possibly-score-changing`, so the verdict stays `unverified` until a run bounds it.

## Upstream notes

- **inspect_evals vs the original harness: a different examiner, `unbounded`.** [inspect_evals v0.20.0 `agieval`](https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0/src/inspect_evals/agieval) describes itself as "based on the original implementation", but it departs from [ruixiangcui/AGIEval@84ab72d9](https://github.com/ruixiangcui/AGIEval/tree/84ab72d94318290aad2e4ec820d535a95a1f7552) in two ways:
  1. **Prompt.**
     - inspect_evals uses one user turn: `Answer the following multiple choice question. … 'ANSWER: $LETTER' … one of A,B,C,D.`, the passage and question, then `A) text` lines (`inspect_evals:agieval/utils.py:68-76`).
     - The harness's zero-shot is chat mode with `system: "You are a helpful AI assistant."` (`fork:openai_api.py:88`). The user turn is `<passage>Q: <question> Answer Choices: (A)… (B)…` followed by `A: Among A through D, the answer is` (`fork:src/dataset_loader.py:25-35`). The first reply then goes back to the model with `Therefore, among A through E, the answer is` (`:250-277`; `fork:run_prediction.py:190-198`), which is a second, paid call.
     - The harness's few-shot setting (the row's Frontier Score) prepends 5 demonstrations from `data/few_shot_prompts.csv` under `Here are the answers for the problems in the exam.` (`fork:src/dataset_loader.py:87-168`).
  2. **Answer extraction.**
     - inspect_evals reads the last `ANSWER:` line.
     - The harness's zero-shot takes the first character in `{A..F}` of the reply (`fork:src/post_process.py:72-78`, `:187-189`).
     - The harness's few-shot tries `answer is .*?([A-G])`, then falls back to the first capital (`:29-43`, `:64-69`).

  On the sheets (Checks 7), a reply in the harness's own format (`The answer is B.`, ` B`) is marked right by the harness and wrong by inspect on 651/651 Cases. A reply in inspect's format (`ANSWER: B`) is marked right by inspect and, by the harness, right only on the 132 Cases keyed A, because it reads the `A` of `ANSWER`. The gap depends on how a Candidate formats its replies, so it cannot be bounded without a run: `unbounded`.
- **inspect_evals keys a different option text than the harness on 12 Cases: `score-changing`, `12/651 = 0.0184`.** In 19 rows of the raw file, the options are written in the order `(A) (C) (B) (D)`. The harness shows them as written, so the key letter names the written option (`fork:src/dataset_loader.py:33-35`; `fork:src/evaluation.py:25`). inspect_evals strips the first three characters and re-letters the options by position (`inspect_evals:agieval/utils.py:95`; `inspect_ai:solver/_multiple_choice.py:64-68`). When the key is B or C, the keyed text moves to the other letter. This affects Cases `109, 115, 141, 146, 148, 149, 173, 186, 193, 195, 199, 200`. Example: Case 193 keys `L` for us and inspect, `G` for the harness. A Candidate that picks the same option text is marked differently by the two examiners on these 12 Cases. Ours inherits this unchanged (dataset row). Reporting it to inspect_evals is an owner call.
- **inspect_evals drops characters of option text on 7 Cases: `possibly-score-changing`, at most `7/651`.** `o[3:]` assumes a `(X)` prefix.
  - Cases `3, 6, 8, 353, 595` write some options as `A text`, so they lose the text's first character (`A Chen Rui can…` → `hen Rui can…`; `A first` → `irst`).
  - Cases `525, 545` have options with no prefix, which lose three characters (`When the land…` → `n the land…`; `Storehouse B.3` → `rehouse B.3`).
  - Cases `11, 16` (`A? `, `C? `) lose nothing.

  These rows are already malformed in the harness's own prompt, so the effect on a mark is a model-behaviour question.
- **Sampling: inspect_evals matches the paper; the harness's chat path sets less.** The paper fixes temperature 0, 2,048 tokens and top_p 1 (§4.2.4). inspect_evals sets exactly those (`inspect_evals:agieval/utils.py:196`). The harness's chat call sets only `temperature=0`, with no `max_tokens` (`fork:openai_api.py:98-103`); its completion call sets `max_tokens=2000` (`:121`). The harness wins on what produced the number. inspect_evals' extra `max_tokens=2048` cap could only bind on a reply longer than that. Recorded, not counted.
- **Harness vs paper.** The paper (§4.2.2, Figure 2) presents zero-shot as one prompt. The harness's chat-mode zero-shot always makes a second call, with a suffix that says "A through E" for a 4-option subset (`fork:src/dataset_loader.py:255`). The harness wins; recorded, not counted.
- **The row's Frontier Score is the paper's few-shot number.** `benchmarks.py:2608-2611` serves 0.639 = Table 3 few-shot GPT-4. inspect_evals' default (and ours) is zero-shot without CoT, and the paper's zero-shot GPT-4 figure is 49.3 (Table 2), although that number comes from the harness's two-stage zero-shot. inspect_evals' own few-shot option (`-T fewshot=5`) draws 5 shuffled **test** rows and removes them from the set (`inspect_evals:agieval/utils.py:175-181`). The paper draws them from the **training** set. So no inspect_evals setting reproduces Table 3. Recording this is for the calling session; it changes no mark.
- **No published inspect_evals number.** The eval's README has no evaluation-report section. "Comparable to inspect" would mean comparable to a run of the pinned eval, not to a number inspect_evals printed.
