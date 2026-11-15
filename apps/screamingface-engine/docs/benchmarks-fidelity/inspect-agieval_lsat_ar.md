---
benchmark: inspect-agieval_lsat_ar
origin: inspect_evals
verdict: unverified
verdict_reason: "Our copy matches inspect_evals on dataset, prompt, answer extraction, metric and roll-up, with zero differences on all 230 Cases. The judge dimension does not apply. One possibly-score-changing deviation is open and undeclared: inspect_evals' Task fixes GenerateConfig(temperature=0, max_tokens=2048, top_p=1) (inspect_evals:agieval/utils.py:196), and our Benchmark applies none of it, because the importer never reads task.config. Only a paid run can bound its effect, so the rule gives unverified. inspect_evals and the original AGIEval harness are different examiners: they mark differently on 177 to 230 of 230 Cases per sheet, which is unbounded. So comparable-to-paper is out either way, and the best this Benchmark can reach is comparable-to-inspect."
audited: 2026-11-09
audited_at: 48fe0ec5b
fingerprint:
  benchmark: 13fe1a6267102769
  harness_url: https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0/src/inspect_evals/agieval
references:
  paper: https://arxiv.org/abs/2304.06364v2
  original_harness: https://github.com/ruixiangcui/AGIEval/tree/84ab72d94318290aad2e4ec820d535a95a1f7552
  inspect_evals: https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0
  inspect_ai: https://github.com/UKGovernmentBEIS/inspect_ai/tree/v0.3.263
parity_test: none
parity_test_reason: "No test puts the reference's marks beside ours for this Benchmark. The closest pins are tests/unit/inspect/test_inspect_task_replay_benchmarks.py, which grades two hand-written Cases through our grader (3 tests for agieval_lsat_ar), and tests/unit/inspect/test_benchmark_fingerprints.py, which pins the fingerprint. Both passed in this audit. The parity evidence is the answer sheets below: 10,350 marks across three examiners."
---

# AGIEval LSAT-AR — Fidelity Record

## Verdict

**`unverified`.** On every one of the 230 Cases, the Candidate gets exactly the bytes that [inspect_evals v0.20.0 `agie_lsat_ar`](https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0/src/inspect_evals/agieval) sends, and the answer key is the same. On 15 answer sheets per Case, our installed Benchmark's grading route and inspect's own solver plus `choice()` give the same mark every time (3,450 pairs, 0 differ). Our roll-up equals inspect's `accuracy()` to four decimals on seven mark vectors.

The verdict stops at `unverified` because of D1. inspect_evals' Task fixes `temperature=0, max_tokens=2048, top_p=1`. Our Benchmark applies none of these settings, so the Candidate answers with its own. Nothing on the row declares this. Only a paid run can bound its effect: `possibly-score-changing`, bound `unknown`.

Even after that run, the paper's number stays out of reach. The paper's 35.2% (GPT-4, zero-shot, Table 2 of [Zhong et al. 2023 v2](https://arxiv.org/abs/2304.06364v2)) came from the authors' harness, [ruixiangcui/AGIEval@84ab72d9](https://github.com/ruixiangcui/AGIEval/tree/84ab72d94318290aad2e4ec820d535a95a1f7552), which works differently from inspect_evals:
- It sends two chat calls, with a system message and an "Among A through E, the answer is" completion prompt.
- It takes the first capital letter A-F in the reply as the answer.

inspect_evals sends one `ANSWER: $LETTER` prompt instead. The two examiners disagree on 177 to 230 of 230 Cases on every sheet that has a parseable answer (Upstream notes), so that gap is `unbounded`.

The arithmetic: sum of bounded deviations against inspect_evals = 0/230 = 0.0000. One `possibly-score-changing` deviation is open (D1, `unknown`), so the result is `unverified`. inspect_evals vs the original harness is `unbounded`, so `comparable-to-paper` is not reachable. If the D1 run bounds it at ≤ 0.005, the verdict becomes `comparable-to-inspect`.

## Dimensions

| dimension | status | severity | bound | evidence |
|---|---|---|---|---|
| dataset | match | — | — | **In-process replay with the declaration's pins** (Checks run 4): `task built: samples 230`, `captured 230 Cases`, `case_digest computed 5f77e982829b4ce7 pinned 5f77e982829b4ce7 equal True`, `case_set_digest computed e6c83fea1dbe4532 pinned e6c83fea1dbe4532 equal True`. The pins are at `apps/screamingface-engine/src/screamingface_engine_inspect/prepare.py:204-211`. There is no `shuffle_seed`, `choice_shuffle_seed`, `excluded_sample_ids` or `task_args` (`None` for each).<br>**The file:** inspect_evals fetches `https://raw.githubusercontent.com/ruixiangcui/AGIEval/84ab72d9…/data/v1_1/lsat-ar.jsonl` (`inspect_evals:agieval/utils.py:32-34`, `:167-172`) and does not shuffle. That commit is the harness clone's HEAD.<br>**Ours vs the harness file, row by row in file order** (Checks run 5): `label differs [] options differ [] question/passage not in input []`. All 230 rows have 5 options prefixed `(A)`…`(E)`, and none has an empty passage or label. The target letters are A 53, B 41, C 47, D 45, E 44.<br>**The paper-era file:** `data/v1/lsat-ar.jsonl` equals `v1_1` row for row (`230 of 230`), and so does the original 2023-04-13 upload (`666a489`). |
| prompt | match | — | — | **All 230 Cases rendered both ways:** our capture (`apps/screamingface-engine/src/screamingface_engine_inspect/capture.py:271`) vs the Task's own `multiple_choice(template=…)` solver (`inspect_evals:agieval/utils.py:147-155`, template `:68-76`). The solver ran on a TaskState with a stub `generate` that records the messages.<br>**Result** (Checks run 4): `Cases whose Candidate input bytes != inspect solver-rendered user message: [] count 0`. `Cases with a system message on inspect's side: 0 ; with more than one message: 0`. The sha256 of all inputs is `c738bffcb3ce127a`.<br>**Shape:** zero-shot and no CoT. With the Task's defaults `cot=False, fewshot=None` (`inspect_evals:agieval/agieval.py:26-42`), `{fewshot_string}` and `{cot_string}` stay empty. That is why every input starts with `\n\n` and has a trailing space after `A,B,C,D,E.`. These are inspect's own bytes, and we serve them unchanged. |
| answer extraction | match | — | — | **Ours replays inspect's own functions:** `parse_answers` + `set_choices_based_on_generated_response` with `multiple_correct=False` (`apps/screamingface-engine/src/screamingface_engine_inspect/scorer_adapter.py:651`; `imported_benchmark('agieval_lsat_ar').multiple_correct` → `False`, Checks run 2). This is the pair inspect's solver calls (`inspect_ai:solver/_multiple_choice.py:82-152`, strict regex `:98-102`, lenient `:107-110`, last match `:115`, uppercase `:121`).<br>**Answer sheets** (Checks run 6): 15 sheets × 230 Cases. `ours vs inspect - sheets with any differing mark: none (identical on every mark)`. |
| metric | match | — | — | **Ours:** the row scorer is `inspect_ai.scorer:choice` (`apps/screamingface-engine/src/screamingface_engine_inspect/benchmarks.py:2160`), resolved by `_scorer_factory` (`benchmarks.py:8483-8492`). `C`/`I` map to 1.0/0.0 (`scorer_adapter.py:111`).<br>**Theirs:** the Task's `choice()` for every non-cloze subset (`inspect_evals:agieval/utils.py:189`; `inspect_ai:scorer/_choice.py:60-112`).<br>**Evidence:** the same 3,450 our-vs-inspect mark pairs, all identical (Checks run 6). `tests/unit/inspect/test_inspect_task_replay_benchmarks.py -k agieval_lsat_ar` → `3 passed` (Checks run 8). |
| roll-up | match | — | — | **Ours:** the installed Benchmark's aggregate route. `_accuracy` computes `round(sum(values) / len(cases), 4)` (`apps/screamingface-engine/src/screamingface_engine_inspect/single_shot.py:1275-1303`). `whole_run_metric_factory` is `None`.<br>**Theirs:** inspect's `accuracy()` = `total / float(len(scores))` (`inspect_ai:scorer/_metrics/accuracy.py:29-37`). The harness uses `correct_numer / len(result_for_human)` (`fork:post_process_and_evaluation.py:117-118`).<br>**Seven vectors through all three** (Checks run 7): all-1 1.0000; all-0 0.0000; alternating 0.5000; every-3rd 0.3348; two sheet vectors 1.0000 / 0.2304; first-53 0.2304. `equal4 True` on every line. |
| judge | not applicable | — | — | `imported_benchmark('agieval_lsat_ar').judge` → `None` (Checks run 2). The Task's model-graded `expression_equivalence()` applies only to the cloze subset `math` (`inspect_evals:agieval/utils.py:189`, `CLOZE_TASK` `:48-50`). LSAT-AR is graded by `choice()`, and the harness uses `prediction == label` (`fork:src/evaluation.py:17-25`). No model grades. |
| sampling | deviation | possibly-score-changing | unknown | **D1, undeclared.** inspect_evals: `config=GenerateConfig(temperature=0, max_tokens=2048, top_p=1)` with the comment "from source paper 4.2.4" (`inspect_evals:agieval/utils.py:195-196`). The replayed Task printed `task.config 0.0 2048 1.0` (Checks run 4). Ours: `params None`, `declaration=BenchmarkDeclaration(failure_policy='withhold', interaction='single_shot', difficulty='hard', attempts=1)` (Checks run 2). No source file in the import or run path reads `task.config` (Checks run 3: `grep` exit 1), so the Candidate answers with its own settings. Attempts: 1 on both sides (`epochs None` = one). |

## Deviations

### D1 — inspect_evals' temperature 0, 2,048-token cap and top_p 1 are not applied

- **Undeclared.** The row (`apps/screamingface-engine/src/screamingface_engine_inspect/benchmarks.py:2137-2197`) and its declaration (`apps/screamingface-engine/src/screamingface_engine_inspect/prepare.py:199-211`) carry no `# NAMED DEVIATION` / `Named Deviation:` line, no `dropped_scorers` and no `excluded_sample_ids` (`awk` over both ranges → no line, Checks run 3). The description (`benchmarks.py:2141-2149`) does not mention generation settings.
  - The catalogue's convention for a dropped `task.config` is a Named Deviation in the description (`docs/plan/2026-10-05-OME-1268-multi-score-benchmarks.md:70`, D10). MATH follows it with a comment at `benchmarks.py:4189`.
  - The general importer doc states that `task.config` is never applied (`apps/screamingface-engine/docs/importing-an-inspect-eval.md:106`). The row does not link that doc, so this is a finding.
- **Where.** Theirs: `inspect_evals:agieval/utils.py:196`, which inspect merges into every model call. Ours: no `task.config` reader in `importer.py`, `capture.py`, `task_replay.py`, `single_shot.py` or `scorer_adapter.py` (Checks run 3). The Candidate's own parameters apply.
- **What differs.** Under `inspect eval`, every reply is greedy (temperature 0, top_p 1) and capped at 2,048 tokens. Under ours, the Candidate samples at its own temperature and with its own cap.
  - The prompt asks for the answer on the last line. Under inspect, a reply that runs past 2,048 tokens is cut before its `ANSWER:` line and marked 0. Under ours, the same reply can finish and be marked right.
  - Long replies are likely on 230 constraint puzzles, and with reasoning Candidates.
- **Severity / bound.** `possibly-score-changing`, `unknown`. Which Cases change depends on the Candidate's replies, so the bound needs a paid run (Recommended paid runs).

## Checks run

- [x] **Read-only on the checkout.** `git status --porcelain` before and after showed only `?? docs/work/2026-11-09-fidelity-sweep.md`. That is the sweep ledger the calling session writes into this worktree at the same time, and it is expected. This audit created nothing under the checkout. All its files lived under `$SCRATCH=/private/tmp/claude-501/…/scratchpad/audit-inspect-agieval_lsat_ar-N3kf`. That folder was deleted at the end with `python3 -c "import shutil, sys; shutil.rmtree(sys.argv[1])" "$SCRATCH"`, and `ls` then gave `No such file or directory`.
- [x] **No keys, no model.** `env -i PATH="$PATH" HOME="$SCRATCH" UV_CACHE_DIR="$SCRATCH/uv-cache" env | grep -iE 'key|token|secret'` → empty output (`grep exit=1`). The `git clone` and the arXiv `curl`s ran under that prefix.
  - **Limitation:** the harness was not installed in its own venv. Its code needs `openai`, `azure-identity`, `pandas` and `tiktoken` only to call Azure and to cut few-shot prompts; scoring zero-shot answers needs none of them.
  - Instead, its pure functions (`find_first_capital_letter`, `evaluate_single_sample`, `convert_to_set`, `convert_zero_shot`) were lifted verbatim with `ast` from the cloned files and run with `python -I`. `convert_zero_shot` ran under the system `python3`. The two scoring functions ran inside the our-side `uv run --isolated --extra inspect` process, so not under the `env -i` prefix. They use only `re` and plain comparisons and read no environment.
  - No model, gateway or provider was called.
- [x] **Harness over paper.** The paper describes the two-step "explanation then answer" only for CoT (§4.1) and says max tokens is 2048 (§4.2.4). The harness runs zero-shot as two chat calls too, and its chat call sets no `max_tokens`. The harness is the reference, and both gaps are in Upstream notes.
- [x] **Declared is not a finding.** Nothing on this row is declared. D1 is undeclared and is a finding.
- [x] **Every cell has evidence.** Each `match` cites the commands and output lines below.
- [x] **Every `file:line` is copied from command output.**
  - Ours: from `grep -n`, `sed -n` and `awk` on the checkout files (Checks run 3).
  - `inspect_evals:` and `inspect_ai:`: from `cat -n` / `awk '{printf "%d\t%s\n", NR, $0}'` on scratch copies of the installed v0.20.0 / v0.3.263 files (Checks run 2).
  - `fork:`: from `awk '{printf "%d\t%s\n", NR, $0}'` on single files of the clone at `84ab72d9` (Checks run 9). Line numbers taken from one concatenated `awk` stream were not used; `fork:src/evaluation.py` lines come from a `grep -n` on that file alone.
  - `arxiv-src:`: from `grep -n` / `sed -n` on the v2 source tarball (Checks run 10).
- [x] **A verdict never claims more than its evidence.** No dimension is `unchecked`. D1 is an open `possibly-score-changing` deviation → `unverified`.
- No `ours` override was set.

1. `git rev-parse --short HEAD` → `48fe0ec5b`. `git status --porcelain` → `?? docs/work/2026-11-09-fidelity-sweep.md` (the calling session's ledger).
2. Our side, from the Engine root: `HF_HUB_DISABLE_XET=1 uv run --isolated --extra inspect python -c "imported_benchmark('agieval_lsat_ar') …"`. Output:
   - `fingerprint 13fe1a6267102769`, `judge None`, `multiple_correct False`, `inverted_grade False`, `whole_run_metric_factory None`, `epoch_reducer_factory None`, `named_scores ()`.
   - `origin inspect_evals`, `harness_url https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0/src/inspect_evals/agieval`, `paper https://arxiv.org/abs/2304.06364`, `params None`.
   - `decl BenchmarkDeclaration(failure_policy='withhold', interaction='single_shot', difficulty='hard', attempts=1)`; `inspect_evals 0.20.0 inspect_ai 0.3.263`.

   The same call copied `inspect_evals/agieval/` and the inspect_ai helpers (`solver/_multiple_choice.py`, `scorer/_choice.py`, `scorer/_metrics/accuracy.py`, …) into scratch. Read there:
   - `inspect_evals:agieval/utils.py` (318 lines): `AGIEVAL_DATASET_REVISION` / `ROOT_URL` `32-34`, `CLOZE_TASK` `48-50`, `MULTIPLE_CHOICE_TEMPLATE_EN` `68-76`, `record_to_sample` `84-109`, MCQ solver `147-155`, `task_template` `160-199`, scorer choice `189`, `GenerateConfig(temperature=0, max_tokens=2048, top_p=1)` `196`.
   - `inspect_evals:agieval/agieval.py:26-42`.
   - `inspect_evals:agieval/README.md`: `:5` "based on the original implementation", `:63` `--temperature 0.5` example; no evaluation-report section.
   - `inspect_evals:agieval/eval.yaml:14-15` (`dataset_samples: 230`).
   - `inspect_ai:solver/_multiple_choice.py` (`prompt` `71-79`, `parse_answers` `82-152`, `max_tokens: int | None = None` `247`), `inspect_ai:scorer/_choice.py:60-112`, `inspect_ai:scorer/_metrics/accuracy.py:14-39`.
3. Our row and declaration:
   - `grep -n 'key="agieval_lsat_ar"\|published_revision=…\|inspect_evals_case_count=230\|score=0.352' benchmarks.py` → `2138`, `2139`, `2196`, `2190`.
   - `awk 'NR>=2137 && NR<=2197 {…}' benchmarks.py | grep -n "scorer=\|failure_policy\|…"` → description `2141`, difficulty `2154`, failure_policy `2155`, scorer `2160`, harness_url `2179`, human_baseline `2186`, frontier_score `2189`. `sed -n '2141,2150p'` showed the description, which says nothing about generation settings.
   - `awk 'NR>=2137 && NR<=2197 && /max_tokens|temperature|params|attempts|NAMED DEVIATION|Named Deviation|excluded|dropped|seed/'` → no line. `awk 'NR>=199 && NR<=211 && /seed|excluded|task_args|NAMED/' prepare.py` → no line.
   - `grep -n '"agieval_lsat_ar": TaskReplayCasesSpec\|case_count=230\|case_digest=…\|case_set_digest=…' prepare.py` → `204`, `206`, `207`, `208`.
   - `grep -n "set_choices_based_on_generated_response\|_INSPECT_LETTER_SCORE_VALUES\|def _task_state" scorer_adapter.py` → `88`, `111`, `607`, `651`. `grep -n "def _accuracy\|score=round(…)" single_shot.py` → `1275`, `1303`. `grep -n "def _scorer_factory" benchmarks.py` → `8483`.
   - `grep -n "task.config\|\.config\b" importer.py capture.py single_shot.py task_replay.py scorer_adapter.py` → no hit (`grep exit 1`).
   - `grep -n "D10" docs/plan/2026-10-05-OME-1268-multi-score-benchmarks.md` → `70`. `grep -n "an eval that pins" docs/importing-an-inspect-eval.md` → `106`. `grep -rn "Task.config\|config=GenerateConfig" …` → `benchmarks.py:4189` (MATH's Named Deviation).
4. Replay and prompt render: `HF_HUB_DISABLE_XET=1 uv run --isolated --extra inspect python -I scripts/render.py "$SCRATCH"`. The script does what `_replay_in_this_process` does (`task_replay.py:414-451`), minus the prefetch: `CaseSourceRecorder(cache_root).install(fetch_pins_of(spec))`, the eval's task function, then `captured_case_records(task, spec)`. `XDG_CACHE_HOME`, `INSPECT_EVALS_CACHE_DIR` and `INSPECT_EVAL_MODEL=none/none` pointed into scratch. Output:
   - `task built: samples 230 in 0.9 s`; `task.config 0.0 2048 1.0 epochs None`; `task_args None excluded None shuffle_seed None choice_shuffle_seed None source_pins {}`.
   - `captured 230 Cases`; both digests `equal True`.
   - `Cases whose Candidate input bytes != inspect solver-rendered user message: [] count 0`; `Cases with a system message on inspect's side: 0 ; with more than one message: 0`; `generate kwargs seen (Case 1): {'max_tokens': None}`.
   - `target==sample.target all: True choices==sample.choices all: True`; `target letters [('A', 53), ('B', 41), ('C', 47), ('D', 45), ('E', 44)] option counts [(5, 230)]`.
   - `sha256 of all inputs c738bffcb3ce127a`; `sample ids unique 230`.
   - Case 1 starts `"\n\nAnswer the following multiple choice question. The last line of your response should be of the following format: 'ANSWER: $LETTER' (without quotes) where LETTER is one of A,B,C,D,E. \n\nOf the eight students—George, …"`, options `A) … E)`, target `C`.
5. Dataset vs the harness file: `python3 -I scripts/dataset.py "$SCRATCH"` → `rows v1_1 230 v1 230 ours 230`; `v1_1 sha256 3b3e3fe09a07c695`; `label differs [] options differ [] question/passage not in input []`; `every v1_1 option starts '(X)' in order: True ; options all 5: True`; `passage None rows 0 label None rows 0`.
   - The script's first v1-vs-v1_1 comparison keyed rows by (passage, question). Logic-game passages and questions repeat, so it falsely reported 5 differing rows.
   - A positional comparison replaced it: `positional rows equal (all fields): 230 of 230`, `differing positions []`.
   - `git show 666a489:data/v1/lsat-ar.jsonl` (2023-04-13) → `equal to v1_1 positionally: 230`. `git log -- data/v1*/lsat-ar.jsonl` → `4673402 2024-06-07 update AGIEval version 1.1`, `4d88e6a 2023-09-28 encode with utf8`, `666a489 2023-04-13 upload all dataset`.
6. Answer sheets: `HF_HUB_DISABLE_XET=1 uv run --isolated --extra inspect python -I scripts/sheets.py "$SCRATCH"`.
   - **Three examiners:**
     - Ours: the installed Benchmark (`_write_cases` + `benchmark.install(node, root)`), graded through its aggregate route as the run does, the same path as `tests/unit/inspect/test_inspect_task_replay_benchmarks.py:136-143`.
     - inspect: the Task's own solver with a stub `generate` returning the reply, then `task.scorer[0]` (`choice()`), then `value_to_float()`.
     - Harness: `find_first_capital_letter(reply)` (zero-shot `post_process`), then `evaluate_single_sample('lsat-ar', pred, label)`.
   - **15 sheets per Case** (G = gold, W = next letter): `ANSWER: G`; `ANSWER: (G)`; `ANSWER: G.`; reasoning then `ANSWER: G`; `The answer is G.`; `(G)`; bare `G`; `**ANSWER: G**`; `ANSWER: g`; `ANSWER: W`; empty; `ANSWER: G` then `ANSWER: W`; `Among A through E, the answer is (G)`; `Based on the conditions, Kyle must report on Tuesday.\nANSWER: G`; a reply with no answer.
   - **Totals:** `marks 10350 ( 15 sheets x 230 Cases x 3 examiners )`; `ours vs inspect - sheets with any differing mark: none (identical on every mark)`.
   - **Per sheet (ours / inspect / harness correct):**

     | sheet | ours | inspect | harness |
     |---|---|---|---|
     | `ANSWER: G` | 230 | 230 | 53 |
     | `ANSWER: (G)` | 0 | 0 | 53 |
     | `ANSWER: G.` | 230 | 230 | 53 |
     | CoT + `ANSWER: G` | 230 | 230 | 53 |
     | `The answer is G.` | 0 | 0 | 230 |
     | `(G)` | 0 | 0 | 230 |
     | bare `G` | 0 | 0 | 230 |
     | `**ANSWER: G**` | 230 | 230 | 53 |
     | `ANSWER: g` | 230 | 230 | 53 |
     | `ANSWER: W` | 0 | 0 | 53 |
     | empty | 0 | 0 | 0 |
     | two lines | 0 | 0 | 53 |
     | harness format | 0 | 0 | 53 |
     | `Based on … ANSWER: G` | 230 | 230 | 41 |
     | no answer text | 0 | 0 | 0 |

   - The aggregate on sheet 1 read `"benchmark_id": "inspect-agieval_lsat_ar", "benchmark_revision": "13fe1a6267102769", "case_count": 230, "score": 1.0, "coverage": 1.0, "metrics": {"correct": 230, "scored_cases": 230}, "failures": []`.
7. Roll-up: `HF_HUB_DISABLE_XET=1 uv run --isolated --extra inspect python -I scripts/rollup.py "$SCRATCH"`. Each vector became replies (`ANSWER: G` for 1, `ANSWER: W` for 0) sent through our aggregate route, and the script asserted that our per-Case marks equal the vector. The same marks went through inspect's `accuracy()` over `SampleScore`s and the harness's `correct/len`. Output: `all-1 1.0000 ×3`; `all-0 0.0000 ×3`; `alternating 0.5000 ×3`; `every-3rd-correct 0.3348 ×3`; `sheet:Based_on_ANSWER_G (inspect marks) 1.0000 ×3`; `sheet:harness-format (harness marks) 0.2304 ×3`; `first-53-correct 0.2304 ×3`; `equal4 True` on all seven.
8. Tests:
   - `HF_HUB_DISABLE_XET=1 uv run --isolated --extra inspect pytest tests/unit/inspect/test_benchmark_fingerprints.py -q -p no:cacheprovider -k agieval_lsat_ar` → `1 passed, 94 deselected`.
   - `… pytest tests/unit/inspect/test_inspect_task_replay_benchmarks.py -q -p no:cacheprovider -k agieval_lsat_ar` → `3 passed, 143 deselected`.
9. Original harness: `env -i … git clone --quiet https://github.com/ruixiangcui/AGIEval harness` → HEAD `84ab72d94318290aad2e4ec820d535a95a1f7552 2024-06-13 update AGIEval scripts for ver. 1.1.`, the same commit inspect_evals pins. `git log -- src/post_process.py src/dataset_loader.py run_prediction.py openai_api.py src/evaluation.py` → `84ab72d`, `05c8189`, `54887c3`, `9a11e1e 2023-04-25 … limit parsed QA answer to A-F`, `666a489`. `git diff 4d88e6a 84ab72d -- src/post_process.py src/dataset_loader.py src/evaluation.py` → only the math/cloze path of `post_process.py` changed. The MCQ zero-shot path has been the same since the paper's v2.
   - `git show 4d88e6a:openai_api.py` has the same system message (`:92`) and `temperature=0` (`:105`).
   - Read per file with `awk '{printf "%d\t%s\n", NR, $0}'`:
     - `fork:src/dataset_loader.py`: `convert_zero_shot` `25-35`, `load_dataset` `219-247`, `generate_second_stage_input` `250-277`.
     - `fork:src/post_process.py`: `find_first_capital_letter` `72-78`, `post_process` `179-196`, zero-shot branch `187-189`.
     - `fork:src/evaluation.py:17-25` (from `grep -n` on that file).
     - `fork:run_prediction.py`: settings `135-140`, `chat_mode = True` `145`, stage 1 `163-170`, stage 2 `172-198`.
     - `fork:post_process_and_evaluation.py`: marking `99-105`, accuracy `117-118`.
     - `fork:openai_api.py`: chat call `79-103`, system message `87-89`, `temperature=0` `101`, `max_tokens=2000` on the completion API only `121`.
     - `fork:README.md:11`: "AGIEval-en datasets remain the same as Verison 1.0".
   - `python3 -I scripts/harness_prompt.py "$SCRATCH"` → `harness zero-shot stage-1 user message, Case 1: 1386 chars; ours 1520 chars`. The harness prompt starts with the passage with no instruction, writes options as `(A)…(E)` on one line, and ends `\nA: Among A through E, the answer is`. `Cases where harness prompt == ours: 0 of 230`.
10. Paper:
    - `env -i … curl https://arxiv.org/abs/2304.06364` → "Submitted on 13 Apr 2023", "last revised 18 Sep 2023 (this version, v2)". The PDF arXiv served was a 3-page stub, so the source was fetched instead: `curl https://arxiv.org/e-print/2304.06364v2`.
    - `arxiv-src:v2/sections/04_experiment.tex:40-42`: the two-step prompt, described under CoT.
    - `:51`: "We use a temperature of zero … set the maximum number of tokens for generation to 2048 … top p to 1".
    - `arxiv-src:v2/tables/main-result.tex:20`: `LSAT-AR & 56 & 91 & 21.7 & 24.4 & 35.2 & 23.9 & 22.6 & 34.4` (human Avg / Top, zero-shot TD-003 / ChatGPT / GPT-4, zero-shot CoT TD-003 / ChatGPT / GPT-4).
    - `:65`: few-shot `… 33.9 … 31.7`.
    - Afterwards: `python3 -c "import shutil, sys; shutil.rmtree(sys.argv[1])" "$SCRATCH"`. `git status --porcelain` → the same single ledger line. `git rev-parse --short HEAD` → `48fe0ec5b`.

## Recommended paid runs

- **D1 (sampling), 230 Cases × 3 sittings, no judge.** Pick one Candidate that accepts `temperature`, `top_p` and `max_tokens`, preferably a reasoning model, since long replies are where the 2,048-token cap bites.
  - **Arm A:** all 230 Cases at `temperature=0, top_p=1, max_tokens=2048`, the inspect_evals settings.
  - **Arm B:** all 230 Cases with no settings, the way our Benchmark runs today.
  - **Arm B again:** a repeat of arm B, to measure run-to-run noise.
- **Bound** = |headline(A) − headline(B)| beyond the B-vs-B noise. Also count the Cases whose arm-A reply hit the 2,048-token cap (`finish_reason == "length"`).
- If the bound is ≤ 0.005, D1 becomes `score-changing` with that bound, and the verdict becomes `comparable-to-inspect`. If it is above 0.005, the verdict becomes `not-comparable`, unless the row applies or declares the settings.
- Grading is `choice()`, so no judge tokens are spent. The run costs about 690 Candidate calls.

## Upstream notes

- **inspect_evals vs the original harness: a different examiner, `unbounded`.** [inspect_evals v0.20.0 `agieval`](https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0/src/inspect_evals/agieval) says it is "based on the [original implementation](https://github.com/ruixiangcui/AGIEval/tree/main)" (`inspect_evals:agieval/README.md:5`). For zero-shot MCQ it departs from [ruixiangcui/AGIEval@84ab72d9](https://github.com/ruixiangcui/AGIEval/tree/84ab72d94318290aad2e4ec820d535a95a1f7552) in two ways.
  - **Prompt.** inspect_evals sends one user message with no system message: the `ANSWER: $LETTER` instruction, then the passage and question, then `A) …` option lines (`inspect_evals:agieval/utils.py:68-76`).
    - The harness first sends a system message, "You are a helpful AI assistant." (`fork:openai_api.py:87-89`).
    - Its stage-1 user message is `passage + "Q: " + question + " Answer Choices: (A)… (E)…" + "\nA: Among A through E, the answer is"` (`fork:src/dataset_loader.py:25-35`).
    - Its stage 2 sends the stage-1 prompt, the stage-1 reply and `Therefore, among A through E, the answer is` (`fork:src/dataset_loader.py:250-277`, run at `fork:run_prediction.py:172-198`).
    - Case 1 is 1,386 chars vs 1,520, and 0 of 230 prompts are equal.
  - **Answer extraction.** inspect_evals reads the last `ANSWER:` line (`inspect_ai:solver/_multiple_choice.py:98-121`). The harness takes the first capital A-F anywhere in the stage-2 reply (`fork:src/post_process.py:72-78`, `:187-189`) and marks `prediction == label` (`fork:src/evaluation.py:17-25`).
  - **On the sheets:**
    - A reply in the harness's own format (`The answer is C.`, `(C)`, bare `C`) is right under the harness on 230/230 Cases and wrong under inspect on 230/230.
    - A reply in inspect's format (`ANSWER: C`) is right under inspect on 230/230. The harness credits it only on the 53 Cases keyed A, because it reads the "A" of "ANSWER".
    - The gap depends on how a Candidate formats its replies, so it cannot be bounded: `unbounded`.
  - Sampling agrees in part: both use temperature 0 (`fork:openai_api.py:101`).
- **Harness vs paper.** The harness wins; these are recorded, not counted.
  - **Two-step zero-shot.** The paper describes the two-step "explanation, then answer" prompt only for CoT (`arxiv-src:v2/sections/04_experiment.tex:40-42`). The harness also runs its zero-shot setting as a stage-1 chat call followed by a stage-2 answer call (`fork:run_prediction.py:163-198`).
  - **No token cap on chat.** The paper says "set the maximum number of tokens for generation to 2048" (`:51`). The harness's chat call passes no `max_tokens` (`fork:openai_api.py:98-103`); only the completion API sets `max_tokens=2000` (`:121`). The `max_tokens=2048` given to `load_dataset` (`fork:run_prediction.py:151`) is the few-shot prompt budget (`fork:src/dataset_loader.py:146-168`).
  - So inspect_evals' `max_tokens=2048` follows the paper, not the harness (`inspect_evals:agieval/utils.py:195-196`).
  - The MCQ zero-shot code has not changed since before the paper's v2 (`git diff 4d88e6a 84ab72d` touches only the math path).
- **Data version: bound 0.** inspect_evals and the harness at `84ab72d9` read `data/v1_1/lsat-ar.jsonl`. The paper's 2023 numbers predate v1.1. For LSAT-AR, `v1` and `v1_1` are equal row for row (230/230), and both equal the 2023-04-13 upload, matching "AGIEval-en datasets remain the same as Verison 1.0" (`fork:README.md:11`).
- **The row's published reference points come from the harness's examiner.** The row's `frontier_score` is 0.352: GPT-4, zero-shot, "the best of the paper's four prompt settings" (`apps/screamingface-engine/src/screamingface_engine_inspect/benchmarks.py:2189-2192`; `arxiv-src:v2/tables/main-result.tex:20`). Its `human_baseline` is 0.56, the Avg column. Under the first note above, a score from this Benchmark can sit beside an inspect_evals run of `agie_lsat_ar`, not beside the 35.2.
- **No published inspect_evals number.** The eval's README has no evaluation-report section. Once D1 is settled, "comparable-to-inspect" would mean comparable to a run of the pinned eval.
