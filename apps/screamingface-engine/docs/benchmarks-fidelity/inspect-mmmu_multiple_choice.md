---
benchmark: inspect-mmmu_multiple_choice
origin: inspect_evals
verdict: unverified
verdict_reason: "Our copy matches inspect_evals on dataset, prompt, answer extraction, metric and roll-up with zero differences on all 847 Cases. The judge dimension does not apply. One possibly-score-changing deviation is open: inspect_evals runs the model at temperature 0 (mmmu.py:60), and this Benchmark sets no temperature (declared in the row's description). Its effect on the score needs a paid run, so the rule gives unverified. inspect_evals and the original MMMU harness mark differently on 847 of 847 Cases, so comparable-to-paper is out either way."
audited: 2026-11-09
audited_at: 43d3942f6
fingerprint:
  benchmark: 5b008891134ef4c1
  harness_url: https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0/src/inspect_evals/mmmu
references:
  paper: https://arxiv.org/abs/2311.16502v4
  original_harness: https://github.com/MMMU-Benchmark/MMMU/tree/aa9b70da92c2825b3d544d1a11b36856bd92f6c3
  inspect_evals: https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0
  inspect_ai: https://github.com/UKGovernmentBEIS/inspect_ai/tree/v0.3.263
parity_test: none
parity_test_reason: "No test compares our marks with inspect_evals' or the MMMU harness's. tests/unit/inspect/test_mmmu_picture_cases.py checks only the rendered Case (pictures first, then both solvers' text), and only over stand-in rows. This audit's answer sheets did the grading comparison by hand."
---

# MMMU (multiple choice) — Fidelity Record

## Verdict

**`unverified`.** The Candidate gets exactly what [inspect_evals](https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0/src/inspect_evals/mmmu) sends, on every one of the 847 Cases:
- the same text, byte for byte;
- the same pictures, byte for byte, in the same order;
- one user message, with no system message.

Grading also matches inspect's own path. On 11 answer sheets per Case (9,317 marks), our scorer adapter and inspect's own solver-plus-`choice()` path disagree on 0 marks. Our roll-up gives the same number as inspect's `accuracy()` to four decimals on six mark vectors.

One deviation stays open. inspect_evals fixes `GenerateConfig(temperature=0)`, and this Benchmark sends no generation settings. The row's description says so (D1). How much that moves marks depends on how the Candidate behaves, so only a paid run can bound it:

`bounds vs inspect_evals = 0/847 (dataset, prompt, extraction, metric, roll-up) + unknown (D1, sampling) → an open possibly-score-changing deviation → unverified`

The paper's number is out of reach in any case. [Yue et al.'s MMMU](https://arxiv.org/abs/2311.16502v4) is graded by the [original harness](https://github.com/MMMU-Benchmark/MMMU/tree/aa9b70da92c2825b3d544d1a11b36856bd92f6c3), which reads answers loosely and guesses at random when it finds none. inspect_evals accepts only `ANSWER: X`. On the same sheets the two mark at least one sheet differently on all 847 Cases:

`inspect_evals vs original harness ≥ 847/847 = 1.0000 > COMPARABLE_TOLERANCE (0.005)` (Upstream notes)

Close D1 with a paid run inside tolerance, or by an owner ruling that the Candidate's sampling is outside the exam. Every other dimension already matches inspect_evals, so the verdict would then be `comparable-to-inspect`.

## Dimensions

| dimension | status | severity | bound | evidence |
|---|---|---|---|---|
| dataset | match | — | — | **Source.** Both sides read the Hub `MMMU/MMMU` at `171b0ef7…`, split `validation`, 30 subject configs (`inspect_evals:mmmu/utils.py:13,89`; ours `apps/screamingface-engine/src/screamingface_engine_inspect/prepare.py:2014-2021`). Our replay made 30 `load_dataset` calls, all at that revision and split, with the real `CaseSourceRecorder` enforcing pins (Checks run 6). **Rows.** The Hub has 900 validation rows, 847 of them `multiple-choice`. inspect's filter (`inspect_evals:mmmu/mmmu.py:44-45`) keeps 847 Samples. We prepared 847 = `case_count` (`prepare.py:2016`). Case ids run 1..847 in inspect's Sample order. **Gold and options.** Our `target` = inspect's target = the Hub `answer` on all 847. Our `choices` = inspect's choices on all 847. Neither list has an extra row (Checks run 9). **Harness.** The MMMU harness's `answer_dict_val.json` has the same 847 multiple-choice ids, with 0 gold mismatches (Checks run 8). |
| prompt | match | — | — | Every Case was rendered both ways, all 847 rather than a sample. Ours ran through Case Preparation's own replay (`captured_case_records` + `prepared_case`, fetch pins enforced). Theirs ran through the real Task's solver chain, `prompt_template(MULT_CHOICE_PROMPT)` then `multiple_choice()` (`inspect_evals:mmmu/mmmu.py:37-40,58`), with a recording generate stub and no model. Result: roles differ `[]`, text parts differ `[]`, picture bytes or order differ `[]`, part order differs `0` (Checks run 9). **Pictures.** 928 pictures over 847 Cases (805 Cases have 1, 23 have 2, 5 have 3, 8 have 4, 6 have 5). All are `data:image/png;base64`. Their bytes equal the PNG files inspect's `ContentImage` points at, and inspect sends those files' raw bytes (`inspect_ai:_util/images.py:171`). The pictures sit before the text because inspect's text setter appends the new text after the pictures (`inspect_ai:model/_chat_message.py:128-129`). **Text.** Every Case starts with `SINGLE_ANSWER_TEMPLATE`, i.e. `ANSWER: $LETTER` (`inspect_ai:solver/_multiple_choice.py:17`), then the eval's "Answer with the option's letter…" line, then the question, then `A) …` options (`:57`). |
| answer extraction | match | — | — | Our adapter calls inspect's own `parse_answers` and `set_choices_based_on_generated_response` (`apps/screamingface-engine/src/screamingface_engine_inspect/scorer_adapter.py:651`). inspect calls them in the `multiple_choice` solver (`inspect_ai:solver/_multiple_choice.py:82,99,108`). Answer sheets: 847 Cases × 11 sheets = 9,317 marks, ours vs inspect_evals → **differing 0** (Checks run 9). The sheets: `ANSWER: G`, `ANSWER: g`, `G`, `(G)`, `The answer is G.`, `ANSWER: (G)`, a reasoning line ending `ANSWER: G`, the gold option's text, `ANSWER: <wrong>`, `ANSWER: G, <wrong>`, and the empty reply. No golden replies exist for this Benchmark (no mmmu file under `tests/unit/inspect/goldens/` or `tests/fixtures/`). |
| metric | match | — | — | Both sides use inspect's `choice()`: the picked letters must equal the target positions (`inspect_ai:scorer/_choice.py:61,104`), and the row names it (`apps/screamingface-engine/src/screamingface_engine_inspect/benchmarks.py:6830`). The same 9,317 marks: 0 differ, and our adapter raised 0 grading failures (Checks run 9). `multiple_correct=False` and `inverted_grade=False` on both sides. |
| roll-up | match | — | — | Ours: `_accuracy` = sum of scores ÷ Cases (`apps/screamingface-engine/src/screamingface_engine_inspect/single_shot.py:1275,1303`). `whole_run_metric_factory` is `None` (Checks run 2). inspect: `accuracy()` = total ÷ count (`inspect_ai:scorer/_metrics/accuracy.py:37`). Six vectors, compared to four decimals: all-1 1.0000/1.0000; all-0 0.0000/0.0000; alternating 0.5006/0.5006; and three harness answer-sheet mark vectors, 0.2586/0.2586, 0.9528/0.9528 and 0.2621/0.2621 (Checks run 10). The harness's `calculate_ins_level_acc` gives the same six numbers (Checks run 11). |
| judge | not applicable | — | — | `imported_benchmark("mmmu_multiple_choice").judge` is `None` (Checks run 2). `choice()` is deterministic, and inspect's `model_graded_fact` judge belongs only to the separate `mmmu_open` Task (`inspect_evals:mmmu/mmmu.py:59` vs `:85`). |
| sampling | deviation | possibly-score-changing | unknown (paid run recommended) | inspect_evals: `config=GenerateConfig(temperature=0)` (`inspect_evals:mmmu/mmmu.py:60`). It sets no `max_tokens`; the run printed `config 0.0 None` (Checks run 5). Ours: no generation settings. The row has no `params`, and its description says "inspect_evals runs the model at temperature 0; this benchmark imposes no generation settings" (`apps/screamingface-engine/src/screamingface_engine_inspect/benchmarks.py:6775-6776`). Attempts: 1 on both sides (ours `BenchmarkDeclaration(... attempts=1)`, inspect's default of one epoch). No seed and no stop sequences on either side. See D1. |

## Deviations

### D1 — inspect_evals' temperature 0 is not applied

- **Declared, but only in the description.** The row's description states it (`apps/screamingface-engine/src/screamingface_engine_inspect/benchmarks.py:6775-6776`), which follows the catalogue's convention for a dropped `task.config` (`docs/plan/2026-10-05-OME-1268-multi-score-benchmarks.md:70`, decision D10). The row has no `# NAMED DEVIATION` comment line. The MATH row has the matching `Named Deviation:` comment (`benchmarks.py:4189`), so a reviewer may want one here for consistency. Counted as declared and not as a finding. It still counts toward the verdict.
- **Where.** Theirs: `inspect_evals:mmmu/mmmu.py:60`. Ours: no setting exists. The importer never reads `task.config`.
- **What differs.** An inspect_evals run asks the model for temperature 0. Our Candidate answers with its provider's default. Some reasoning models reject or ignore temperature anyway.
- **Severity / bound.** `possibly-score-changing`, `unknown`. It changes what the Candidate writes, not how the reply is marked. Only a paid run can measure the gap.
- **Evidence.** The two source lines above, and Checks run 5 (`config 0.0 None`).

## Checks run

- [x] **Read-only on the checkout.** The audit wrote nothing under the checkout. Every file it made lived under `SCRATCH=/private/tmp/claude-501/…/scratchpad/audit-inspect-mmmu_multiple_choice-gOvW`. `git status --porcelain` was not empty before: it showed `?? docs/work/2026-11-09-fidelity-sweep.md`, the calling session's ledger. After, it also showed seven `docs/benchmarks-fidelity/*.md` records that the calling session wrote during the audit. Filtering those out left nothing (Checks run 13). The scratch folder was removed by the calling session (the audit's own `rm -rf` was blocked by a shell-safety hook).
- [x] **No keys, no model.** `env -i PATH="$PATH" HOME="$SCRATCH" UV_CACHE_DIR="$SCRATCH/uv-cache" env | grep -iE 'key|token|secret'` returned nothing (`grep exit=1`). Every command that ran third-party code used that prefix. Hub loads ran with `HF_HUB_OFFLINE=1` after one anonymous download. inspect's chain ran with a recording `generate` stub, not a model. No model, gateway or provider was called.
- [x] **Harness over paper.** The paper and the harness agree on the extraction rule. The paper's per-model prompts are not in the harness, so the harness's llava config wins (Upstream notes).
- [x] **Declared is not a finding.** D1 is declared in the row's description, as discussed above. No undeclared difference was found.
- [x] **Every cell has evidence.** Each `match` cites its command and output, or two source locations.
- [x] **A verdict never claims more than its evidence.** No dimension is `unchecked`. D1 is open, so the verdict is `unverified`.
- No `ours` override was set.
- Line numbers came from `grep -n` and `awk 'NR>=a && NR<=b'` on each pinned file:
  - ours: `benchmarks.py` (`key="mmmu_multiple_choice"`, `imposes no generation settings`, `scorer=`, `inspect_evals_case_count`), `prepare.py` (`"mmmu_multiple_choice": TaskReplayCasesSpec`, `case_digest=`, `"MMMU/MMMU"`), `scorer_adapter.py` (`set_choices_based_on_generated_response(state, parse_answers`), `single_shot.py` (`^def _accuracy`, `score=round(`);
  - inspect: `mmmu.py`, `utils.py`, `_multiple_choice.py`, `_choice.py`, `accuracy.py`, `images.py`, `_chat_message.py`, all copied from the installed packages;
  - harness: `eval_utils.py`, `data_utils.py`, `model_utils.py`, `llava1.5.yaml`.

1. `git rev-parse --short HEAD` → `43d3942f6`. `git status --porcelain` → `?? docs/work/2026-11-09-fidelity-sweep.md`.
2. Our side, from the Engine root: `env -i … uv run --isolated --extra inspect python -c "imported_benchmark('mmmu_multiple_choice')…"` →
   - `fingerprint 5b008891134ef4c1`, `origin 'inspect_evals'`;
   - `harness_url 'https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0/src/inspect_evals/mmmu'`, `paper_url 'https://arxiv.org/abs/2311.16502'`;
   - `judge None`, `multiple_correct False`, `inverted_grade False`, `whole_run_metric_factory None`;
   - `declaration BenchmarkDeclaration(failure_policy='withhold', interaction='single_shot', difficulty='medium', attempts=1)`;
   - `inspect_evals 0.20.0`, `inspect_ai 0.3.263`, `datasets 5.0.1`.
3. The installed `inspect_evals/mmmu/`, `inspect_ai/{scorer,solver,_util,model}` and `_eval/task/run.py` were copied into scratch for reading.
4. Original harness: `git clone https://github.com/MMMU-Benchmark/MMMU harness && git checkout aa9b70da92c2825b3d544d1a11b36856bd92f6c3`, the commit the inspect_evals README links → `aa9b70da… 2024-09-06 "Update README"`. The repo has no install file, and the eval code needs only `numpy` + `pyyaml`. `env -i … uv venv` + `uv pip install numpy pyyaml` → `numpy 2.5.4`. Paper: arXiv API → latest version `2311.16502v4` (2024-06-13). PDF pp.5-7 read, covering §4 prompts, the "Evaluation" paragraph and Table 2.
5. The Hub `list_repo_tree` at `171b0ef7` gave sizes: validation 341 MB, test 2,958 MB. To avoid the test split, `snapshot_download(allow_patterns=['*/validation-*.parquet'])` fetched the 30 validation files (331 MB). Then `theirs.py`, with `HF_HUB_OFFLINE=1`, built the real `mmmu_task_multiple_choice` over them → `hub validation rows 900 multiple-choice 847`, `inspect samples 847 config 0.0 None`, `cases 847 sheets/case 11 marks 9317`.
6. `ours.py` ran the real task through `CaseSourceRecorder(fetch_pins_of(spec))` + `captured_case_records`, with `datasets.load_dataset` replaced by a reader of the same parquet files. Output:
   - `load_dataset calls 30 revisions ['171b0ef74cd1704464e6940860968009d8cdd59a'] splits ['validation']`;
   - `prepared 847 pinned case_count 847`;
   - `case_digest (this platform) 08e8974a… sealed (linux/amd64) 3fe742a9…`. They differ as the row's comment predicts: Pillow re-encodes pictures differently per platform (`prepare.py:1948-1952`). The seal itself is not re-verified here.
   - `ours marks 9317`.
7. `uv run --isolated --extra inspect pytest tests/unit/inspect/test_mmmu_picture_cases.py tests/unit/test_candidate_input.py -q -p no:cacheprovider` → `56 passed in 271.64s`.
8. `harness.py` ran in the harness venv with `python -I`. It used `construct_prompt` (llava1.5.yaml), `parse_multi_choice_response` and `eval_multi_choice` against `answer_dict_val.json`. Output:
   - `answer_dict rows 900`, `mc in answer_dict 847`;
   - `gold mismatches … []`, `ids in answer_dict mc but not in Cases []`;
   - Case 1 prompt: `"<QUESTION>\n(A) $6\n(B) $7\n(C) $8\n(D) $9\n\nAnswer with the option's letter from the given choices directly."`.
9. `compare.py`:
   - `our Case ids 1..847 in order: True`, schema `screamingface.candidate-input.v2` × 847;
   - `roles differ []`, `text parts differ []`, `image bytes/order differ []`, `part order differs 0`;
   - `images per Case [(1, 805), (2, 23), (3, 5), (4, 8), (5, 6)]`, every one `data:image/png;base64`;
   - `gold mismatches ours/inspect/hub []`, `choices mismatches []`;
   - `ours vs inspect_evals: marks 9317 differing 0`, `our grading failures []`;
   - the inspect-vs-harness per-sheet table (Upstream notes): `Cases with any differing mark 847`.
10. `rollup_ours.py` → `ours _accuracy` = `inspect accuracy()` on every vector: 1.0000, 0.0000, 0.5006, 0.2586, 0.9528, 0.2621.
11. `rollup_harness.py` used per-subject `evaluate` then `calculate_ins_level_acc` over 30 subjects → 1.0000, 0.0000, 0.5006, 0.2586, 0.9528, 0.2621.
12. Worked sheet, Case 1 (`validation_Accounting_1`, gold B). inspect marks / harness parses:
    - `ANSWER: B` → 1 / B;
    - `ANSWER: b` → 1 / A (the harness's lowercase miss falls to its random guess);
    - `B`, `(B)`, `The answer is B.`, `ANSWER: (B)` → 0 / B each;
    - the gold option text → 0 / B;
    - empty → 0 / A (random).
13. `git status --porcelain | grep -v "docs/benchmarks-fidelity/\|docs/work/2026-11-09-fidelity-sweep.md"` → nothing. The audit's `rm -rf "$SCRATCH"` was blocked by a shell-safety hook; the calling session removed the folder afterwards.

## Recommended paid runs

- **D1 (sampling), 847 Cases × 2 arms, no judge.** Pick one Candidate that accepts `temperature=0`. Run all 847 Cases once with `temperature=0` and once with no temperature, then repeat the no-temperature arm once to measure run-to-run noise. Bound = |headline(T=0) − headline(default)| beyond that noise. If the bound is ≤ 0.005, D1 becomes `score-changing` with that bound and the verdict becomes `comparable-to-inspect`. Grading is `choice()`, so no judge tokens are spent. The cost is about 2,541 Candidate calls with pictures.

## Upstream notes

inspect_evals and the original harness differ by far more than the tolerance, on four counts. This is the gap that makes the paper's number unreachable.

- **Answer extraction: 847/847 Cases mark differently on at least one sheet. Bound 1.0000 on these sheets; unbounded in general, because it depends on reply style.**
  - inspect accepts only `ANSWER: X` (`inspect_ai:solver/_multiple_choice.py:99,108`).
  - The harness `parse_multi_choice_response` (`fork:mmmu/utils/eval_utils.py:10`) accepts `(X)` first, then ` X ` (`:29`), then the option's text when the reply is over five words (`:35`). Otherwise it picks a random letter (`:40`), seeded 42 at import (`:6`).
  - Correct marks out of 847, inspect vs harness, with the Cases that differ:

    | sheet | inspect | harness | Cases differing |
    |---|---|---|---|
    | `ANSWER: G` | 847 | 847 | 0 |
    | `ANSWER: g` | 847 | 222 | 625 |
    | `G` | 0 | 847 | 847 |
    | `(G)` | 0 | 847 | 847 |
    | `The answer is G.` | 0 | 847 | 847 |
    | `ANSWER: (G)` | 0 | 847 | 847 |
    | reasoning then `ANSWER: G` | 847 | 847 | 0 |
    | option text | 0 | 807 | 807 |
    | wrong letter | 0 | 0 | 0 |
    | two letters | 0 | 0 | 0 |
    | empty | 0 | 219 | 219 |

  - The harness gives credit for empty replies at random, about 1/k per Case. inspect gives 0.
- **Prompt: different. Bound `unknown`; it changes what the model sees.**
  - The harness's llava config is `{question}\n\n(A) …\n\nAnswer with the option's letter from the given choices directly.` (`fork:mmmu/configs/llava1.5.yaml:3`; `fork:mmmu/utils/data_utils.py:136,146`). It has no `ANSWER:` instruction, and its options are `(A)`-style.
  - inspect puts its `ANSWER: $LETTER` template first, then the "Answer with…" line before the question, with `A)`-style options.
  - Pictures: inspect sends every picture (up to 5 here), shrunk to fit 1024 × 1024 (`inspect_evals:mmmu/utils.py:39,78`). The harness sends only `image_1` (`fork:mmmu/utils/data_utils.py:100`), behind one `<image>` token (`fork:mmmu/utils/model_utils.py:34`). It answers at random when the options hold several pictures (`:64`).
  - The paper (p.5) says each model's own default prompt was used, with prompt engineering on the validation set where a model had none. Only the llava prompt is in the harness, so the harness wins.
- **Sampling: different.** The harness's llava runner uses `do_sample=True, temperature=1, num_beams=5, max_new_tokens=128` (`fork:mmmu/utils/model_utils.py:49-53`). The yaml's `temperature: 0` (`fork:mmmu/configs/llava1.5.yaml:14`) is never read by that call. inspect uses temperature 0 and no token cap.
- **Headline population: different.** The paper's headline is "Validation Overall (900)", which includes the 53 open questions (Table 2, p.6). Some of its rows are "results provided by the authors", i.e. run by the vendors. inspect splits the open questions into `mmmu_open`, so this Benchmark covers the 847 multiple-choice Cases. Their gold equals the harness's `answer_dict_val.json` on all 847 (bound 0 on gold).
- **Roll-up: agrees.** The paper's micro-averaged accuracy (p.6) is the harness's `calculate_ins_level_acc`, a per-subject accuracy weighted by count (`fork:mmmu/utils/eval_utils.py:246,255`). That pooled number equals inspect's plain mean on all six vectors (Checks run 10-11). Bound 0.
- **Paper vs harness: extraction agrees.** The paper's "rule-based … random selection … for multiple-choice questions" (p.6) is the harness's `parse_multi_choice_response`.
