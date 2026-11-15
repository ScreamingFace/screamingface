---
benchmark: inspect-agieval_lsat_rc
origin: inspect_evals
verdict: unverified
verdict_reason: "Our copy matches inspect_evals on dataset, prompt, answer extraction, metric and roll-up, with zero differences on all 269 Cases and 4,573 answer-sheet marks. The judge dimension does not apply. One possibly-score-changing deviation is open and undeclared: the inspect_evals Task fixes GenerateConfig(temperature=0, max_tokens=2048, top_p=1) (utils.py:196), and our importer never reads task.config, so the Candidate answers with its provider's defaults. Only a paid run can bound that, so the rule gives unverified. inspect_evals and the authors' AGIEval harness mark differently on up to 269 of 269 Cases per answer format, so comparable-to-paper is out either way. Once the sampling gap is closed or measured, the evidence supports comparable-to-inspect."
audited: 2026-11-09
audited_at: 48fe0ec5b
fingerprint:
  benchmark: 7e36f14f4aec1e60
  harness_url: https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0/src/inspect_evals/agieval
references:
  paper: https://arxiv.org/abs/2304.06364v2
  original_harness: https://github.com/ruixiangcui/AGIEval/tree/84ab72d94318290aad2e4ec820d535a95a1f7552
  inspect_evals: https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0
  inspect_ai: https://github.com/UKGovernmentBEIS/inspect_ai/tree/v0.3.263
parity_test: none
parity_test_reason: "No test runs the reference's marks beside ours for this Benchmark. The closest pins are tests/unit/inspect/test_inspect_task_replay_benchmarks.py, where test_a_multiple_choice_benchmark_grades_with_no_network[agieval_lsat_rc] puts two canned replies through our grader and test_declaration_is_sealed_licensed_and_registered[agieval_lsat_rc] checks the seal, and tests/unit/inspect/test_benchmark_fingerprints.py, which pins the fingerprint. All passed in this audit. The parity evidence is the answer sheets below: 4,573 marks per examiner."
---

# AGIEval LSAT-RC: Fidelity Record

## Verdict

**`unverified`.** Our headline is plain accuracy over the 269 LSAT reading-comprehension questions. On every grading dimension it is the same examiner as [inspect_evals v0.20.0 `agie_lsat_rc`](https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0/src/inspect_evals/agieval), which runs zero-shot, no chain of thought, inspect's `multiple_choice` template, the `choice()` scorer and the `accuracy` metric. The evidence:

- All 269 Candidate inputs equal inspect's own solver prompt byte for byte.
- Our 4,573 answer-sheet marks equal inspect's solver plus scorer on every sheet.
- The roll-up equals to four decimals on six vectors.

One difference is open. The inspect_evals Task pins `GenerateConfig(temperature=0, max_tokens=2048, top_p=1)`, and we apply none of it. Nothing on the row declares this (D1). It changes what the Candidate writes, not how a reply is marked, so it is `possibly-score-changing` with bound `unknown`, and the rule gives `unverified`. The arithmetic: `sum of enumerable bounds against inspect_evals = 0/269 = 0.0000 ≤ COMPARABLE_TOLERANCE (0.005)`, plus D1 = `unknown` → `unverified`.

The paper's numbers come from a different examiner by design, so the result can never be `comparable-to-paper`. [Zhong et al. 2023 v2](https://arxiv.org/abs/2304.06364v2) report GPT-4 at 85.9 zero-shot (Table 2) and 87.7 few-shot (Table 3). The [authors' harness](https://github.com/ruixiangcui/AGIEval/tree/84ab72d94318290aad2e4ec820d535a95a1f7552) differs from inspect_evals in three ways:

- It asks with a different prompt: `Q: … Answer Choices: … A: Among A through E, the answer is`.
- It asks in two stages: a second call appends `Therefore, among A through E, the answer is`.
- It reads the first capital A–F anywhere in the reply.

That gap is `unbounded` (Upstream notes). Once D1 is closed or measured, the evidence here supports `comparable-to-inspect`.

## Dimensions

| dimension | status | severity | bound | evidence |
|---|---|---|---|---|
| dataset | match | — | — | **Same pinned file on both sides.** Ours: the Case Source recorded at import, `https://raw.githubusercontent.com/ruixiangcui/AGIEval/84ab72d9…/data/v1_1/lsat-rc.jsonl` (comment on the spec, `apps/screamingface-engine/src/screamingface_engine_inspect/prepare.py:228`). Theirs: `AGIEVAL_DATASET_REVISION` / `ROOT_URL` (`inspect_evals:agieval/utils.py:32-34`). **In-process replay, pins enforced (Checks run 5):** `task built: samples 269`, `captured 269 Cases`, `case_digest computed 984f6070 pinned 984f6070 equal True`, `case_set_digest … equal True` (pins at `prepare.py:230-234`). **Row by row against the raw file**, read from the harness clone at `84ab72d9`, which is the same commit: `raw rows 269`. Every row agrees on target vs `label`, on `choices` vs `options[3:]`, and on the Sample input vs `passage\n\nquestion` (`inspect_evals:agieval/utils.py:84-109`), so `[]` on all three. The row order is the file's order: no shuffle on either side, and `excluded None`. There are 269 unique Sample ids. Labels: A 47, B 66, C 47, D 60, E 49. Every row has 5 options, prefixes `(A)`–`(E)`, and 40 distinct passages. |
| prompt | match | — | — | **All 269 Cases**, our capture (`apps/screamingface-engine/src/screamingface_engine_inspect/capture.py:271`) against the eval's own `task.solver` with a stub `generate`. That solver is `multiple_choice(template=…)` (`inspect_evals:agieval/utils.py:147-155`), with the template at `:68-76` and `prompt()` at `inspect_ai:solver/_multiple_choice.py:71-79`. Result: `Cases whose Candidate input bytes != inspect solver prompt: [] count 0` (Checks run 5). The only message role is `('user',)`, and `system_message None`. Every input starts with `\n\nAnswer the following` (269/269), an inspect_evals quirk that we reproduce (Upstream notes). sha256 of all inputs: `f3260a7cfe6ac5fc`. `cot=False` and `fewshot=None` are the Task's defaults (`inspect_evals:agieval/agieval.py:65-80`), and our spec passes `task args None`. |
| answer extraction | match | — | — | Ours replays inspect's own pair, `parse_answers` + `set_choices_based_on_generated_response` (`apps/screamingface-engine/src/screamingface_engine_inspect/scorer_adapter.py:651`), with `multiple_correct False` (Checks run 2). Theirs: the same functions inside `multiple_choice.solve`. The strict regex is at `inspect_ai:solver/_multiple_choice.py:98-102` and the lenient one at `:107-110`. The last match wins (`:115`), the match is uppercased (`:121`), and exactly one allowed letter is required (`:147-150`). **Answer sheets** (Checks run 6): 17 replies × 269 Cases = 4,573 marks per examiner, `ours vs inspect — sheets with any differing mark: none (identical on every mark)`. |
| metric | match | — | — | Row scorer `inspect_ai.scorer:choice` (`apps/screamingface-engine/src/screamingface_engine_inspect/benchmarks.py:2280`), which is the Task's own `choice()` (`inspect_evals:agieval/utils.py:189`; `inspect_ai:scorer/_choice.py:60-112`, `CORRECT if target_matches_choices else INCORRECT` at `:107`). Both sides map `C`/`I` to 1.0/0.0 (`scorer_adapter.py:111`). On the same 4,573 marks the two sides are identical, including the empty reply (0 on both, not a withheld Case). Correct-letter sheets score 269/269 on 7 formats on both sides, and 0/269 on the other 10. |
| roll-up | match | — | — | Ours: `_accuracy`, `round(sum(values) / len(cases), 4)` (`apps/screamingface-engine/src/screamingface_engine_inspect/single_shot.py:1275`, `:1303`, chosen at `:1160`; `whole_run_metric_factory None`). Run through the real aggregate route of a url4 node serving the 269 prepared Cases. inspect: `accuracy()` = `total / float(len(scores))` (`inspect_ai:scorer/_metrics/accuracy.py:15`, `:37`), the first metric `choice()` declares (`_choice.py:60`). Harness: `correct_numer / len(result_for_human)` (`fork:post_process_and_evaluation.py:117-118`). Six vectors through all three (Checks run 7): all-1 → 1.0000, all-0 → 0.0000, alternating → 0.5019, every-3rd → 0.3346, two harness sheet-mark vectors → 0.1747 / 0.1747. `equal4 True` on all six. inspect also reports `stderr()` and our headline does not, which is cosmetic. Under `failure_policy="withhold"` (`benchmarks.py:2275`) a Case with no grade counts as 0. The sheets have no failed Case. |
| judge | not applicable | — | — | `imported_benchmark("agieval_lsat_rc").judge` → `None` (Checks run 2). The Task's scorer for an MCQ subset is `choice()` (`inspect_evals:agieval/utils.py:189`). The model-graded `expression_equivalence` applies only to the `math` cloze task (`:189`, `:229-256`). |
| sampling | deviation | possibly-score-changing | unknown (paid run recommended) | inspect_evals fixes `config=GenerateConfig(temperature=0, max_tokens=2048, top_p=1)` on the Task (`inspect_evals:agieval/utils.py:196`), and the run printed `task config 0.0 2048 1.0` (Checks run 5). Ours sets nothing. Our declaration is `BenchmarkDeclaration(failure_policy='withhold', interaction='single_shot', difficulty='medium', attempts=1)`, with no `params` (Checks run 2). `awk` for temperature/max_tokens/params/Named Deviation over the row `benchmarks.py:2258-2316` finds nothing (Checks run 3). Capture ignores the generation config (`capture.py:247`). **Undeclared:** D1. Attempts are 1 on both sides (`epochs None`). |

## Deviations

### D1: inspect_evals' temperature 0, 2048-token cap and top_p 1 are not applied

- **Undeclared.** The row (`apps/screamingface-engine/src/screamingface_engine_inspect/benchmarks.py:2258-2316`) has no `# NAMED DEVIATION` / `Named Deviation:` line and no `params`. Its description (`:2262` onward) says nothing about generation settings. It names no `dropped_scorers` or `excluded_sample_ids` and links no README. The catalogue has a convention for exactly this case. The MATH row carries `Named Deviation: the Task's config=GenerateConfig(temperature=0.5) is not applied` (`benchmarks.py:4189`), following decision D10 (`docs/plan/2026-10-05-OME-1268-multi-score-benchmarks.md:70`, "the importer never reads `task.config`"). This row does not follow it, so this is a finding.
- **Where.** Theirs: `inspect_evals:agieval/utils.py:196`, a comment at `:195` ("from source paper 4.2.4: Implementation Details"). Ours: there is no setting. Case Preparation's stub `generate` accepts the generation config and ignores it (`apps/screamingface-engine/src/screamingface_engine_inspect/capture.py:247`), and the row carries no `params`.
- **What differs.** An `inspect eval` run asks the model for greedy decoding (temperature 0, top_p 1) and cuts the reply at 2,048 tokens. Under inspect, a reply that would put its `ANSWER:` line after token 2,048 is marked wrong. Our Candidate answers with its provider's default temperature and our run's token cap. Some reasoning models reject or ignore temperature anyway.
- **Severity / bound.** `possibly-score-changing`, `unknown`. It changes what the Candidate writes, not how a reply is marked: every mark on the sheets is identical. Only a paid run can measure the gap. The same `task.config` is shared by every `agie_*` task through `task_template`, so the AGIEval sibling rows likely carry the same gap. Those rows were not audited here.
- **Evidence.** The two source locations above. `task config 0.0 2048 1.0` (Checks run 5). The row `awk` with no hits (Checks run 3).

## Checks run

- [x] **Read-only on the checkout.** `git status --porcelain` was the same before and after: `?? docs/work/2026-11-09-fidelity-sweep.md`, the sweep ledger the calling session writes into this worktree, as expected. This audit's files lived under `$SCRATCH=/private/tmp/claude-501/…/scratchpad/audit-inspect-agieval_lsat_rc-ndpg`, which was deleted at the end with `shutil.rmtree` (`ls` → `No such file or directory`). One slip: Checks run 9 briefly redirected one `git show` to `/tmp/x`, which was deleted in the same command (`ls /tmp/x` → `No such file or directory`).
- [x] **No keys, no model.** `env -i PATH="$PATH" HOME="$SCRATCH" UV_CACHE_DIR="$SCRATCH/uv-cache" env | grep -iE 'key|token|secret'` printed nothing (`grep exit=1`). The harness clone, the arXiv fetches, `pdftotext` and both harness scripts ran under `env -i PATH="$PATH" HOME="$SCRATCH"` with system `python3 -I` (3.14.7).
  - The harness was **not installed** in its own venv. Its grading path (`src/post_process.py`, `src/evaluation.py`) is pure `re`. It imports `pandas`, `tiktoken` and `tqdm` only through `src/dataset_loader.py` for prompt building, and `tiktoken.encoding_for_model` would fetch a file at import (`fork:src/dataset_loader.py:296-297`). Those three modules were stubbed in `sys.modules`, and the harness's own files ran unmodified.
  - The our-side and inspect-side scripts ran in `uv run --isolated --extra inspect python -I` from the Engine root, with `XDG_CACHE_HOME` in scratch and `INSPECT_EVAL_MODEL=none/none`.
  - No model, gateway or provider was called.
- [x] **Harness over paper.** The paper says LSAT-RC has 260 questions (Table 1). The harness file has 269 at every commit. The harness is the reference, and the disagreement is in Upstream notes.
- [x] **Declared is not a finding.** No deviation on this row is declared. D1 is undeclared and is a finding.
- [x] **Every cell has evidence.** Each `match` names its command and output lines below.
- [x] **Every `file:line` is copied from command output.**
  - Ours: from `grep -n` / `/usr/bin/grep -n` / `sed -n` / `awk` on the worktree files (Checks run 3).
  - `inspect_evals:` / `inspect_ai:`: from `cat -n` / `sed -n` / `grep -n` on copies of the installed v0.20.0 / v0.3.263 files (Checks run 4).
  - `fork:`: from `cat -n` / `grep -n` on the clone at `84ab72d9` (Checks run 8).
- [x] **A verdict never claims more than its evidence.** No dimension is `unchecked`. D1 is `possibly-score-changing` and open, so the verdict is `unverified`.
- No `ours` override was set.

1. `git status --porcelain` → `?? docs/work/2026-11-09-fidelity-sweep.md`. `git rev-parse --short HEAD` → `48fe0ec5b`.
2. **Our side, from the Engine root:** `HF_HUB_DISABLE_XET=1 uv run --isolated --extra inspect python -c "imported_benchmark('agieval_lsat_rc') …"` printed:
   - `fingerprint 7e36f14f4aec1e60`, `origin 'inspect_evals'`
   - `harness_url 'https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0/src/inspect_evals/agieval'`, `paper_url 'https://arxiv.org/abs/2304.06364'`
   - `judge None`, `multiple_correct False`, `inverted_grade False`, `whole_run_metric_factory None`, `epoch_reducer_factory None`, `named_scores ()`
   - `declaration BenchmarkDeclaration(failure_policy='withhold', interaction='single_shot', difficulty='medium', attempts=1)`
   - `params`, `dropped_scorers` and `excluded_sample_ids` absent
   - `inspect_evals 0.20.0 inspect_ai 0.3.263`
3. **Our-side line numbers:**
   - `/usr/bin/grep -n 'key="agieval_lsat_rc"\|inspect_evals_case_count=269\|score=0.877' benchmarks.py` → `2259`, `2310`, `2316`.
   - `awk 'NR>=2258 && NR<=2316 && /scorer=|failure_policy|harness_url|…/'` → `2274` difficulty, `2275` failure_policy, `2280` scorer, `2299` harness_url, `2306` human_baseline.
   - `awk 'NR>=2258 && NR<=2316 && /[Tt]emperature|max_tokens|params=|NAMED|Named Dev|generation/'` → no line.
   - `sed -n '2305,2316p'` → frontier comment `2307-2308`, `FrontierScore` `2309-2314`.
   - `grep -n '"agieval_lsat_rc": TaskReplayCasesSpec\|case_digest="984f6070\|…' prepare.py` → `230`, `232`, `233`, `234`. The Case Source comment is at `228` (`sed -n '222,237p'`).
   - `grep -n "def _task_state\|set_choices_based_on_generated_response\|_INSPECT_LETTER_SCORE_VALUES.*=" scorer_adapter.py` → `88`, `111`, `607`, `651`.
   - `grep -n "def _accuracy\|score=round(sum(values) / len(cases), 4)" single_shot.py` → `1275`, `1303`. `awk 'NR>=1150 && NR<=1170 && /_accuracy/'` → `1160`.
   - `grep -n "generation config are accepted and ignored" capture.py` → `247`. `grep -n "Named Deviation: the Task's config=GenerateConfig" benchmarks.py` → `4189`. `grep -n "^| D10 " docs/plan/2026-10-05-OME-1268-multi-score-benchmarks.md` → `70`.
4. **The installed reference, copied to scratch** (`shutil.copytree(Path(inspect_evals.__file__).parent/'agieval', …)` plus the inspect_ai solver/scorer/metric files) and read with `cat -n`:
   - `inspect_evals:agieval/agieval.py`, 178 lines: `agie_lsat_rc` at `65-80`.
   - `inspect_evals:agieval/utils.py`, 318 lines:
     - revision and URL `32-34`
     - `MULTIPLE_CHOICE_TEMPLATE_EN` `68-76`
     - `record_to_sample` `84-109`
     - `multiple_choice(template=template_prompt)` `155`
     - `task_template` `160-199`
     - `scorer = … choice()` `189`
     - comment `195`, `config=GenerateConfig(temperature=0, max_tokens=2048, top_p=1)` `196`
   - `inspect_evals:agieval/README.md`: "based on the original implementation" `:5`, Scoring `:205-211`. The README has no results section.
   - `inspect_evals:agieval/eval.yaml`: `version: "3-A"`, `agie_lsat_rc dataset_samples: 269`.
   - `inspect_ai:solver/_multiple_choice.py`: `prompt` `71-79`, `parse_answers` `82-152`, `solve` `314-340`.
   - `inspect_ai:scorer/_choice.py:60-112` and `inspect_ai:scorer/_metrics/accuracy.py:15-37`.
5. **Render and dataset:** `HF_HUB_DISABLE_XET=1 uv run --isolated --extra inspect python -I scripts/render.py`. It calls `prefetch_case_sources`, `_resolve(spec.task)` and `CaseSourceRecorder(cache_root).install(fetch_pins_of(spec))`, builds the task, then calls `captured_case_records(task, spec)`, as `_replay_in_this_process` does (`apps/screamingface-engine/src/screamingface_engine_inspect/task_replay.py:414`). It then runs the eval's own `task.solver` on every Sample with a stub `generate`, and compares against the raw file from the harness clone. Output:
   - `task built: samples 269 in 1.2 s`
   - `task config 0.0 2048 1.0 system_message None epochs None`
   - `task args None excluded None`
   - `captured 269 Cases`
   - `case_digest computed 984f6070 pinned 984f6070 equal True`
   - `case_set_digest computed 984c74ac pinned 984c74ac equal True`
   - `Cases whose Candidate input bytes != inspect solver prompt: [] count 0`
   - `roles seen in solver messages: [('user',)]`
   - `inputs starting with two newlines: 269`
   - `sha256 of all inputs: f3260a7cfe6ac5fc`
   - `raw rows 269`
   - `target != raw label: [] | choices != raw options[3:]: [] | sample input != passage\n\nquestion: []`
   - `option prefixes ['(A)'…'(E)'] option counts [5]`
   - `passages None: 0`
   - `label dist {'A': 47, 'B': 66, 'C': 47, 'D': 60, 'E': 49}`
   - `unique sample ids 269`
   - `distinct passages 40`
   - Case 1 printed: the input opens `'\n\nAnswer the following multiple choice question. The last line of your response should be of the following format: 'ANSWER: $LETTER' (without quotes) where LETTER is one of A,B,C,D,E. \n\n…'` and the target is `D`.
6. **Answer sheets:** `HF_HUB_DISABLE_XET=1 uv run --isolated --extra inspect python -I scripts/sheets_ours_inspect.py`.
   - **Ours:** the production aggregate route (`b.aggregate_route`) of a `Url4Node` with the Benchmark installed over the 269 real prepared Cases, as `tests/unit/inspect/test_inspect_task_replay_benchmarks.py` drives it. **Inspect:** a fresh `agie_lsat_rc()` Task, its `task.solver` with a stub `generate` returning the reply, then `task.scorer[0]`, then `value_to_float()`.
   - **The 17 sheets** (G = gold, W = next letter):
     - correct letter: `ANSWER: G`, `ANSWER: G.`, CoT then `ANSWER: G`, `ANSWER: g`, `**ANSWER: G**`, `Answer: G`, `ANSWER: G,`
     - correct letter in other formats: `The answer is (G).`, `(G)`, bare `G`, the harness's zero-shot phrasing `Among A through E, the answer is G.`, the harness's few-shot phrasing `The answer is therefore G`
     - wrong or no answer: `ANSWER: W`, empty, `ANSWER: G` then a later `ANSWER: W`, `ANSWER: G, W`, a reply with no letter
   - **Result:** `marks per examiner 4573`; `ours vs inspect — sheets with any differing mark: none (identical on every mark)`. The first seven sheets score 269/269 on both sides, and the other ten score 0/269 on both. The aggregate printed `"case_count": 269, "score": 1.0, "coverage": 1.0, "failures": []` on the first sheet.
   - No recorded replies exist for this Benchmark: no `agieval` entries under `tests/unit/inspect/goldens/`.
7. **Roll-up:** `HF_HUB_DISABLE_XET=1 uv run --isolated --extra inspect python -I scripts/rollup.py`. It runs each vector through our aggregate route, inspect's `accuracy()` over `SampleScore`s, and the harness's `correct/len`:
   - `all-1 ours 1.0000 inspect 1.0000 harness 1.0000`
   - `all-0 0.0000 ×3`
   - `alternating 0.5019 ×3`
   - `every-3rd-correct 0.3346 ×3`
   - `harness zero-shot marks on ANSWER_gold 0.1747 ×3`
   - `harness zero-shot marks on harness_zero_shot_gold 0.1747 ×3`
   - `equal4 True` on all six.
8. **Original harness.** `env -i … git clone --quiet https://github.com/ruixiangcui/AGIEval harness` → HEAD `84ab72d94318290aad2e4ec820d535a95a1f7552 2024-06-13 "update AGIEval scripts for ver. 1.1."`, the same commit inspect_evals pins for the data. `git log -- src/` → `05c8189 2024-06-07`, `54887c3 2023-05-25`, `9a11e1e 2023-04-25 "limit parsed QA answer to A-F"`, `666a489 2023-04-13`. Read with `cat -n`:
   - `fork:src/dataset_loader.py`: `convert_zero_shot` `25-35` (the prompt string `33-35`), few-shot builders `87-142` and `190-217`, `generate_second_stage_input` `250-277` (`"Therefore, among A through E, the answer is"` `255`, joined `274`), tokenizer at import `296-297`.
   - `fork:src/post_process.py`: `find_first_capital_letter` `72-78`, the zero-shot branch `187-189`, few-shot `answer is .*?([A-G])` then first capital `29-43`, `64-69`.
   - `fork:src/evaluation.py:17-25` (`prediction == label`, `25`).
   - `fork:post_process_and_evaluation.py`: settings `55-60`, accuracy `117-118`.
   - `fork:openai_api.py`: `query_azure_openai_chat` `79`, system message `"You are a helpful AI assistant."` `88`, `temperature=0` `101` with no `max_tokens` on the chat call.
   - `fork:run_prediction.py:197`: the stage-2 engine is set to `"gpt-35-turbo"`.
   - `fork:README.md:77-81`: AGIEval-en zero-shot results for gpt-3.5-turbo and GPT-4o on v1.1.

   Harness sheets: `env -i PATH="$PATH" HOME="$SCRATCH" python3 -I scripts/sheets_harness.py` runs `post_process.post_process("lsat-rc", setting, reply)` then `evaluation.evaluate_single_sample`, under both `zero-shot` and `few-shot`. Against inspect, under zero-shot:
   - `ANSWER: G` agree 47 / disagree 222. The first capital is the `A` of "ANSWER", credited only on the 47 Cases keyed A. The same holds for `ANSWER: G.`, `ANSWER: g`, `**ANSWER: G**`, `Answer: G` and `ANSWER: G,`.
   - CoT then `ANSWER: G` disagree 269.
   - `The answer is (G).`, `(G)` and bare `G` disagree 269. The harness credits them and inspect does not.
   - `The answer is therefore G` disagree 269.
   - `Among A through E, the answer is G.` disagree 47.
   - `ANSWER: W` disagree 47.
   - empty and no-letter agree 269.

   Few-shot gives the same pattern, except that the two harness-format sheets disagree on 269.

   `scripts/harness_prompt.py` (same prefix) printed `harness stage-1 prompts 269 equal to ours: 0`. Case 1 harness tail: `… (E)Defense attorneys … innocence.\nA: Among A through E, the answer is`. The passage is joined to `Q:` with no separator (`…facts of the case.Q: Which one…`). Stage-2 tail: `…\n<stage-1 reply>\nTherefore, among A through E, the answer is`. Case 1 is 3,674 chars in the harness and 3,808 in ours.
9. **Data history:** `cmp data/v1/lsat-rc.jsonl data/v1_1/lsat-rc.jsonl` → `identical`. `git show 666a489:data/v1/lsat-rc.jsonl` (the 2023-04-13 upload, before the paper's v2) → `269` lines, `content-equal rows 269` against the pinned file. The bytes differ only by `4d88e6a 2023-09-28 "encode with utf8"`.
10. **Paper:** `env -i … curl https://arxiv.org/abs/2304.06364` → "last revised 18 Sep 2023 (this version, v2)". Then `curl https://arxiv.org/pdf/2304.06364v2` and `pdftotext -layout`, which gave:
    - §4.2.4 "Implementation Details": "We use a temperature of zero to generate output using greedy search and set the maximum number of tokens for generation to 2048 … top p to 1".
    - Table 1: `LSAT-RC Law-Reading 260`.
    - Table 2 (zero-shot / zero-shot CoT): `LSAT-RC 56 91 64.7 65.4 85.9 57.6 62.1 85.1`.
    - Table 3 (few-shot / few-shot CoT): `LSAT-RC 56 91 70.6 67.7 87.7 64.3 57.6 87.7`.
11. **Tests:**
    - `HF_HUB_DISABLE_XET=1 uv run --isolated --extra inspect pytest tests/unit/inspect/test_benchmark_fingerprints.py -q -p no:cacheprovider -k agieval_lsat_rc` → `1 passed, 94 deselected`.
    - `… pytest tests/unit/inspect/test_inspect_task_replay_benchmarks.py -q -p no:cacheprovider -k agieval_lsat_rc` → `3 passed, 143 deselected`. This covers `test_declaration_is_sealed_licensed_and_registered` (`:147`) and `test_a_multiple_choice_benchmark_grades_with_no_network` (`:161`).
12. **Cleanup:** `python3 -c "import shutil, sys; shutil.rmtree(sys.argv[1])" "$SCRATCH"`. Then `git status --porcelain` → `?? docs/work/2026-11-09-fidelity-sweep.md` (unchanged), and `git rev-parse --short HEAD` → `48fe0ec5b`.

## Recommended paid runs

- **D1 (sampling), one Candidate, all 269 Cases, no judge.** Run it twice through our Engine: once as today (provider defaults), and once with `temperature=0, max_tokens=2048, top_p=1` as the inspect Task fixes them. Alternatively, run `inspect eval inspect_evals/agie_lsat_rc` with the same model as the second arm. Report the accuracy gap and the count of `finish_reason="length"` replies under the 2,048 cap. A gap ≤ 0.005 closes D1 as bounded. Otherwise the row needs `params` or a declared Named Deviation. The cost is about 538 Candidate calls on roughly 3.8k-character prompts, with no judge tokens.

## Upstream notes

- **inspect_evals vs the original harness: a different examiner, `unbounded`.** [inspect_evals v0.20.0 `agieval`](https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0/src/inspect_evals/agieval) says it is "based on the original implementation" (`inspect_evals:agieval/README.md:5`). It departs from [ruixiangcui/AGIEval@84ab72d9](https://github.com/ruixiangcui/AGIEval/tree/84ab72d94318290aad2e4ec820d535a95a1f7552) on two dimensions:
  - **Prompt.** inspect's single-turn `ANSWER: $LETTER` template with `A) option` lines and `passage\n\nquestion` (`inspect_evals:agieval/utils.py:68-76`, `:85-89`). The harness's zero-shot run is two chat calls under a `"You are a helpful AI assistant."` system message (`fork:openai_api.py:88`). The first call is `passage + "Q: " + question + " Answer Choices: (A)… (B)…\nA: Among A through E, the answer is"` (`fork:src/dataset_loader.py:33-35`). The second appends the first reply and `"Therefore, among A through E, the answer is"` (`:255`, `:274`). The script sets the second-stage engine to `gpt-35-turbo` (`fork:run_prediction.py:197`). The 269 stage-1 prompts match ours on 0 of 269.
  - **Answer extraction.** inspect uses the `ANSWER:` line regex. The harness's zero-shot path takes the first capital A–F anywhere in the final reply (`fork:src/post_process.py:72-78`, `:187-189`). On the sheets (Checks run 8), a reply in inspect's own format `ANSWER: G` is credited by the harness only on the 47 Cases keyed A. The `A` of "ANSWER" is read as the answer. The paper's own phrasing `The answer is (G).` is credited by the harness and marked wrong by inspect on 269 of 269 Cases.

  How far the published number moves depends on how a Candidate formats its replies, so it cannot be bounded without a run: `unbounded`. Sampling agrees with the paper (temperature 0, top_p 1, 2,048 tokens, §4.2.4) on the inspect side, and the harness's chat call sets only `temperature=0` (`fork:openai_api.py:101`).
- **Harness vs paper.** These are recorded, not counted. The harness wins.
  - The paper's Table 1 gives LSAT-RC 260 questions, but the file has 269 rows at the paper-era upload (`666a489`, 2023-04-13) and at the pin. Those rows are content-equal (Checks run 9).
  - The paper's GPT-4 numbers (Table 2 zero-shot 85.9, Table 3 few-shot 87.7) predate v1.1. The v1.1 LSAT-RC file is identical to v1 (`cmp` → identical), so the data did not change.
- **inspect_evals' prompt opens with two newlines and has a stray space.** `MULTIPLE_CHOICE_TEMPLATE_EN` is `.strip()`ped *before* `{fewshot_string}` and `{cot_string}` are filled (`inspect_evals:agieval/utils.py:68-76`, `:147-153`). With `fewshot=None` and `cot=False`, every prompt therefore begins `\n\nAnswer the following…` and has a trailing space after `A,B,C,D,E.`. We reproduce those bytes exactly (269/269). It is cosmetic to the mark: bound 0.
- **What our row's frontier score is comparable to.** The row serves `FrontierScore(score=0.877, model="GPT-4")`, the paper's few-shot / few-shot-CoT number (`apps/screamingface-engine/src/screamingface_engine_inspect/benchmarks.py:2307-2314`). Our prompt is inspect's zero-shot, no-CoT template, which is a different process from either. The paper's zero-shot GPT-4 number is 85.9 (Table 2). This is not a grading dimension and no mark changes. It is recorded so a reader does not read our score against 87.7 as like for like.
- **No published inspect_evals number.** The eval's README has no evaluation-report section, so `comparable-to-inspect` would mean comparable to a run of the pinned eval, not to a number inspect_evals printed.
