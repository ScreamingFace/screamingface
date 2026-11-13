---
benchmark: inspect-mmmu_open
origin: inspect_evals
verdict: not-comparable
verdict_reason: "different examiners by design: MMMU's own harness marks open answers with a rule-based matcher (parse_open_response + eval_open), inspect_evals has model_graded_fact marked by the model under test, and this row pins openrouter/openai/gpt-5.4 as the judge (declared NAMED DEVIATION). No published number covers the 53 open-answer questions alone. Two further gaps are open and unsized (judge-unparseable Cases count 0 here but are dropped by inspect; temperature 0 is not imposed), but no paid run could change this verdict"
audited: 2026-11-09
audited_at: 43d3942f6
fingerprint:
  benchmark: 8ce88e420239ae4d
  harness_url: https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0/src/inspect_evals/mmmu
references:
  paper: https://arxiv.org/abs/2311.16502v4
  original_harness: https://github.com/MMMU-Benchmark/MMMU/tree/aa9b70da92c2825b3d544d1a11b36856bd92f6c3
  inspect_evals: https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0
  inspect_ai: https://github.com/UKGovernmentBEIS/inspect_ai/tree/v0.3.263
parity_test: tests/unit/inspect/test_mmmu_open_cases.py
parity_test_reason: ""
---

# MMMU (open answer) — Fidelity Record

## Verdict

**`not-comparable`.** Our headline is the mean judge grade over the 53 open-answer questions of the [MMMU](https://arxiv.org/abs/2311.16502v4) validation split. It cannot sit beside any published MMMU number, for two reasons.

**First, no such number exists.** The paper and every lab report score all 900 validation questions (or the test split), never the open ones alone. The row says so itself in `frontier_score=NotPublished(...)`.

**Second, the examiner differs by design, on both references:**
- [MMMU's own harness](https://github.com/MMMU-Benchmark/MMMU/tree/aa9b70da92c2825b3d544d1a11b36856bd92f6c3) marks an open answer with a rule-based string and number matcher (`fork:mmmu/utils/eval_utils.py:122,191-216`).
- [inspect_evals](https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0/src/inspect_evals/mmmu) replaces that matcher with `model_graded_fact()` and no model, so the model under test grades itself (`inspect_evals:mmmu/mmmu.py:85`).
- This row pins `openrouter/openai/gpt-5.4` as the judge, declared as a `NAMED DEVIATION` (`apps/screamingface-engine/src/screamingface_engine_inspect/benchmarks.py:6952-6957`).

Everything below the judge's call matches inspect_evals exactly:
- the Candidate's bytes on all 53 Cases, 54 pictures included;
- the dataset and gold on all 53;
- the judge prompt bytes and the marks on 371 answer sheets;
- the mean on four mark vectors.

The arithmetic:
- Against the original harness: D1 (rule-based matcher replaced by an LLM judge) is `unbounded` by design → `not-comparable`.
- Against inspect_evals: D1 (gpt-5.4 instead of the Candidate grading itself) is `unbounded` by design, plus D2 `unknown` and D3 `unknown` → `comparable-to-inspect` is ruled out as well.

D2 and D3 are open `possibly-score-changing` deviations, which on their own would make this `unverified`. But D1 is a different examiner by design, which no paid run can remove, so `not-comparable` is the verdict.

## Dimensions

| dimension | status | severity | bound | evidence |
|---|---|---|---|---|
| dataset | match | — | — | **Ours:** real Task replay through the child process (`replay_with_provenance`) gave `cases 53 pinned 53`, with 30 Hub configs `MMMU/MMMU/<subject>` loaded at `171b0ef7…` (Checks run 4). **Theirs:** `inspect_evals:mmmu/utils.py:13,89` (same revision, split `validation`), filter `question_type == "open"` (`inspect_evals:mmmu/mmmu.py:74`) gave `samples 53` (Checks run 6). Gold per Case, in order: `gold differs on Cases []` (Checks run 9). **Against the harness's own answer file** (`fork:mmmu/answer_dict_val.json`): 900 rows, 53 open, `open ids only in harness file []`, `ids only in inspect task []`, gold differences none. The 3 list-valued golds (Cases 11, 38, 48) equal the harness lists as strings (Checks run 8). **Seal:** on this Mac the Case Digest `71f776f7…` and the case-set digest `c12472a8…` differ from the pins. This is expected: the row documents that inspect_evals re-encodes pictures with Pillow, whose PNG bytes are platform-bound, so the seal was made on linux/amd64 (`apps/screamingface-engine/src/screamingface_engine_inspect/prepare.py:2056-2057`). It is not a difference between examiners. The seal was not reproduced on linux/amd64 in this audit. |
| prompt | match | — | — | All 53 Cases rendered both ways. Ours: `ours_cases.json` from the replay child (`capture.py:271`). Theirs: inspect's own `eval()` of `mmmu_open()` with a recording mock Candidate. Result: `Cases whose Candidate input differs from inspect's (roles, part order, text bytes, decoded picture bytes): []`, `pictures compared 54`, `multi-picture Cases [(43, 'validation_Manage_20')]` (both pictures, same slot order on both sides), layout `['image', 'text']`, roles `['user']`, no system message (Checks run 9). Text = `OPEN_PROMPT` "Answer the question using a single word or phrase.\n{question}" (`inspect_evals:mmmu/mmmu.py:66-69,84`). The text goes after the pictures because inspect's text setter appends it (`inspect_ai:model/_chat_message.py:129`). The parity test pins the same layout: `test_the_candidate_sees_the_pictures_in_slot_order_then_the_eval_s_open_line` (`apps/screamingface-engine/tests/unit/inspect/test_mmmu_open_cases.py:209`), passed (Checks run 12). |
| answer extraction | match | — | — | Neither side extracts an answer: the judge reads the whole reply (`state.output.completion`), and the prompt quotes `state.input_text` (`inspect_ai:scorer/_model.py:299`). Our scorer is inspect's `model_graded_fact` itself, resolved from the row (`apps/screamingface-engine/src/screamingface_engine_inspect/benchmarks.py:6949-6950,8483-8490`). Judge prompt bytes on 371 sheets (53 Cases × 7 replies): `judge prompt diffs 0` (Checks run 9). The question quoted to the judge is the Sample's own, without the open-answer line, on both sides (`scorer_adapter.py:622`). Also pinned by `test_the_judge_reads_the_sample_s_question_byte_for_byte_as_inspect_s_judge_does` (`test_mmmu_open_cases.py:237`, passed). |
| metric | match | — | — | Same scorer code on both sides, and the same fixed judge reply per sheet kind. 371 sheets: `mark diffs 0` (Checks run 9). The rule tested covers `C`, `Correct` and lower-case `c` → 1, `I` → 0, last `GRADE:` wins (`GRADE: I … GRADE: C` → C). `GRADE: P` (partial credit off) and a reply with no verdict are `Score.unscored` on inspect's side (`inspect_ai:scorer/_model.py:349`) and `invalid_score_value` on ours (`scorer_adapter.py:878`), on the same 106 sheets. How a mark-less Case reaches the headline is D2 (roll-up). |
| roll-up | deviation | possibly-score-changing | unknown | Our mean: `withhold` → `_accuracy` (`apps/screamingface-engine/src/screamingface_engine/benchmarks/aggregation.py:106`; `apps/screamingface-engine/src/screamingface_engine_inspect/single_shot.py:1275,1303`). Theirs: inspect's `accuracy()` (`inspect_ai:scorer/_metrics/accuracy.py:15,37`) under its NaN filter (`inspect_ai:_eval/task/results.py:405-412`). all-C / all-I / alternating / every-3rd-C → `1.0000 / 0.0000 / 0.5094 / 0.3396` on ours, inspect's real `eval()` and the harness's `calculate_ins_level_acc` alike (Checks run 10-11, 13). They part only on a Case with no verdict: alternating with 5 unparseable judge replies → ours `0.4151` (22/53, coverage 0.9057), inspect `0.4583` (22/48, `scored [48] unscored [5]`). See D2. |
| judge | deviation | score-changing (different process by design) | unbounded | See D1. Ours: `JudgeSpec(model='openrouter/openai/gpt-5.4', params=(('web_search','false'),('max_tokens','4096')))` (`benchmarks.py:6957,6960`). inspect_evals: `model_graded_fact()` with no model, so the Candidate grades itself (`inspect_evals:mmmu/mmmu.py:85`). Harness: no judge, a rule-based matcher (`fork:mmmu/utils/eval_utils.py:191-216`). The prompt template and reply parsing are inspect's, byte for byte (rows above). |
| sampling | deviation | possibly-score-changing | unknown | See D3. inspect_evals fixes `GenerateConfig(temperature=0)` (`inspect_evals:mmmu/mmmu.py:86`; Checks run 6 prints `temperature=0.0`, every other field `None`). Ours: `declaration=BenchmarkDeclaration(failure_policy='withhold', interaction='single_shot', difficulty='medium', attempts=1)`, with no generation settings on the row (Checks run 2). One attempt per Case on both sides. |

## Deviations

### D1 — the judge is the pinned house model, not the model under test (and not MMMU's rule-based matcher)

- **Declared.** `# NAMED DEVIATION` on the row (`apps/screamingface-engine/src/screamingface_engine_inspect/benchmarks.py:6952-6956`): "the eval calls model_graded_fact() with no model, so inspect grades with the model under test … This Benchmark pins the house judge … so its scores are NOT directly comparable to an inspect run that lets the Candidate grade itself." The row's description says the same (`:6934`).
- **Where.** Ours: `scorer_kwargs={"model": "screamingface/openrouter/openai/gpt-5.4"}` (`benchmarks.py:6950`) and `JudgeSpec` (`:6951-6960`). Theirs: `scorer=model_graded_fact()` (`inspect_evals:mmmu/mmmu.py:85`). Original harness: `parse_open_response` then `eval_open` (`fork:mmmu/utils/eval_utils.py:122,191`, called at `fork:mmmu/main_parse_and_eval.py:51`).
- **What differs.** The examiner itself. Prompt template, reply parsing and the mark map are identical to inspect_evals (371 sheets, 0 prompt or mark differences). Only the model that answers the judge prompt differs.
- **Severity / bound.** `score-changing`, `unbounded`. A judge model other than the one the reference used is a different process by design (spec §2.3), so this alone makes the verdict `not-comparable`.

### D2 — a Case the judge gives no verdict on counts 0 in our mean; inspect drops it

- **Undeclared.** `failure_policy="withhold"` is on the row (`benchmarks.py:6944`) and the engine documents it (`single_shot.py:1275`, OME-1642). But no `NAMED DEVIATION` line or README names the difference from inspect's aggregation.
- **Where.** Ours: `aggregation.py:106` hands every selected Case to `_accuracy`, which divides by `len(cases)` (`single_shot.py:1303`). Theirs: `inspect_ai:_eval/task/results.py:405-412` filters NaN-unscored Samples out before `accuracy()`.
- **What differs.** A judge reply with no parseable `GRADE: C/I` (including `GRADE: P`, since partial credit is off) counts 0 for us and is left out of inspect's denominator. On the fixed vector with 5 such Cases: `0.4151` vs `0.4583`.
- **Severity / bound.** `possibly-score-changing`, `unknown`: how many of gpt-5.4's replies fail to parse is a judge behaviour that only a paid run can count. Each such Case moves our headline by up to 1/53 = 0.0189 relative to inspect's.

### D3 — inspect_evals runs the Candidate at temperature 0; we impose no generation settings

- **Undeclared.** The row's description says so in prose ("inspect_evals runs the model at temperature 0; this benchmark imposes no generation settings", `benchmarks.py:6934-6935`). The agent's rule does not count description prose as a declaration, and there is no `NAMED DEVIATION` line.
- **Where.** Theirs: `config=GenerateConfig(temperature=0)` (`inspect_evals:mmmu/mmmu.py:86`). Ours: no settings on the row (Checks run 2).
- **What differs.** The Candidate's decoding temperature: its provider default here, 0 in inspect_evals.
- **Severity / bound.** `possibly-score-changing`, `unknown`: it changes what the Candidate writes, not how a written reply is marked.

## Checks run

- [x] **Read-only on the checkout.** `git status --porcelain` before showed one untracked file, `docs/work/2026-11-09-fidelity-sweep.md` (the calling session's ledger, not this audit's). After, it showed that file plus nine other audits' records written by the calling session in the meantime. None is this audit's, and nothing tracked changed.
  - Every file this audit wrote lived under `SCRATCH=/private/tmp/claude-501/…/scratchpad/audit-mmmu_open-j9Us`, deleted at the end (`chmod -R u+w` + `rm -r`; the safety hook blocks `rm -rf`).
  - Two side effects outside it:
    - **The replay child's own temp dir.** It created `/private/tmp/task-replay-fmzpgj6l` because `env -i` dropped `TMPDIR`, and removed it itself (`No such file or directory` afterwards).
    - **Possible bytecode files.** The first `uv run` calls ran without `PYTHONDONTWRITEBYTECODE`, so they may have written gitignored `__pycache__` files under the checkout's `src/`. Later calls set `TMPDIR=$SCRATCH/tmp` and `PYTHONDONTWRITEBYTECODE=1`.
- [x] **No keys, no model.** `env -i PATH="$PATH" HOME="$SCRATCH" UV_CACHE_DIR="$SCRATCH/uv-cache" env | grep -iE 'key|token|secret'` → empty (`grep exit=1`). Every third-party command ran under that prefix. Candidate and judge were inspect's `mockllm` everywhere. No model, gateway or provider was called; the Hub was read unauthenticated (MMMU is not gated).
- [x] **Harness over paper.** The harness is the reference. Where inspect_evals differs from it, that goes to Upstream notes. The paper PDF was not re-read in this audit.
- [x] **Declared is not a finding.** D1 is declared (`NAMED DEVIATION`). D2 and D3 are undeclared findings.
- [x] **Every cell has evidence.** Each `match` names its command and output lines.
- [x] **A verdict never claims more than its evidence.** No dimension is `unchecked`. The open `possibly-score-changing` D2 and D3 are named in the verdict, which rests on D1 (different by design).
- No `ours` override was set.

1. `git status --porcelain` → only the untracked ledger; `git rev-parse --short HEAD` → `43d3942f6`.
2. Our side: `uv run --isolated --extra inspect python -c "imported_benchmark('mmmu_open') …"` printed:
   - `fp 8ce88e420239ae4d`, `origin inspect_evals`
   - `harness https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0/src/inspect_evals/mmmu`, `paper https://arxiv.org/abs/2311.16502`
   - `judge JudgeSpec(model='openrouter/openai/gpt-5.4', params=(('web_search', 'false'), ('max_tokens', '4096')), …)`
   - `declaration=BenchmarkDeclaration(failure_policy='withhold', interaction='single_shot', difficulty='medium', attempts=1)`, `verdict_grades None`, `whole_run_metric None`
   - `inspect-evals 0.20.0`, `inspect-ai 0.3.263`

   A second call dumped the BenchmarkSpec fields: `scorer = 'inspect_ai.scorer:model_graded_fact'`, `scorer_kwargs = {'model': 'screamingface/openrouter/openai/gpt-5.4'}`, `dropped_scorers = ()`, no `excluded_sample_ids`.
3. Original harness: `env -i … git clone https://github.com/MMMU-Benchmark/MMMU harness && git checkout aa9b70da92c2825b3d544d1a11b36856bd92f6c3` → `aa9b70da… 2024-09-06 Update README`. This is the commit inspect_evals' README links for prompts and micro-averaging (`inspect_evals:mmmu/README.md:89`). `uv venv` + `uv pip install numpy pyyaml` → `2.5.4 6.0.3`. The eval and prompt code needs only these; the inference script needs LLaVA + CUDA and was not run.
4. Ours, prompt + dataset: `env -i … HF_HUB_DISABLE_XET=1 uv run --isolated --extra inspect python -I scripts/ours_render.py` (`replay_with_provenance(TASK_REPLAY_CASES["mmmu_open"])`, the real Hub fetch of all 30 configs, 3.36 GB with test splits) → `replay seconds 536.3`, `cases 53 pinned 53`, `case_digest 71f776f7… equal False`, `case_set_digest c12472a8… equal False`, provenance 30 `hugging-face MMMU/MMMU/<subject>` sources at `revision 171b0ef7…`.
5. A first inspect-side run with the real Hub fetch sat in inspect_evals' HF backoff (rate-limited, several audits fetching MMMU at once), so it was killed. Instead the 30 pinned `*/validation-00000-of-00001.parquet` files were downloaded (`HfApi().list_repo_tree(…, revision='171b0ef7…')` → `validation files 30 validation MB 341.2`) with `hf_hub_download` into `$SCRATCH/val`.
6. Theirs: `env -i … MMMU_VAL_DIR=$SCRATCH/val uv run --isolated --extra inspect python -I scripts/theirs.py`. It ran inspect_evals' real `mmmu_open()` under inspect's own `eval()`. Only `datasets.load_dataset` was replaced, by a stand-in that asserts `("MMMU/MMMU","validation","171b0ef7…")` and reads the same parquet from disk. The mock Candidate is wrapped to record its input and answer each sheet; the mock judge is wrapped to record its prompt and give a fixed reply per sheet kind. Output: `subjects loaded 30 at 171b0ef7`, `samples 53`; `gold`/`gold_sentence`/`gold_therefore`/`qwen` → `accuracy 1.0, values ['C']`; `wrong` → `0.0, ['I']`; `empty` (no verdict) and `llava` (`GRADE: P`) → `accuracy nan, ['None']`; `task config … temperature=0.0`, all other fields `None`.
7. Ours, answer sheets: `uv run --isolated --extra inspect python -I scripts/ours_sheets.py`. It ran the same 7 sheets × 53 Cases through `inspect_grade_case(model_graded_fact(model=<recording mock>))` with the same judge replies, the row's scorer with only the model swapped (asserted from `BENCHMARKS`). Output: `gold/gold_sentence/gold_therefore/qwen scores ['1.0']`, `wrong ['0.0']`, `empty`/`llava scores ['None'] failure_codes ['invalid_score_value']`.

   The sheets per Case: gold as written; `The answer is <gold>.`; `Let me compute.\nTherefore, the final answer is <gold>` (the harness parser's indicator words); a wrong reply `I cannot tell from the picture.`; the empty reply; and the two sets of real replies MMMU's repo records for these ids (`fork:mmmu/example_outputs/llava1.5_13b/*/output.json`, `qwen_vl/total_val_output.json`, 53 of 53 each). The repo has no goldens of ours for this Benchmark.
8. Harness, same sheets: `env -i … venv/bin/python -I scripts/harness_marks.py` (`eval_open(answer_dict_val[id]["ground_truth"], parse_open_response(reply))`) → `harness answer file rows 900 open rows 53`, `open ids only in harness file []`, `ids only in inspect task []`, gold differences none. Rule-based correct: gold 53/53, sentence 53/53, therefore 53/53, wrong 1/53, empty 0/53, llava real 2/53, qwen real 6/53.
9. Compare: `venv/bin/python -I scripts/compare.py`:
   - `ours cases 53 inspect samples 53`, `gold differs on Cases []`
   - `Cases whose Candidate input differs … []`, `pictures compared 54`, `multi-picture Cases [(43, 'validation_Manage_20')]`, layout `['image', 'text']`, roles `['user']`
   - `sheets 371 judge prompt diffs 0 mark diffs 0`
   - On the harness side: `wrong credited [(2, 'validation_Basic_Medical_Science_10', 'C')]`, `llava credited [(40, …Geography_22), (50, …Pharmacy_19)]`, qwen credited Cases 12, 23, 46, 47, 51, 52.
10. Roll-up, ours: `uv run --isolated --extra inspect python -I scripts/ours_rollup.py invalid_score_value` (production `finalize_candidate_result` + `_accuracy`, the row's `failure_policy`) → `withhold`; all_C 1.0000, all_I 0.0000, alternating 0.5094, every_3rd_C 0.3396, alternating_with_5_unparseable 0.4151 (coverage 0.9057).
11. Roll-up, inspect: `… scripts/theirs_rollup.py` (real `eval()`, mock judge following each vector) → 1.0000 / 0.0000 / 0.5094 / 0.3396 (`scored [53]`), and `alternating_with_5_unparseable 0.4583 scored [48] unscored [5]`. The first attempt crashed on the script's own print line (`EvalResults` has no `scored_samples`); the script was fixed and rerun.
12. `uv run --isolated --extra inspect pytest tests/unit/inspect/test_mmmu_open_cases.py -q -p no:cacheprovider` → `3 passed, 2 warnings in 110.34s`.
13. Roll-up, harness: `venv/bin/python -I scripts/harness_rollup.py` (`evaluate` per subject, then `calculate_ins_level_acc`) → 1.0000 / 0.0000 / 0.5094 / 0.3396 / 0.4151 over `subjects 15`. A rule-based examiner has no "unparseable", so a `U` was marked Wrong.
14. YAML check: `load_yaml(configs/llava1.5.yaml)` + `construct_prompt` → `'<image 1> Q?\nAnswer the question using a single word or phrase.'`.
15. Citations, every `file:line` above taken from these commands:
    - `grep -n` on the checkout's `benchmarks.py` (row lines 6917-6960), `prepare.py` (2056-2057, 2120-2125), `single_shot.py` (1275, 1303), `aggregation.py` (106) and `scorer_adapter.py` (111, 622, 878).
    - `grep -n` on the installed `inspect_evals/mmmu/{mmmu.py,utils.py,README.md}` (`diff -r` against the scratch copy: `identical`).
    - `grep -n` on the installed `inspect_ai/{scorer/_model.py,_eval/task/results.py,scorer/_metrics/accuracy.py,solver/_prompt.py,model/_chat_message.py}`.
    - `grep -n` on the clone's `mmmu/{configs/llava1.5.yaml,utils/data_utils.py,utils/model_utils.py,utils/eval_utils.py,run_llava.py,main_parse_and_eval.py,main_eval_only.py}`.
    - `sed -n` to confirm `data_utils.py:162-170`, `single_shot.py:1296-1304`, `benchmarks.py:6930-6937,6951-6962`.
16. `git status --porcelain` (see the first bullet); the scratch folder was deleted.

## Recommended paid runs

These would size D2 and the inspect_evals-vs-harness grading gap. Neither can move the verdict, since D1 is different by design.

- **Judge vs MMMU's matcher on real replies.** 106 judge calls: 53 Cases × the two real reply sets MMMU's repo records (llava1.5-13b, qwen-vl), each graded by the pinned judge `openrouter/openai/gpt-5.4` through the gateway (`web_search=false`, `max_tokens=4096`). Compare against the harness's rule-based marks from Checks run 8 (2/53 and 6/53). This settles how far our examiner sits from the paper's on real answers, and counts how many judge replies fail to parse (the D2 bound).
- **Optional, sizes D3.** One Candidate × 53 Cases at temperature 0 vs provider default, graded by the same judge.

## Upstream notes

These are differences between inspect_evals v0.20.0 and the [original harness at `aa9b70da`](https://github.com/MMMU-Benchmark/MMMU/tree/aa9b70da92c2825b3d544d1a11b36856bd92f6c3). They are recorded here, not counted as ours.

- **Grading process: rule-based matcher vs an LLM judge.** The harness lower-cases the reply and keeps the text after the last "is / so / therefore / answer …". It pulls out every number, rounds numbers to 2 decimals, and credits the Case if a normalised gold string is a substring of a prediction or a gold number equals one (`fork:mmmu/utils/eval_utils.py:76-98,122,191-216`). inspect_evals has `model_graded_fact` graded by the Candidate (`inspect_evals:mmmu/mmmu.py:85`). The bound is `unknown` without the paid run above.
  - The matcher has its own false positive: for a single-letter gold it pads to `" c"` (`:97`). So the wrong reply "I cannot tell from the picture." is credited on Case 2 (`validation_Basic_Medical_Science_10`, gold `C`).
- **Prompt order.**
  - **Harness:** `"{question}\nAnswer the question using a single word or phrase."` (`fork:mmmu/configs/llava1.5.yaml:10-13`, `fork:mmmu/utils/data_utils.py:164`), with LLaVA's image token in front (`fork:mmmu/utils/model_utils.py:34`).
  - **inspect_evals:** the instruction line comes before the question (`inspect_evals:mmmu/mmmu.py:66-69`).

  Bound `unknown` (Candidate behaviour).
- **Pictures.**
  - **Second picture:** the harness passes only `image_1` (`fork:mmmu/utils/data_utils.py:100`), so on Case 43 (`validation_Manage_20`, two pictures) the harness model never saw the second. inspect_evals sends all seven slots (`inspect_evals:mmmu/utils.py:75`). Bound ≤ 1/53.
  - **Downscaling:** inspect_evals downscales each picture to fit 1024 px before PNG encoding (`inspect_evals:mmmu/utils.py:39-40`).
- **List-valued golds.** Cases 11, 38 and 48 (`['$MgS$', 'MgS']`, `['Tampa', 'Florida']`, `['24/7', '3.429']`): the harness accepts any listed form. inspect_evals hands the judge the Python-list string as the expert answer (`inspect_evals:mmmu/mmmu.py:151`). Bound ≤ 3/53 = 0.0566, not separable from the judge gap above.
- **Sampling.** The harness's LLaVA run samples with `do_sample=True, temperature=1, num_beams=5, max_new_tokens=128` (`fork:mmmu/utils/model_utils.py:49-53`). Its config's `temperature: 0` (`llava1.5.yaml:14-15`) is never read. inspect_evals fixes temperature 0. The paper's API-model numbers came from code not in this repo.
- **Roll-up: agree.** The harness's micro-average over subjects (`fork:mmmu/utils/eval_utils.py:246-255`, `main_eval_only.py:92`) equals inspect's plain mean on every fixed vector to four decimals (Checks run 11, 13). This is the "micro-averaged vs Inspect's accuracy" point inspect_evals' README raises (`inspect_evals:mmmu/README.md:89`). Bound 0.
- **Dataset: agree.** The harness's `answer_dict_val.json` holds the same 53 open ids with the same gold as the Hub at `171b0ef7`. The harness itself loads the Hub with no revision pin (`fork:mmmu/run_llava.py:76`). Bound 0.
- **Row description (not a fidelity dimension).** The description says the 53 questions span "MMMU's 30 subjects". They come from 15 subjects (Checks run 13: `subjects 15`), though the task loads all 30.
