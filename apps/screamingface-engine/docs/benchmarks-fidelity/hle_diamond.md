---
benchmark: hle_diamond
origin: screamingface
verdict: not-comparable
verdict_reason: "The authors' harness (the reference for a screamingface-origin row) grades with openai o3-mini-2025-01-31, the official JSON judge prompt, structured output and one judging pass; the HLE-Diamond release post that carries the row's Frontier Score names no judge, and the harness at the pin adds no Diamond-specific prompt or judge, so that default is the reference examiner. Ours grades with inspect_evals' maintained regex_judge under openrouter/z-ai/glm-5.3-flash, so by rule (spec §2.3, a judge model other than the one the published number used) our score is reproducible but not the authors' number. Two possibly-score-changing deviations also stay open: the system prompt folded into the user turn (D5) and the judge's fp8 provider pin not sent (D4)."
audited: 2026-11-16
audited_at: 682644804
fingerprint:
  benchmark: 9640c5c7e59fc61e
  harness_url: https://github.com/centerforaisafety/hle/tree/22ed3074b1e7b134bcbc09028d0ba320839b0655
references:
  paper: https://arxiv.org/abs/2501.14249v12
  original_harness: https://github.com/centerforaisafety/hle/tree/22ed3074b1e7b134bcbc09028d0ba320839b0655
  inspect_evals: https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0
  inspect_ai: https://github.com/UKGovernmentBEIS/inspect_ai/tree/v0.3.263
parity_test: tests/unit/inspect/test_hle_diamond_cases.py
parity_test_reason: ""
---

# Humanity's Last Exam: Diamond (HLE-Diamond) — Fidelity Record

## Verdict

**`not-comparable`.** The Cases are exactly the authors' 1,000 Diamond questions, and the Candidate reads exactly what the [CAIS harness](https://github.com/centerforaisafety/hle/tree/22ed3074b1e7b134bcbc09028d0ba320839b0655) sends:
- **The questions:** `cais/hle-diamond` at `04eeb7ef`, which is the Hub's `main` today. The Case Digest recomputes equal from a local copy at that commit (Checks run 7-9).
- **The prompt text:** the harness's 204-byte `SYSTEM_PROMPT` plus the question, on all 1,000 Cases, with the picture's data URI byte-equal on all 272 picture Cases (Checks run 9, 11).
- **The headline:** the harness's accounting, `sum(correct) / n` with an ungradable reply counting 0 (Checks run 13).

**The examiner is not the authors'.** The [paper](https://arxiv.org/abs/2501.14249v12) and the harness grade with `o3-mini-2025-01-31`, the official JSON judge prompt, structured output and one judging pass (`fork:hle_eval/run_judge_results.py:16-53,198`). The [HLE-Diamond release post](https://lastexam.ai/blog/hle-diamond), the source of the row's Frontier Score of 0.743, names no judge, prompt or accounting. The harness's only Diamond-specific file covers the with-tools setting and has no prompt or judge (`fork:docs/evaluation-with-tools.md:1-52`; Checks run 5), so the harness default is the reference.

Ours grades with [inspect_evals' maintained `hle` default](https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0/src/inspect_evals/hle): `regex_judge` under `openrouter/z-ai/glm-5.3-flash`, a paraphrased `GRADE: C/I` prompt, and up to three asks (`apps/screamingface-engine/src/screamingface_engine_inspect/benchmarks.py:7907-7939`). The row says so itself (`benchmarks.py:7865-7866`, "The authors' leaderboard was judged by their own set-up, not this judge"), and the owner decided on 2026-11-10 to keep our judges. Spec §2.3 makes a different judge model `not-comparable` by rule.

Bound arithmetic, for the record:
- `bounds vs original harness = D2 0 + D6 0 + D7 0 = 0/1000 measured`.
- D4 and D5 are `unknown`.
- The judge (D1) differs by design, so the rule's third clause decides, not the sum.

Against inspect_evals' own `hle` Task over the same Diamond rows (not a published number), the audit finds:
- **Samples:** equal on 1,000 of 1,000.
- **Judge prompts:** equal on 3,360 of 3,360 answer sheets.
- **Marks:** equal on 3,330. The other 30 are the lower-case-grade case (D6), which scores 0 on both sides.
- **Whole-run score:** equal to inspect's `original_accuracy` to four decimals on six vectors.

## Dimensions

The reference is the CAIS harness at `22ed307`. Where inspect_evals v0.20.0 (whose `hle` scorer, prompts and helpers this local Task imports) differs from the harness, the cell says so and `## Upstream notes` carries it.

| dimension | status | severity | bound | evidence |
|---|---|---|---|---|
| dataset | match | — | — | **Ours:** `cais/hle-diamond` at `04eeb7efa7e3e4f83a00cbd5ce436a38fd5dda23`, test split, natural order (`apps/screamingface-engine/src/screamingface_engine_inspect/local_tasks/hle_diamond/hle_diamond.py:62-63,79-85`; `apps/screamingface-engine/src/screamingface_engine_inspect/prepare.py:2301`). `case_count=1000`, Case Digest `ba7f9bc0…` (`prepare.py:2295-2296`), no excluded ids.<br>**Local copy:** the Hub-cache snapshot folder is named for the pinned sha, and the parquet's sha256 `2b342190…` equals its LFS blob name. Through our real Task and capture: `prepared 1000`, `case_digest ba7f9bc0bd5b23a0… equal True` (Checks run 7, 9).<br>**Rows:** 1,000 rows with 1,000 unique ids; partition 500 reasoning / 500 knowledge; 796 exactMatch / 204 multipleChoice; 272 with a picture. No empty answer or question. Every Case's target equals the row's `answer` (1,000 of 1,000), Case order = parquet order (`True`).<br>**Theirs:** `load_dataset(args.dataset, split="test")`, unpinned (`fork:hle_eval/run_model_predictions.py:68`, `fork:hle_eval/run_judge_results.py:162`). The card's own call is `load_dataset("cais/hle-diamond", split="test")`. The Hub API today gives `sha 04eeb7ef…` for `main` (Checks run 8), so the harness reads the same 1,000 rows today, and no row is on one side only.<br>**Pictures:** declared MIME matches the magic bytes on 272 of 272. inspect_evals' MIME fix list (`inspect_evals:hle/dataset.py:168-171`) names one Diamond row, `671f2c7d…`, which Diamond already serves as `image/webp` with WEBP bytes, so the fix is a no-op (Checks run 9).<br>**Our README's overlap table checked:** 397 Diamond-only, 603 shared, 80 shared with a different answer, 124 with different question text (`apps/screamingface-engine/src/screamingface_engine_inspect/local_tasks/hle_diamond/README.md:20-31`). One shared question also has a different picture, which the table does not list (Checks run 10). |
| prompt | deviation | possibly-score-changing | unknown | **Text equal, role differs (D5).**<br>**Every Case, in our real capture:** 728 text Cases equal `system_mc + "\n\n" + question`. 272 picture Cases are one user message `[text(system_mc), text(question), image_url]` with the URL byte-equal to the row's `image` (`bad [] 0`, Checks run 9).<br>**Samples:** ours equals inspect_evals' `record_to_sample` on 1,000 of 1,000 (messages minus ids, target, id, metadata plus `partition`; Checks run 9). `system_mc` is the harness's `SYSTEM_PROMPT` byte for byte, 204 bytes (Checks run 11; `inspect_evals:hle/prompts.py:18-22`, `fork:hle_eval/run_model_predictions.py:11`).<br>**What differs:** inspect builds `ChatMessageSystem` + `ChatMessageUser` (`inspect_evals:hle/dataset.py:148-151`). The harness sends the prompt as a system turn (a user turn only for o1 models) and then a user turn `[text, image_url]` (`fork:hle_eval/run_model_predictions.py:13-28`). Ours folds it into the user turn (`apps/screamingface-engine/src/screamingface_engine_inspect/capture.py:75-79`, `apps/screamingface-engine/src/screamingface_engine_inspect/picture_input.py:123-130`).<br>**Pinned by** `test_the_candidate_sees_the_system_prompt_the_question_and_the_picture_bytes` (`apps/screamingface-engine/tests/unit/inspect/test_hle_diamond_cases.py:89`, passed). `partition` never reaches the Candidate (`test_hle_diamond_cases.py:111`, passed). |
| answer extraction | match | — | — | **The same code runs on both sides.** Our scorer is `inspect_evals.hle.scorers:regex_judge` itself (`benchmarks.py:7907`), with kwargs `7911-7916` equal to `inspect_evals:hle/run_configs/default.yaml:29-35` with `graders: [grader]` (`prepare.py:2284-2294`). It hands `model_graded_qa` the grade regex `(?is).*GRADE\s*:\s*([CI])` (`inspect_evals:hle/prompts.py:75`; `inspect_evals:hle/scorers.py:189-195`) and reads the Candidate's **last** `confidence:\s*(\d+)` (`scorers.py:203-210`, clamped at `inspect_evals:hle/metrics.py:41-43`).<br>**Answer sheets on real Diamond rows** (Checks run 12): 1,000 rows × 3 sheets, plus 30 rows (10 exact-answer text, 10 multiple choice, 10 picture) × 15 sheets, 3,360 in all.<br>• Judge prompt bytes equal on 3,360 of 3,360.<br>• Judge call counts equal on 3,360 of 3,360: 3 and 3 on the no-grade, `GRADE: P` and empty sheets, 1 and 1 elsewhere.<br>• Marks the same on 3,330. The 30 others are D6.<br>• Confidence equal on all 2,270 scored sheets: 85→85, none→100, 150→100, two values→last (60), empty→100, bare gold→100, wrong→10.<br>The harness extracts differently by design (judge-side `extracted_final_answer` and `confidence` through a response schema, `fork:hle_eval/run_judge_results.py:24,33,35-40,52`). That belongs to the judge dimension (D1). |
| metric | deviation | cosmetic | 0 | The per-Case rule is C→1, I→0 on both sides. inspect uses `value_to_float` (`inspect_ai:scorer/_metric.py:279`). Ours uses `_INSPECT_LETTER_SCORE_VALUES` (`apps/screamingface-engine/src/screamingface_engine_inspect/scorer_adapter.py:111`, chosen at `:204-211`).<br>An ungradable reply is `NaN` in inspect after `max_grader_attempts` (`inspect_evals:hle/scorers.py:196-201,211-215`) and a failed Case in ours, which counts 0 under `withhold` (`benchmarks.py:7875`). All 1,060 such sheets agree (Checks run 12).<br>**D6 (undeclared, cosmetic):** a lower-case `grade: c` is kept as `"c"` by inspect and read as 0.0 with a warning (`inspect_ai:scorer/_metric.py:337-338`); ours fails the Case with `invalid_score_value`, which also counts 0. The headline mark is 0 on both sides (Checks run 12-13).<br>The harness marks `"yes" in judge_response["correct"]` (`fork:hle_eval/run_judge_results.py:135`), the same 1/0 rule over a different examiner (D1). |
| roll-up | deviation | score-changing | 0 vs the harness; vs inspect's `accuracy`: `unscored/1000`, unknown before a run | **D2, declared** (`benchmarks.py:7920-7923`).<br>**Ours:** `round(sum(values) / len(cases), 4)` over every selected Case, a failed one adding 0 (`apps/screamingface-engine/src/screamingface_engine_inspect/single_shot.py:1288,1316`; `apps/screamingface-engine/src/screamingface_engine/benchmarks/aggregation.py:94-106`).<br>**Harness:** `round(100 * sum(correct) / n, 2)` with `n` = all questions (`fork:hle_eval/run_judge_results.py:148`).<br>**inspect:** the headline `accuracy` drops unscored Cases (`inspect_evals:hle/metrics.py:46-53,66-84`); its `original_accuracy` is the harness's rule (`metrics.py:101-123`).<br>**Six 1,000-Case vectors through all three** (Checks run 13):<br>• all-C 1.0000, all-I 0.0000 and alternating 0.5000: equal everywhere.<br>• Every 10th unscored: ours 0.5000 = `original_accuracy` 0.5000 = CAIS 0.5000; inspect `accuracy` 0.5556.<br>• 3 lower-case `c`: 0.9970 on all four.<br>• C/I/unscored by i%3: ours 0.3340 = `original_accuracy` = CAIS; inspect `accuracy` 0.5007.<br>**Not reproduced:** the harness's Calibration Error (`:151`) and inspect's `stderr`, `cerr` and `unscored`. The row's description declares this (`benchmarks.py:7861`); none of them feeds the headline. The confidence mean is a second Named Score (`benchmarks.py:7910`). |
| judge | deviation | different examiner by design (vs the harness); possibly-score-changing (vs inspect_evals) | unknown | **Ours** (Checks run 3; `max_tokens` is 131072 since OME-1939, **D8**): `JudgeSpec(model='openrouter/z-ai/glm-5.3-flash', params=(('temperature','0'), ('max_tokens','32768'), ('web_search','false')), model_role='grader', redraw_repeats=True)` (`benchmarks.py:7924-7940`). It is identical to the `hle` row's, pinned by `test_hle_diamond_is_judged_exactly_as_hle_is` (`apps/screamingface-engine/tests/unit/inspect/test_hle_diamond_cases.py:144`, passed).<br>**inspect's `grader` in `default.yaml`:** the same model, `temperature: 0`, `max_tokens: 32768`, plus `provider: quantizations: [fp8]` (`inspect_evals:hle/run_configs/default.yaml:44-51`). Our gateway cannot send that pin (**D4**, declared at `benchmarks.py:7929-7931`). `default.yaml` also runs a backup judge (`default.yaml:53-57`) that we do not run (**D3**, declared at `benchmarks.py:7927-7928`).<br>**Judge prompt bytes:** ours equals inspect's on 3,360 of 3,360 sheets (Checks run 12), and on the picture row in `test_the_judge_reads_the_question_byte_for_byte_as_inspect_s_judge_does` (`test_hle_diamond_cases.py:128`, passed).<br>**The harness's judge:** `o3-mini-2025-01-31` (`fork:hle_eval/run_judge_results.py:198`), the 1,290-byte JSON prompt (`:16-33`, byte-equal to inspect's `json_judge` prompt, Checks run 11), `response_format=ExtractedAnswer` (`:35-40,52`), `max_completion_tokens=4096` (`:48`), one pass. inspect's paper-faithful `original.yaml` carries the same (`inspect_evals:hle/run_configs/original.yaml:20-25,33-36`).<br>**The release post** names no judge (Checks run 6). See D1. |
| sampling | match | — | — | **Ours:** no `params` on the row (`imported_benchmark("hle_diamond").benchmark.params` absent, Checks run 3; description "No generation settings are imposed", `benchmarks.py:7866-7867`), `attempts=1`, `interaction='single_shot'` (no tools). The Task takes inspect's `generate(tool_calls="none")`, a `GenerateConfig` of nulls and `Epochs(1, attempt_preserving_mean())` (`hle_diamond.py:93-100`; `inspect_evals:hle/run_configs/default.yaml:37-40,59-62`). `test_the_task_asks_and_grades_as_inspect_evals_hle_does` (`apps/screamingface-engine/tests/unit/inspect/test_local_task_hle_diamond.py:160`, passed) pins it equal to inspect's `hle()`.<br>**Harness:** the request's temperature line is commented out (`fork:hle_eval/run_model_predictions.py:36`). `--max_completion_tokens` is a runner argument (`:37,109`), and the README recommends ≥ 8192 for reasoning models (`fork:README.md:32`).<br>**Release post:** "without tools", "All models are evaluated with reasoning high" (Checks run 6). That is a per-Candidate setting the harness leaves to the runner; a run compared with the 0.743 Frontier Score needs the Candidate at reasoning high with no tools. Both sides impose nothing. |

## Deviations

### D1 — the judge is not the authors' examiner

- **Declared.** The row's description says so (`apps/screamingface-engine/src/screamingface_engine_inspect/benchmarks.py:7865-7866`). The judge comment records the owner's choice (`:7925-7926`, OME-1478, 2026-11-02), and the local Task's README describes the judge (`apps/screamingface-engine/src/screamingface_engine_inspect/local_tasks/hle_diamond/README.md:40-47`). Owner decision 2026-11-10: keep our judges; differences only in the judge stay `not-comparable`.
- **Where.**
  - Ours: `benchmarks.py:7907-7939`, which runs `inspect_evals:hle/scorers.py:166-233` with `inspect_evals:hle/prompts.py:43,66-75`.
  - Theirs: `fork:hle_eval/run_judge_results.py:16-64,198`.
- **What differs.**
  - Model: `glm-5.3-flash` vs `o3-mini-2025-01-31`.
  - Prompt: a paraphrased prompt with a `GRADE: C/I` line vs the official JSON prompt with an extraction step and a numerical-tolerance clause.
  - Parsing: a regex on free text vs a structured-output schema.
  - Asks: 3 vs 1.
  - Judge `max_tokens`: 131072 vs 4096 (raised from default.yaml's 32768 by OME-1939, see D8).
- **Severity / bound.** A different examiner by design, which settles `not-comparable` by rule (spec §2.3, third clause). Bound `unknown`. A paired judge run could size it but cannot change the verdict (Recommended paid runs).

### D2 — ungradable Cases count 0 in the headline, where inspect's `accuracy` drops them

- **Declared.** `# NAMED DEVIATION` at `benchmarks.py:7920-7923`; `failure_policy="withhold"` at `:7875`; the description at `:7857-7859`.
- **Where.**
  - Ours: `apps/screamingface-engine/src/screamingface_engine_inspect/single_shot.py:1288,1316` and `apps/screamingface-engine/src/screamingface_engine/benchmarks/aggregation.py:94-106`.
  - inspect: `inspect_evals:hle/metrics.py:66-84` (`accuracy`, scored Cases only) vs `:101-123` (`original_accuracy`, every Case).
  - Harness: `fork:hle_eval/run_judge_results.py:148`.
- **What differs.** A Case whose judge reply had no `GRADE` line after three asks is a 0 in our denominator and in the harness's. inspect's headline leaves it out.
- **Severity / bound.** `score-changing`.
  - Against the harness and inspect's `original_accuracy`: `0`. They are identical to four decimals on six vectors (Checks run 13).
  - Against inspect's `accuracy`: `unscored/1000` per run, unknown before a run.

### D3 — inspect's backup judge is not run

- **Declared.** `benchmarks.py:7927-7928`.
- **Where.** `inspect_evals:hle/run_configs/default.yaml:53-57` (`grader_2: openrouter/google/gemini-3.7-flash`). inspect's README calls it a separate column, "not voted or averaged", and says "For a single headline number, use the primary judge" (`inspect_evals:hle/README.md:123,129`).
- **Severity / bound.** `cosmetic`, `0`: no mark in the primary column depends on it. The harness has no backup judge.

### D4 — the judge's fp8 provider pin is not sent

- **Declared.** `benchmarks.py:7929-7931`.
- **Where.** inspect: `inspect_evals:hle/run_configs/default.yaml:46-48`. inspect's README notes that a bound role "does not inherit `model_args` such as the default GLM fp8 provider filter" (`inspect_evals:hle/README.md:131`). Ours sends the model and its params only (`benchmarks.py:7932-7935`).
- **Severity / bound.** `possibly-score-changing`, `unknown`. OpenRouter may serve `glm-5.3-flash` at another precision; only a paired judge run bounds it. Against the harness, D1 already covers it.

### D5 — the system prompt rides inside the user turn

- **Declared at the plugin level, not on the row: a finding for the row.**
  - The plugin declares it: `apps/screamingface-engine/src/screamingface_engine_inspect/capture.py:75-79` ("Named deviation (contracteval pattern)…") and `apps/screamingface-engine/src/screamingface_engine_inspect/picture_input.py:75-78,123-130`.
  - The glossary's Named Deviation entry names "a system message delivered as input text" (`CONTEXT.md:323-326`).
  - The row (`benchmarks.py:7841-7943`) carries no `# NAMED DEVIATION` line for it. The local Task's README section "Asking and scoring" (`README.md:40-47`) says the system prompt "asks for" the answer format but not that it arrives as user text.
- **Where.**
  - Ours: a text Case is `system_mc + "\n\n" + question`; a picture Case is one user message `[text(system_mc), text(question), image_url]`.
  - inspect: `ChatMessageSystem` + `ChatMessageUser` (`inspect_evals:hle/dataset.py:148-151`).
  - Harness: a `system` role (`user` only for o1 models), then a `user` turn (`fork:hle_eval/run_model_predictions.py:23-27`).
- **What differs.** Every byte of text is equal on all 1,000 Cases (Checks run 9), but the Candidate receives the prompt as user text, not as a system turn. The judge never sees it: it quotes the kept Sample question, which equals the row's `question` on 1,000 of 1,000 Cases, and the judge prompt bytes equal inspect's on 3,360 of 3,360 sheets.
- **Severity / bound.** `possibly-score-changing`, `unknown`. A Candidate may follow a system instruction differently from user text. Bounding it needs a paired Candidate run over the 1,000 Cases (Recommended paid runs).
- **After this audit:** the row now declares it with a `# NAMED DEVIATION` comment beside its other deviations, and the README's "Asking and scoring" says so. Comment and prose only; the fingerprint does not move.

### D6 — a lower-case grade letter fails the Case here and scores 0.0 with a warning in inspect

- **Undeclared.** A finding, cosmetic for the headline.
- **Where.**
  - inspect: the regex is case-insensitive (`(?is)`, `inspect_evals:hle/prompts.py:75`), so `grade: c` yields `"c"`. `regex_judge` keeps it (`inspect_evals:hle/scorers.py:211-215`). `value_to_float` returns 0.0 and logs "Unable to convert value to float: c" (`inspect_ai:scorer/_metric.py:328,337-338`). `_scored` keeps the Case (`inspect_evals:hle/metrics.py:46-53`).
  - Ours: the letter map is case-sensitive for this row (`scorer_adapter.py:111,204-211`), giving `invalid_score_value`, a failed Case and 0 under `withhold`.
- **Severity / bound.** `cosmetic`, `0`. All 30 such sheets mark 0 on both sides, and the vector with 3 lower-case `c` gives 0.9970 on all four aggregators (Checks run 12-13). The bookkeeping differs: our coverage shows a failed Case, while inspect's `unscored` count stays 0. A lower-case **c** is a *correct* verdict that both sides mark 0; see Upstream notes.

### D7 — the local Task's own lines: `partition` kept, inspect's version labels left out

- **Declared.** The README section "What is ours" (`README.md:33-38`) and the module's `OURS` comments (`apps/screamingface-engine/src/screamingface_engine_inspect/local_tasks/hle_diamond/hle_diamond.py:70-72,101-102`).
- **What differs.**
  - Each Sample's metadata also carries the row's `partition` (`hle_diamond.py:72`).
  - The Task leaves out inspect's `version=` and `metadata=` labels (`:101-102`).
  - The README says "One line" is ours, but the module marks two.
- **Severity / bound.** `cosmetic`, `0`.
  - `partition` sits in private Grading Material only. It never appears in a Candidate input (`test_hle_diamond_cases.py:111`, passed) and never in a judge prompt (bytes equal on 3,360 of 3,360).
  - The labels are not part of any Case.
- **After this audit:** the README's "What is ours" now names both lines.

### D8 — the judge may write 131072 tokens, not default.yaml's 32768

- **Declared.** `# NAMED DEVIATION (OME-1939)` on the row's judge params (`apps/screamingface-engine/src/screamingface_engine_inspect/benchmarks.py`, the `hle_diamond` row's `JudgeSpec`, shared with `hle`). Added 2026-11-17, after this audit; not re-audited.
- **What differs.** Ours pins `max_tokens 131072`, `glm-5.3-flash`'s output limit on OpenRouter (checked 2026-11-17). inspect_evals' `default.yaml` pins `32768` (`default.yaml:44-51`). The run binds the `grader` role with the row's pins, so the stanza fills only the settings they leave unset (`judge_provider.py`, `_pinned_generation_settings`).
- **Why.** On about 1.5% of Cases the judge spent all 32,768 tokens reasoning and wrote no `GRADE:` line after 3 attempts, so the Case counted 0 whatever the Candidate answered (D2's accounting).
- **Severity / bound.** `possibly-score-changing`. Bound: only Cases whose judge needed more than 32,768 tokens can change, measured on `hle`, not yet on `hle_diamond`; every other Case gets the same judge reply. Pinned by `tests/unit/inspect/test_judge_settings_the_wire_carries.py` (`test_a_run_binds_hles_judge_role_with_the_rows_raised_cap`).

### D9 — one picture is shrunk from 14950×2780 px to 8000×1488 px

- **Declared.** `# NAMED DEVIATION (OME-1970)` on the row's `TaskReplayCasesSpec` (`apps/screamingface-engine/src/screamingface_engine_inspect/prepare.py`, `shrunk_picture_sample_ids=HLE_OVERSIZED_PICTURE_SAMPLE_IDS`). Added 2026-11-26, after this audit; not re-audited.
- **What differs.** Case 35 (Hub row `66f1b940f8bb4425f74e4299`, Sample id `hle_350ce3fb`) carries its picture at 8000×1488 px: Pillow LANCZOS to a long side of 8000, aspect kept, lossless PNG re-encode, RGBA kept (991,800 → 671,068 base64 bytes). inspect_evals and the CAIS harness send the original 14950×2780 px. The question, the answer key and the other 999 Cases are byte-identical: main's and the branch's Cases compared by Case id on linux/amd64 differ only in Case 35's picture. Case Digest `ba7f9bc0…` → `822e5531…`.
- **Why.** On the 6 Nov 2026 prod HLE runs no Claude Candidate could read the original (400 "The upstream provider rejected the request."; Claude takes at most 8000 px per side), nor gpt-6-astra-pro or gpt-6.1-terra-pro ("requires 40716 patches after processing, exceeding the limit of 30000"), so the Case counted 0 for them whatever they knew. It is the only picture over 8000 px in the dataset at the pinned revision (a scan of every row, 2026-11-26).
- **Severity / bound.** `possibly-score-changing`, bound `0.001`: one Case of 1,000. A model that read the original reads a smaller copy of the same picture; a model that refused it can now answer.
- **Pinned by** `tests/unit/inspect/test_shrunk_pictures.py` (the shrink, its refusals when stale, and the real Task serving the row at 8000 px).

## Checks run

- [x] **Read-only on the checkout.**
  - At the start, `git status --porcelain` listed 11 entries (7 `M`, 4 `??`): the calling session's uncommitted OME-1863 work, with HEAD at `8ae0d124d`.
  - During the audit the session committed `a7e78f15f` (feat) and `682644804` (ledger, mirror and the frontier-score comment). `git diff --stat a7e78f15f 682644804 -- apps/screamingface-engine/src` shows `benchmarks.py | 7 ++++---`, a comment only.
  - At the end, `git status --porcelain` was empty and HEAD was `682644804`. This audit wrote nothing in the repo; pytest ran with `-p no:cacheprovider` and `PYTHONDONTWRITEBYTECODE=1`.
  - The fingerprint was `9640c5c7e59fc61e` at both ends. Every line number in this record was taken at `682644804`.
  - Every file this audit created lived under `$SCRATCH=/private/tmp/claude-501/…/scratchpad/audit-hle-diamond-8hQt`, deleted at the end.
- [x] **No keys, no model.**
  - `env -i PATH="$PATH" HOME="$SCRATCH" UV_CACHE_DIR="$SCRATCH/uv-cache" env | grep -iE 'key|token|secret'` → empty (`grep exit=1`).
  - The user shell carried `GEMINI_API_KEY`, `GEMINI_CLI_IDE_AUTH_TOKEN` and `CLAUDE_CODE_MESSAGING_TOKEN`.
  - Checks run 3 and 4 ran as `env -u GEMINI_API_KEY -u GEMINI_CLI_IDE_AUTH_TOKEN -u CLAUDE_CODE_MESSAGING_TOKEN -u HF_TOKEN uv run --isolated --extra inspect …` under the real HOME. They only imported the catalogue and copied package files, with no Hub call, but the Hub token file under that HOME was readable to those two processes.
  - Every later command (the clone, curl, every script, pytest) ran under `env -i PATH="$PATH" HOME="$SCRATCH" …`. The Engine-side ones added `HF_HOME="$SCRATCH/hf" HF_HUB_OFFLINE=1 HF_DATASETS_OFFLINE=1`, and the ones that read the dataset copy added `python -I`.
  - Departure from the prefix: `UV_CACHE_DIR` pointed at the user's existing uv cache (read-only use for wheels), not at an empty `$SCRATCH/uv-cache`.
  - The Hub token was never read, printed or passed. The harness scripts were read, never executed, since they call OpenAI.
  - Every judge and Candidate in the answer sheets is inspect's `mockllm/model` or a canned solver. No model, gateway or provider was called.
- [x] **Harness over paper.** The harness's `system_mc` and `sum(correct)/n` are the reference. The paper's v1 exact-answer prompt was never sent by the harness (Upstream notes).
- [x] **Declared is not a finding.**
  - D1, D2, D3 and D4 are declared on the row, and D7 in the README and the module.
  - D5 is declared at the plugin level but not on the row: a finding.
  - D6 is undeclared: a finding.
- [x] **Every cell has evidence.** Each `match` and `deviation` names its command and output, or the two source locations.
- [x] **Every `file:line` is copied from command output.** The `grep -n` and `sed -n` commands are listed at the end of this section.
- [x] **Every citation names its tree.** The prefixes are defined below.
- [x] **A verdict never claims more than its evidence.** No dimension is `unchecked`. D4 and D5 are open `possibly-score-changing` deviations; the judge rule gives `not-comparable` first.
- No `ours` override was set.
- **Gated dataset: option 1, a local copy at the pin.** The Hub-cache snapshot folder `datasets--cais--hle-diamond/snapshots/04eeb7efa7e3e4f83a00cbd5ce436a38fd5dda23` was copied into `$SCRATCH`; the Case Digest was recomputed from the copy and is equal.

Tree prefixes:
- `fork:` = [centerforaisafety/hle at `22ed3074b1e7b134bcbc09028d0ba320839b0655`](https://github.com/centerforaisafety/hle/tree/22ed3074b1e7b134bcbc09028d0ba320839b0655).
- `inspect_evals:` = the installed `inspect_evals` 0.20.0 package.
- `inspect_ai:` = the installed `inspect_ai` 0.3.263 package.
- The dataset card is cited by URL, [cais/hle-diamond at `04eeb7ef`](https://huggingface.co/datasets/cais/hle-diamond/tree/04eeb7efa7e3e4f83a00cbd5ce436a38fd5dda23), with no line numbers.

1. `git status --porcelain` → the 11 entries above; `git rev-parse --short HEAD` → `8ae0d124d` (worktree `.claude/worktrees/OME-1863-hle-diamond`).
2. The key check above → empty.
3. Our side, from the Engine root, `uv run --isolated --extra inspect python -c "…imported_benchmark('hle_diamond')…"`:
   - `id hle_diamond`, `fingerprint 9640c5c7e59fc61e`, `origin screamingface`.
   - `harness_url https://github.com/centerforaisafety/hle/tree/22ed3074b1e7b134bcbc09028d0ba320839b0655`, `paper_url https://arxiv.org/abs/2501.14249`.
   - `declaration BenchmarkDeclaration(failure_policy='withhold', interaction='single_shot', difficulty='hard', attempts=1)`.
   - `judge JudgeSpec(model='openrouter/z-ai/glm-5.3-flash', params=(('temperature','0'),('max_tokens','32768'),('web_search','false')), model_role='grader', seed_per_pass=False, redraw_repeats=True)`.
   - `params <absent>`, `named_scores ('score','confidence')`, `case_count 1000`.
   - The `hle` row printed the same declaration and judge.
   - `inspect_evals 0.20.0`, `inspect_ai 0.3.263`.
4. Copied the installed `inspect_evals/hle` and `inspect_evals/utils` packages and inspect_ai's `scorer/` and `solver/` into `$SCRATCH`. Every `inspect_evals:` and `inspect_ai:` line number comes from `cat -n` or `grep -n` on those copies.
5. The harness clone:
   - `git clone https://github.com/centerforaisafety/hle harness && git checkout 22ed3074…` → `22ed307 2026-09-23 Block all jsDelivr hosts…`.
   - `git log --oneline -12`: `1001c32 Document HLE-Diamond tool evaluation settings and blocklist`, `73ae974`, `26dca2e Create hle-rolling-changes.txt`, `67b3251 Unify system prompt`.
   - `git diff --stat 26dca2e 22ed307` → only `docs/blocklist.json`, `docs/evaluation-with-tools.md`, `docs/requirements-tools.txt` and `hle-rolling-changes.txt`. Nothing under `hle_eval/` or in `README.md`.
   - `grep -rn -i diamond --exclude=blocklist.json .` → only `docs/evaluation-with-tools.md:1:# Evaluating HLE-Diamond with tools`. That file covers the sandbox, web tools, blocklist and provider harnesses only (`:3-52`), with no prompt and no judge.
   - No install: nothing in the harness is run.
6. Under `env -i`:
   - `curl -sL https://lastexam.ai/blog/hle-diamond` → `200`. The extracted text contains "We compare the performance of current models on HLE-Diamond without tools.", "All models are evaluated with reasoning high.", Claude Fable 5.2 74.3% (reasoning 79.4%, knowledge 69.2%), and a with-tools table. `grep -i "judge\|grad\|o3\|prompt\|temperature"` → no judge, prompt or temperature named.
   - `curl -sL https://arxiv.org/abs/2501.14249` → "last revised 19 Oct 2026 (this version, v12)".
7. The local copy:
   - `cp -RL ~/.cache/huggingface/hub/datasets--cais--hle-diamond/snapshots/04eeb7efa7e3e4f83a00cbd5ce436a38fd5dda23 $SCRATCH/data/`.
   - `shasum -a 256 …/test-00000-of-00001.parquet` → `2b3421909ac47580d8373d4e7e5a23f0f08365d2cfb54a13100ddfac4a961e87`, equal to the blob filename in the cache's `blobs/`.
   - Card header `license: mit`. The card says "500 reasoning questions and 500 knowledge questions, indicated by the `partition` column. All other columns follow the HLE format."
8. The Hub API without a token, under `env -i`:
   - `curl https://huggingface.co/api/datasets/cais/hle-diamond` and `…/revision/04eeb7ef…` → both `sha 04eeb7efa7e3e4f83a00cbd5ce436a38fd5dda23`, `gated auto`, `lastModified 2026-09-24T21:30:53.000Z`, `license mit`, siblings `.gitattributes, README.md, data/test-00000-of-00001.parquet`.
   - `curl -I …/resolve/04eeb7ef…/data/test-00000-of-00001.parquet` → `HTTP/2 401`, `x-error-code: GatedRepo`.
9. `python -I $SCRATCH/scripts/cases.py` (the Engine env, `HF_HUB_OFFLINE=1`). The rows from the local parquet are served as `datasets.load_dataset` through `replay_in_process_over_rows`, so our real Task, inspect's `hf_dataset`, the enforcer and our capture all run:
   - `rows 1000 unique ids 1000`; `partition {'reasoning': 500, 'knowledge': 500}`; `answer_type {'exactMatch': 796, 'multipleChoice': 204}`; `with image 272`; `empty answer 0 empty question 0`.
   - `image headers {png 186, jpeg 81, webp 4, gif 1}`; `mime mismatches 0`; `ids in inspect_evals _MIME_TYPE_FIXES ['671f2c7debcbc34ccb44613b']`, whose header is `data:image/webp;base64` with magic `RIFF…WEBP`.
   - `samples ours vs inspect_evals differing (beyond partition) 0 of 1000`.
   - `prepared 1000 case_digest ba7f9bc0bd5b23a0635a2b1082aa0035f7bb43ad51662a87274ea38f1bc5aa3b declared ba7f9bc0… equal True`.
   - `text Cases equal system_mc+\n\n+question 728`; `picture Cases [text(system_mc), text(question), image_url == row image] 272`; `bad [] 0`.
   - `targets equal row answer 1000`; `partition equal 1000`; `order = parquet order True`; `kept sample_input == question 1000`; `system_mc len 204`.
10. A comparison with `cais/hle` at `5a81a4c7…`, copied from the Hub cache: `hle rows 2500 diamond rows 1000 diamond-only 397 shared 603`; `shared with different answer 80`; `shared with different question text 124`; `shared with different image 1`.
11. `python3 -I $SCRATCH/scripts/prompt_bytes.py` (AST-extracted constants, no import): `CAIS SYSTEM_PROMPT in inspect_evals prompts.py constants: True len 204`; `CAIS JUDGE_PROMPT in inspect_evals prompts.py constants: True len 1290`. That second constant is `json_judge` (`inspect_evals:hle/prompts.py:79-82`), not the `regex_judge_template` our row uses (`:43`).
12. Answer sheets, `python -I $SCRATCH/scripts/sheets.py`:
   - **The sheets.** All 1,000 real Diamond rows get 3 sheets each: `GRADE: C` over a gold reply, `GRADE: I` over a wrong one, and a judge reply with no grade. 30 rows (10 exact-answer text, 10 multiple choice, 10 picture) get 9 judge sheets (`C`, `I`, prose then `C`, `C` then `I`, `grade: c`, `P`, `GRADE:C`, empty, no grade) plus 6 Candidate sheets judged `GRADE: C` (confidence none / 150 / two values / empty, the bare gold, a wrong answer). Total 3,360.
   - **The setup.** inspect's side is `eval()` over inspect_evals' own `record_to_sample` Samples, with a canned Candidate solver and a mock judge in the `grader` role whose reply is chosen by a sheet marker in the prompt. Our side is `inspect_grade_case(regex_judge(**kwargs), named_scores=("score","confidence"))` over the 1,000 prepared Cases with the same mock judge.
   - **Results:** `SUMMARY sheets 3360 same outcome 3330 differing 30 judge_prompt_bytes_equal 3360 judge_call_counts_equal 3360`; `differing by sheet {('j_lower_c','conf85'): 30}` (theirs `raw:c`, ours `invalid_score_value`); `confidence equal 2270 differ 0`; `judge calls … (j_P,3,3) 30, (j_empty,3,3) 30, (j_nograde,3,3) 1000`, and 1 and 1 on every other sheet.
13. Whole-run score, `python -I $SCRATCH/scripts/rollup.py`. Ours is `finalize_candidate_result(scorer=_accuracy, failure_policy="withhold")` over `scored_case_result` / `failed_case_result`; inspect's is `accuracy()`, `original_accuracy()` and `unscored()`; CAIS is `round(100*sum(correct)/n, 2)/100`.
   - `all C` 1.0000 ×4; `all I` 0.0000 ×4; `alternating` 0.5000 ×4.
   - `every 10th unscored` ours 0.5000, inspect accuracy 0.5556, original_accuracy 0.5000, unscored 100, CAIS 0.5000.
   - `3 lower-case c` 0.9970 ×4.
   - `C,I,unscored by i%3` ours 0.3340, inspect accuracy 0.5007, original_accuracy 0.3340, unscored 333, CAIS 0.3340.
14. `uv run --isolated --extra inspect pytest tests/unit/inspect/test_hle_diamond_cases.py tests/unit/inspect/test_local_task_hle_diamond.py tests/unit/inspect/test_hle_cases.py -q -p no:cacheprovider` → `12 passed` on the uncommitted tree and again at `682644804` (`12 passed, 3 warnings in 19.59s`).
15. `imported_benchmark("hle_diamond").fingerprint` again at the end → `9640c5c7e59fc61e`, `harness_url` unchanged. `git status --porcelain` → empty; HEAD `682644804`. `rm -r "$SCRATCH"` → gone.

`grep -n` and `sed -n` commands behind the citations:
- `sed -n 7841,7945p src/screamingface_engine_inspect/benchmarks.py | cat -n` (offset to absolute lines) and `grep -n "NAMED DEVIATION\|failure_policy\|…"` over that range.
- `grep -n '"hle_diamond": TaskReplayCasesSpec\|"cais/hle-diamond": "04eeb\|case_digest="ba7f9bc0' src/screamingface_engine_inspect/prepare.py` → `2282, 2296, 2301`, with `git diff` of the entry from 2277.
- `grep -n "DATASET_PATH = \|DATASET_REVISION = \|^def record_to_sample\|sample.metadata = \|…" src/screamingface_engine_inspect/local_tasks/hle_diamond/hle_diamond.py` and `cat -n` of the file.
- `grep -n "^## " …/hle_diamond/README.md`.
- `grep -n "^def test_" tests/unit/inspect/test_local_task_hle_diamond.py tests/unit/inspect/test_hle_diamond_cases.py`.
- `sed -n 70,82p src/screamingface_engine_inspect/capture.py`; `sed -n 120,131p src/screamingface_engine_inspect/picture_input.py`; `grep -n -i system` on both files; `sed -n 320,328p CONTEXT.md`.
- `grep -n "_INSPECT_LETTER_SCORE_VALUES\|invalid_score_value\|def inspect_grade_case" src/screamingface_engine_inspect/scorer_adapter.py` with `sed -n 198,212p`.
- `grep -n "def policy_cases\|return tuple(cases) if failure_policy" src/screamingface_engine/benchmarks/aggregation.py`; `grep -n "def _accuracy\|score=round(sum(values) / len(cases), 4)" src/screamingface_engine_inspect/single_shot.py`.
- `cat -n` on `inspect_evals:hle/dataset.py`, `hle.py`, `run_configs/default.yaml` and `original.yaml`; `sed -n 25,148p metrics.py`; `sed -n 166,234p scorers.py`; `grep -n "^def \|^@metric\|^@scorer"` on `metrics.py` and `scorers.py`; `grep -n "system_mc\|regex_judge_template\|…" prompts.py`; `grep -n -i "comparable\|not voted\|primary judge\|model_args\|diamond" README.md`; `grep -n "dataset_samples\|version" eval.yaml`.
- `grep -n "def value_to_float\|value = value.lower()\|Unable to convert value to float\|return 0.0$" inspect_ai/scorer/_metric.py`.
- `cat -n fork:hle_eval/run_judge_results.py`, `cat -n fork:hle_eval/run_model_predictions.py`, `cat -n fork:README.md | sed -n 20,60p` and `cat -n fork:docs/evaluation-with-tools.md`.

## Recommended paid runs

- **D5, system turn vs folded text.** Take one Candidate (reasoning high, no tools) on about 300 Diamond Cases, stratified by partition and picture/text. Produce replies once with `system_mc` as a system turn (inspect's `eval()` over the local Task) and once from our prepared Case input. Judge both with the pinned judge and compare per-Case marks. This costs Candidate plus judge calls, bounds D5, and counts unscored Cases for D2 as a by-product.
- **D4, the fp8 pin.** Judge one Candidate's replies on the same ~300 Cases twice with `glm-5.3-flash` at temperature 0: once through inspect's `default.yaml` route (OpenRouter with `provider.quantizations: [fp8]`) and once through our gateway. The disagreement count bounds D4. This costs judge calls only.
- **Optional: size D1 against the authors' examiner.** Run `original.yaml`'s `o3-mini-2025-01-31` `json_judge` beside ours on the same replies. This would size the gap the verdict already records but cannot change the verdict. The owner noted that model is on OpenRouter only as `:batch`.

## Upstream notes

- **The release post does not say how its table was judged.** [lastexam.ai/blog/hle-diamond](https://lastexam.ai/blog/hle-diamond) (2026-09-22) gives the no-tools and with-tools tables, "reasoning high" and the per-partition split, but names no judge, no Candidate prompt and no accounting. The harness at `22ed307` adds only the with-tools settings for Diamond (`fork:docs/evaluation-with-tools.md:1-52`). Its `hle_eval/` code and README are identical to `26dca2e` (Checks run 5). This record therefore takes the harness defaults (the `system_mc` prompt, the `o3-mini-2025-01-31` JSON judge, `sum(correct)/n`) as the Diamond examiner. That is an inference, not a statement by the authors; the post lists agibenchmark@safe.ai for questions. Bound: none on our side, since the verdict already rests on D1.
- **The harness has no per-partition metric.** The release reports reasoning and knowledge halves, but `dump_metrics` reports only overall accuracy and calibration (`fork:hle_eval/run_judge_results.py:129-155`). The harness README still documents `cais/hle` and an example with `n = 2700` (`fork:README.md:26,44,52`). Diamond's columns are `cais/hle`'s plus `partition`, so `--dataset cais/hle-diamond` runs unchanged. We publish no per-half score either (`README.md:40-47`, owner decision 2026-11-16). This affects no headline.
- **inspect_evals v0.20.0 cannot load Diamond.** Its loader knows only `cais/hle` and `cais/hle-rolling` (`inspect_evals:hle/dataset.py:19-25,62,67`), and its README never names Diamond (`grep -n -i diamond` → no match). That is why this row is a local Task around inspect_evals' `hle`, not an import.
- **inspect_evals' default is a different examiner from the CAIS harness, by design.** It differs in judge model (`glm-5.3-flash` vs `o3-mini-2025-01-31`), prompt (the paraphrased `regex_judge_template` with `GRADE: C/I` vs the 1,290-byte official JSON prompt), parsing (a regex vs structured output, `inspect_evals:hle/scorers.py:189-195` vs `fork:hle_eval/run_judge_results.py:52`), asks (3 vs 1, `inspect_evals:hle/run_configs/default.yaml:35` vs `original.yaml:25`) and judge `max_tokens` (32768 vs 4096). inspect_evals' own README calls default-run scores "not comparable with earlier versions" and keeps `original.yaml` as the paper-faithful config (`inspect_evals:hle/README.md:238-239`). Bound: unbounded by design.
- **The exact-answer prompt was never sent by the harness.** The paper's v1 described two prompts, but the first harness commit sent the multiple-choice prompt to every question, and commit `67b3251` (2025-06-06) made that single `SYSTEM_PROMPT` official (`inspect_evals:hle/prompts.py:21-22,33-34` records the history). The harness wins, and ours equals it byte for byte.
- **Calibration error is not comparable between the harness and inspect_evals, and ours reproduces neither.** The harness drops the top-confidence bin and prints integer percent (`fork:hle_eval/run_judge_results.py:107,151`); inspect keeps every bin (`inspect_evals:hle/README.md:39`). Our second Named Score is the confidence mean, not a calibration error (`benchmarks.py:7859-7861`).
- **A lower-case grade letter scores 0.0 in inspect instead of being left unscored.** inspect's case-insensitive regex (`inspect_evals:hle/prompts.py:75`) accepts `grade: c`, `regex_judge` keeps `"c"`, and inspect_ai's `value_to_float` returns 0.0 with a warning (`inspect_ai:scorer/_metric.py:337-338`). So a correct verdict spelled in lower case counts as incorrect under inspect's `accuracy`. Our path fails the Case instead, the same 0 in the headline (D6). Worth reporting to inspect_evals (upper-case the capture, or add `c`/`i` to the letter map); nothing in our row changes the mark.
- **The release's with-tools numbers come from a different process.** Provider agent harnesses, a sandbox and web tools behind a blocklist produced them (`fork:docs/evaluation-with-tools.md:5-52`). The row's Frontier Score is the no-tools 0.743 (`benchmarks.py:7900-7905`), the right table for a single-shot Benchmark with no tools.
