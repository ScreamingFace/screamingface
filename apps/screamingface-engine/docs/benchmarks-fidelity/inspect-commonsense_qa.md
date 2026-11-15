---
benchmark: inspect-commonsense_qa
origin: inspect_evals
verdict: unverified
verdict_reason: "Our copy matches inspect_evals on dataset (apart from the declared, cosmetic row-shuffle seed), prompt, answer extraction, metric and roll-up. All 1,221 Cases have byte-identical prompts, and 0 of 18,315 sheet marks differ. The judge dimension does not apply. One possibly-score-changing deviation is open and undeclared: inspect_evals runs the Task with GenerateConfig(temperature=0) (commonsense_qa.py:44), and our Benchmark applies no generation settings. Only a paid run can bound its effect, so the rule gives unverified. The paper's numbers come from a different process by design: fine-tuned classifiers that take the argmax over five option logits, measured on the hidden test split. So comparable-to-paper is out either way."
audited: 2026-11-09
audited_at: 48fe0ec5b
fingerprint:
  benchmark: 203aa920ad7ad52b
  harness_url: https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0/src/inspect_evals/commonsense_qa
references:
  paper: https://arxiv.org/abs/1811.00937v2
  original_harness: https://github.com/jonathanherzig/commonsenseqa/tree/6f5690bd539b67a4f965d8572aae3ed9195fd4a1
  inspect_evals: https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0
  inspect_ai: https://github.com/UKGovernmentBEIS/inspect_ai/tree/v0.3.263
parity_test: none
parity_test_reason: "No test compares our marks with inspect_evals' marks on the real Cases. The closest pins are tests/unit/inspect/test_inspect_task_replay_benchmarks.py::test_every_judge_less_benchmark_grades_with_no_network[commonsense_qa] (:586) and tests/unit/inspect/test_benchmark_fingerprints.py (the fingerprint, :68). Both passed in this audit. The answer sheets below (18,315 marks per examiner) are the parity evidence."
---

# CommonsenseQA — Fidelity Record

## Verdict

**`unverified`.** The Candidate gets exactly what [inspect_evals v0.20.0 `commonsense_qa`](https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0/src/inspect_evals/commonsense_qa) sends, on all 1,221 validation Cases: the same bytes in one user message, with no system message. Each Case has the same key and the same five options as the Hub rows and as the authors' own `dev_rand_split.jsonl`. Our grading matches inspect's own path too. On 15 answer sheets per Case (18,315 marks), our real served aggregate route and inspect's own `multiple_choice()` solver plus `choice()` scorer disagree on 0 marks. Our headline equals inspect's `accuracy()` to four decimals on eight mark vectors.

D1, the forced row-shuffle seed, is declared and cosmetic. D2 is open, and nothing declares it. inspect_evals pins `GenerateConfig(temperature=0)` on the Task, and our Benchmark applies no generation settings, because the importer never reads `task.config`. This changes what the Candidate writes, not how a reply is marked, so only a paid run can bound it:

`bounds vs inspect_evals = 0/1221 (D1, cosmetic) + unknown (D2, sampling, undeclared, possibly-score-changing) → an open possibly-score-changing deviation → unverified`

The paper's number is out of reach in any case. Talmor et al.'s Table 5 (BERT-large 55.9%, GPT 45.5%, human 88.9%) reports **test-split** accuracy for models **fine-tuned** on CommonsenseQA. Each model picks the argmax of five option logits ([authors' harness](https://github.com/jonathanherzig/commonsenseqa/tree/6f5690bd539b67a4f965d8572aae3ed9195fd4a1)). inspect_evals instead asks a generative model, zero-shot, for an `ANSWER: $LETTER` line on the validation split. These are different examiners by design, and the harness reads logits, not text, so the sheets cannot even be sent through it. `inspect_evals vs original harness = unbounded` (Upstream notes).

There are two ways to close D2. A paid run could show the gap is inside tolerance. Or the owner could rule that the Candidate's sampling is outside the exam, and declare that in the row's description, as other rows already do (`benchmarks.py:3335`, `:4189`). Every other dimension already matches inspect_evals, so the verdict would then be `comparable-to-inspect`.

## Dimensions

| dimension | status | severity | bound | evidence |
|---|---|---|---|---|
| dataset | deviation | cosmetic | 0 | **Seal.** Our in-process replay used the real `CaseSourceRecorder` with `fetch_pins_of(spec)` (`apps/screamingface-engine/src/screamingface_engine_inspect/task_replay.py:404`). It printed `task built: samples 1221`, `captured 1221 Cases`, `case_digest computed 0a4789cb pinned 0a4789cb equal True` and `case_set_digest computed e3b2d5b6 pinned e3b2d5b6 equal True`, against the pins at `apps/screamingface-engine/src/screamingface_engine_inspect/prepare.py:957-966` (Checks run 4). **Hub.** [`tau/commonsense_qa@94630fe3`](https://huggingface.co/datasets/tau/commonsense_qa/tree/94630fe30dad47192a8546eb75f094926d47e155) has train 9741, validation 1221 and test 1140. That is the same revision constant and `split="validation"` as `inspect_evals:commonsense_qa/commonsense_qa.py:23`, `:32-38`. The validation split has 1,221 unique ids, every row labelled `A`…`E` in order (`0 rows not`), no empty `answerKey`, no duplicate question, and keys A 239, B 255, C 241, D 251, E 235. Our ids equal the Hub ids as sets (`True`). Our `target` equals the Hub `answerKey` (`0` differing), our `choices` equal the Hub `choices.text` (`0`), and the Hub question appears in every input (`0` missing) (Checks run 6). **Authors' file.** The harness reads `dev_rand_split.jsonl` (`fork:bert/run_commonsense_qa.py:175`). The authors' S3 copy (1,221 lines, sha256 `3210497f…`) has the same ids as ours as sets (`True`). Taking choices sorted by label, as the harness does (`:214-219`), `answerKey differs 0`, `choices differ 0` and `stem not in our input 0` (Checks run 8). **Order.** This is the only difference: `our order == hub order False`. inspect_evals shuffles without a seed (`commonsense_qa.py:36`, `inspect_ai:dataset/_sources/hf.py:264-265`), and ours forces `shuffle_seed=20260917` (`prepare.py:965`). That is D1, declared. |
| prompt | match | — | — | All 1,221 Cases were rendered both ways. **Ours:** Case Preparation's own capture (`captured_case_records`, `apps/screamingface-engine/src/screamingface_engine_inspect/capture.py:271`) with the pins enforced. **Theirs:** inspect_evals' own Task solver, `multiple_choice()` (`inspect_evals:commonsense_qa/commonsense_qa.py:42`), with the default `SINGLE_ANSWER_TEMPLATE` (`inspect_ai:solver/_multiple_choice.py:17`) and `prompt()` (`:71`). It ran with a recording stub `generate` and no model. Matched by sample id: `Cases whose Candidate input != inspect_evals solver prompt: [] count 0`, roles `('user',): 1221` (Checks run 5, 6). Neither side sends a system message (`system message in any of our Cases 0`). The sha256 of all our inputs, in our order, is `7b9d980e…`. Case 1 starts `Answer the following multiple choice question. The entire content of your response should be of the following format: 'ANSWER: $LETTER' … A,B,C,D,E.` and ends with the options `A) sick` … `E) attack`. |
| answer extraction | match | — | — | Ours calls inspect's own `set_choices_based_on_generated_response(state, parse_answers(state, multiple_correct))` (`apps/screamingface-engine/src/screamingface_engine_inspect/scorer_adapter.py:651`), with `multiple_correct False` (Checks run 2). That is the pair inspect's solver runs after `generate` (`inspect_ai:solver/_multiple_choice.py:82` `parse_answers`, strict regex `:99`, lenient `:108`, last match `:115`, uppercased `:121`; `:155` `set_choices_based_on_generated_response`). Answer sheets: 1,221 Cases × 15 sheets = 18,315 marks per examiner, `total differing 0` (Checks run 6). No golden replies exist for this Benchmark: there is no `tests/unit/inspect/goldens/` directory, and no `tests/fixtures/` file mentions commonsense (Checks run 3). |
| metric | match | — | — | The row's scorer is `inspect_ai.scorer:choice` (`apps/screamingface-engine/src/screamingface_engine_inspect/benchmarks.py:572`), resolved by `_scorer_factory` (`benchmarks.py:8483`). It is the Task's own `choice()` (`inspect_evals:commonsense_qa/commonsense_qa.py:43`; `inspect_ai:scorer/_choice.py:60-61`, `:107`), and `C`/`I` maps to 1.0/0.0 (`scorer_adapter.py:111`). Our marks came from the **real served Benchmark**: a url4 node with the 1,221 prepared Cases installed, every sheet sent through its aggregate route. They equal inspect's marks on all 18,315: `ANSWER_gold` 1221/1221 on both sides, `ANSWER_lower_gold` 1221/1221, `bold_ANSWER_gold` 1221/1221, `ANSWER_paren_gold` 0/0, `bare_gold` 0/0, `the_answer_is_gold` 0/0, `gold_option_text` 0/0, `ANSWER_wrong` 0/0, `two_ANSWER_lines_gold_then_wrong` 0/0, `empty` 0/0, with `ours!=inspect 0` on every sheet (Checks run 6). `test_every_judge_less_benchmark_grades_with_no_network[commonsense_qa]` passed (Checks run 9). |
| roll-up | match | — | — | Ours: `_accuracy`, `round(sum(values) / len(cases), 4)` (`apps/screamingface-engine/src/screamingface_engine_inspect/single_shot.py:1275`, `:1303`), with `whole_run_metric_factory None` (Checks run 2). inspect: `accuracy()` = `total / float(len(scores))` (`inspect_ai:scorer/_metrics/accuracy.py:15`, `:37`), the metric `choice()` declares (`_choice.py:60`). Harness: `tf.metrics.accuracy(label_ids, predictions)`, a plain mean (`fork:bert/run_commonsense_qa.py:608-609`). Eight vectors went through all three, with ours taken as the served aggregate route's `score`. Results: all-1 1.0000; all-0 0.0000; alternating 0.5004; every-3rd 0.3333; and four sheet vectors, 1.0000 / 1.0000 / 0.0000 / 0.0000. Every line printed `equal4 True`, `coverage 1.0` and `scored 1221` (Checks run 7). Note, with no mark change: under `failure_policy="withhold"` (`benchmarks.py:569`), a Case with no grade counts 0 in our denominator, where `inspect eval` would by default stop on a sample error. The sheets carry no failed Case. |
| judge | not applicable | — | — | `imported_benchmark('commonsense_qa').judge` is `None` (Checks run 2). The Task's only scorer is `choice()` (`inspect_evals:commonsense_qa/commonsense_qa.py:43`). The paper and harness grade by argmax against the label (`fork:bert/run_commonsense_qa.py:608`), with no model. |
| sampling | deviation | possibly-score-changing | unknown (D2, paid run recommended) | **inspect_evals:** `config=GenerateConfig(temperature=0)` (`inspect_evals:commonsense_qa/commonsense_qa.py:44`). The built Task printed `config {'temperature': 0.0}` and `epochs None`. The solver's `generate` call carried `{'max_tokens': None}` (`inspect_ai:solver/_multiple_choice.py:247`) (Checks run 4, 5). **Ours:** `BenchmarkDeclaration(failure_policy='withhold', interaction='single_shot', difficulty='easy', attempts=1)`, with `params <none>` (Checks run 2). An `awk` over the row `benchmarks.py:551-606` for `NAMED DEVIATION\|Named Deviation\|temperature\|max_tokens\|top_p\|params\|attempts\|config` printed no line (Checks run 10). Attempts match: 1 on both sides. **Harness/paper:** a fine-tuned classifier with no decoding, so no sampling knob applies. See D2. |

## Deviations

### D1 — row order forced by a declared shuffle seed

- **Declared.** The row's spec says so at `apps/screamingface-engine/src/screamingface_engine_inspect/prepare.py:953` ("Fold: same Cases; order forced by shuffle_seed through inspect's shuffle (D1)"), with `shuffle_seed=20260917` at `:965`. The mechanism is in `docs/spec/2026-10-02-ome-1460-one-fetch-path.md:281` (the D1 row), which lists commonsense_qa under "our row shuffle, upstream unseeded" at `:365`. The Benchmark description says "served in a fixed seeded shuffle (inspect_evals randomizes order per run)" (`apps/screamingface-engine/src/screamingface_engine_inspect/benchmarks.py:561-562`).
- **Where.** Ours: `fetch_pins_of(spec)` (`apps/screamingface-engine/src/screamingface_engine_inspect/task_replay.py:404`) hands the seed to the recorder, which forces it onto the eval's `hf_dataset(shuffle=True)` call. Theirs: `inspect_evals:commonsense_qa/commonsense_qa.py:36` (`shuffle=shuffle`, default `True` at `:30`, no seed), which reaches `inspect_ai:dataset/_sources/hf.py:264-265` (`dataset.shuffle(seed=seed)` with `seed=None`).
- **What differs.** Only the Case numbering. Ours is one fixed permutation of the Hub order, while inspect_evals draws a fresh random permutation per run. Every Case's text, options and key are identical (see the dataset row).
- **Severity / bound.** `cosmetic`, `0`. A Case's mark does not depend on its position: all 18,315 marks match (Checks run 6).

### D2 — inspect_evals' temperature 0 is not applied

- **Undeclared, so this is a finding.** The row (`apps/screamingface-engine/src/screamingface_engine_inspect/benchmarks.py:551-606`) has no `# NAMED DEVIATION` or `Named Deviation` line, and its description (`:555-564`) says nothing about generation settings (Checks run 10). The Task-replay declaration (`prepare.py:957-967`) has none either. There is no `dropped_scorers` and no `excluded_sample_ids` (`excluded_sample_ids=None`, Checks run 2). The catalogue's convention for a dropped `task.config` is a sentence in the row's description, named as a Named Deviation (`docs/plan/2026-10-05-OME-1268-multi-score-benchmarks.md:70`, decision D10). Other rows follow it (`benchmarks.py:3335`, `:4189`). This row does not.
- **Where.** Theirs: `inspect_evals:commonsense_qa/commonsense_qa.py:44`. Ours: no setting exists. A `grep -n "\.config\b\|task\.config\|GenerateConfig"` over `importer.py`, `capture.py`, `task_replay.py`, `prepare.py`, `single_shot.py` and `task_replay_rows.py` hits only a judge-side docstring (`single_shot.py:185`). Capture's stand-in `generate` accepts the generation config and ignores it (`apps/screamingface-engine/src/screamingface_engine_inspect/capture.py:243-247`) (Checks run 10).
- **What differs.** An inspect_evals run asks the model for greedy decoding. Our Candidate answers at its provider's default temperature, so a sampled reply can pick a different letter, or stray from the `ANSWER:` format, which scores 0. Some reasoning models reject or ignore `temperature` anyway.
- **Severity / bound.** `possibly-score-changing`, `unknown`. It changes what the Candidate writes, not how a reply is marked (the marks match on every sheet). Only a paid run can measure the gap.

## Checks run

- [x] **Read-only on the checkout.** `git status --porcelain` before (Checks 1) and after (Checks 11) showed only `?? docs/work/2026-11-09-fidelity-sweep.md`, the ledger the calling session writes into this worktree, as expected. HEAD stayed `48fe0ec5b`. Every file of this audit lived under `$SCRATCH=/private/tmp/claude-501/…/scratchpad/audit-inspect-commonsense_qa-hyP0`, which was deleted at the end with `python3 -c "import shutil, sys; shutil.rmtree(sys.argv[1])" "$SCRATCH"` (`ls` → `No such file or directory`). This report was written outside the repo.
- [x] **No keys, no model.** `env -i PATH="$PATH" HOME="$SCRATCH" UV_CACHE_DIR="$SCRATCH/uv-cache" env | grep -iE 'key|token|secret'` printed nothing (`grep exit=1`). Every command that ran third-party code used that prefix: the clone, the three fetches, and every `uv run --isolated --extra inspect` (through a wrapper script that also set `XDG_CACHE_HOME=$SCRATCH/xdg`, `HF_HUB_DISABLE_XET=1` and `INSPECT_EVAL_MODEL=none/none`). inspect's solver ran against a stub `generate`. The harness was cloned and read, never installed or run: it is TensorFlow 1 and AllenNLP training code whose examiner is a fine-tuned model's logits, and no part of it grades text. No model, gateway or provider was called.
- [x] **Harness over paper.** The harness and the paper agree: both use the random split, accuracy, and argmax over option scores. The gap between inspect_evals and the harness is in Upstream notes.
- [x] **Declared is not a finding.** D1 is declared on the spec, in the spec doc and in the row description. It counts in the bound (0) and is not a finding. D2 is undeclared, so it is a finding.
- [x] **Every cell has evidence.** Each `match` names its command and output lines below.
- [x] **Every `file:line` is copied from command output.** Ours come from `grep -n`, `awk 'NR>=a && NR<=b {print NR": "$0}'` and `sed -n` on the checkout files (Checks 3, 10). The `inspect_evals:` and `inspect_ai:` cites come from `cat -n` and `grep -n` on copies of the installed v0.20.0 / v0.3.263 files (Checks 2). The `fork:` cites come from `grep -n` and `awk` on the clone at `6f5690bd` (Checks 8).
- [x] **A verdict never claims more than its evidence.** No dimension is `unchecked`. One `possibly-score-changing` deviation (D2) is open, so the verdict is `unverified`.
- No `ours` override was set.

1. From the checkout root, `git status --porcelain` → `?? docs/work/2026-11-09-fidelity-sweep.md`, and `git rev-parse --short HEAD` → `48fe0ec5b`. The `env -i … env | grep -iE 'key|token|secret'` check printed nothing (`grep exit=1`).
2. Our side and reference copy, from the Engine root: `run.sh scripts/side.py` (`imported_benchmark('commonsense_qa')`) printed:
   - `fingerprint 203aa920ad7ad52b`, `origin inspect_evals`, `harness_url https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0/src/inspect_evals/commonsense_qa`, `paper_url https://arxiv.org/abs/1811.00937`
   - `params <none>`, `declaration BenchmarkDeclaration(failure_policy='withhold', interaction='single_shot', difficulty='easy', attempts=1)`
   - `judge None`, `multiple_correct False`, `inverted_grade False`, `whole_run_metric_factory None`, `epoch_reducer_factory None`, `named_scores ()`
   - the spec: `shuffle_seed=20260917`, `choice_shuffle_seed=None`, `excluded_sample_ids=None`, `task_args=None`, `source_pins={'tau/commonsense_qa': '94630fe3…'}`
   - versions `inspect_evals 0.20.0 inspect_ai 0.3.263`

   The installed `inspect_evals/commonsense_qa/` and the inspect_ai helpers were copied to scratch and read with `cat -n` and `grep -n`:
   - `inspect_evals:commonsense_qa/commonsense_qa.py` (63 lines): revision `:23`, task `:29-47`, `hf_dataset(... split="validation" ... shuffle=shuffle, revision=…)` `:32-38`, `multiple_choice()` `:42`, `choice()` `:43`, `GenerateConfig(temperature=0)` `:44`, `record_to_sample` `:50-63`
   - `README.md`: `:46` `--temperature 0.5` example, `:65` "1,140 samples", `:81` simple accuracy
   - `eval.yaml`: `:8` `version: "2-A"`, `:11` `dataset_samples: 1221`, `:17` `state: pinned`
   - `inspect_ai:solver/_multiple_choice.py`: `SINGLE_ANSWER_TEMPLATE` `:17`, `prompt` `:71`, `parse_answers` `:82`, regexes `:99`, `:108`, `matches[-1]` `:115`, `.upper()` `:121`, `set_choices_based_on_generated_response` `:155`, `multiple_choice` `:242`, `max_tokens: int | None = None` `:247`
   - `inspect_ai:scorer/_choice.py:60-61`, `:107`
   - `inspect_ai:scorer/_metrics/accuracy.py:15`, `:37`
   - `inspect_ai:dataset/_sources/hf.py:264-265`
3. Our-side line numbers:
   - `grep -n "commonsense_qa"` over `benchmarks.py`, `prepare.py` and `src/screamingface_engine_inspect/*.py` → `benchmarks.py:552`, `:566`, `:571`, `:591`, `:593`; `prepare.py:951-958`, `:963`; `fetch_pins.py:26`
   - `sed -n '545,610p' benchmarks.py`, then `awk` → row `551-606` (`failure_policy` `:569`, `scorer` `:572`, description `:555-564`, the shuffle sentence `:561-562`)
   - `awk 'NR>=951 && NR<=968' prepare.py` → `953` (D1 comment), `957` (spec), `965` (`shuffle_seed`), `966` (`license="mit"`)
   - `grep -n "def _accuracy\|score=round(sum(values) / len(cases), 4)" single_shot.py` → `1275`, `1303`
   - `grep -n "set_choices_based_on_generated_response(state, parse_answers" scorer_adapter.py` → `651`; `_INSPECT_LETTER_SCORE_VALUES` → `111`
   - `grep -n "def _scorer_factory" benchmarks.py` → `8483`; `grep -n "def fetch_pins_of" task_replay.py` → `404`; `grep -n "^def captured_case_records" capture.py` → `271`
   - `grep -n "D1\|commonsense" docs/spec/2026-10-02-ome-1460-one-fetch-path.md` → `281`, `365`
   - goldens: `ls tests/unit/inspect/goldens/` → no such directory; `grep -rln commonsense tests/fixtures` → nothing; `grep -rln commonsense tests/` → `test_benchmark_declaration.py`, `test_case_sources.py`, `test_fetch_pins.py`, `test_failure_policy_rows.py`, `test_published_revisions.py`, `test_importer_command.py` and the fingerprints test, none with recorded replies
4. Our render: `run.sh scripts/ours_render.py` uses `CaseSourceRecorder(cache).install(fetch_pins_of(spec))`, the eval's task function, then `captured_case_records(task, spec)`. That is what `_replay_in_this_process` does, minus the prefetch. Output:
   - `task built: samples 1221 in 6.4 s`, task config `temperature=0.0` with every other field `None`, `epochs None`
   - `captured 1221 Cases in 0.4 s`
   - `case_digest computed 0a4789cb pinned 0a4789cb equal True`, `case_set_digest computed e3b2d5b6 pinned e3b2d5b6 equal True`
   - `first 5 sample ids ['6386bcf0…', '15b09080…', 'c02a3c2d…', '33ea932a…', 'fc1d33a2…']`, `sha256 of all inputs 7b9d980e`
   - Case 1 printed in full: the default template, `A) sick` … `E) attack`, target `E`
5. inspect's examiner: `run.sh scripts/theirs.py` builds `commonsense_qa()` from inspect_evals, then runs every sheet through its own `task.solver` with a recording stub `generate`, then `task.scorer[0]` and `value_to_float()`. Output: `task samples 1221 epochs None config {'temperature': 0.0}`; `solver multiple_choice.<locals>.solve scorers ['choice.<locals>.score']`; `rows 1221 first gen kwargs {'max_tokens': None} roles ['user']`.
6. Ours vs inspect and vs the Hub: `run.sh scripts/ours_grade.py` installs our 1,221 prepared Cases on a `Url4Node` and sends each sheet through `b.aggregate_route`. It printed `{'benchmark_revision': '203aa920ad7ad52b', 'case_count': 1221, 'score': 1.0, 'coverage': 1.0, 'metrics': {'correct': 1221, 'scored_cases': 1221}, 'failures': []}` for `ANSWER_gold`. Then `run.sh scripts/compare.py` (`load_dataset("tau/commonsense_qa", revision="94630fe3…")`, keyed by sample id) printed:
   - Hub: validation `1221 unique ids 1221`, `labels always A-E in order: 0 rows not`, `answerKey dist {'A': 239, 'B': 255, 'C': 241, 'D': 251, 'E': 235}`, `empty answerKey 0`, `duplicate question texts 0`
   - ids and order: `our ids == hub ids as sets True len 1221 unique 1221`, `our order == hub order False`
   - rows: `target != hub answerKey: 0 choices != hub text: 0 hub question not in input: 0`, `theirs ids == ours as sets True`
   - prompt: `Cases whose Candidate input != inspect_evals solver prompt: [] count 0`, `roles theirs Counter({('user',): 1221})`, `system message in any of our Cases 0`, `target/choices ours vs theirs differ 0`
   - marks, 15 sheets: gold as `ANSWER: X`, `ANSWER: X.`, CoT then `ANSWER: X`, `ANSWER: (X)`, `**ANSWER: X**`, `ANSWER: x`, `ANSWER: X,`, `(X)`, bare `X`, `The answer is X.` and the gold option text; then `ANSWER: <next letter>`, `ANSWER: gold` followed by `ANSWER: wrong`, the empty reply, and a no-answer sentence. `ours!=inspect 0` on every sheet; `total marks per examiner 18315 total differing 0`
7. Roll-up: `run.sh scripts/rollup.py` builds each vector as gold or wrong `ANSWER:` replies, then sends it through our served aggregate route, inspect's `accuracy()` on `SampleScore`s, and a plain mean (the harness's `tf.metrics.accuracy`). Every line printed `equal4 True coverage 1.0 scored 1221`:

   | vector | ours | inspect | harness mean |
   |---|---|---|---|
   | all-1 | 1.0000 | 1.0000 | 1.0000 |
   | all-0 | 0.0000 | 0.0000 | 0.0000 |
   | alternating | 0.5004 | 0.5004 | 0.5004 |
   | every-3rd | 0.3333 | 0.3333 | 0.3333 |
   | sheet `cot_then_ANSWER_gold` | 1.0000 | 1.0000 | 1.0000 |
   | sheet `ANSWER_lower_gold` | 1.0000 | 1.0000 | 1.0000 |
   | sheet `ANSWER_paren_gold` | 0.0000 | 0.0000 | 0.0000 |
   | sheet `two_ANSWER_lines_gold_then_wrong` | 0.0000 | 0.0000 | 0.0000 |
8. Original harness and authors' data:
   - `env -i … git clone --quiet https://github.com/jonathanherzig/commonsenseqa harness` → HEAD `6f5690bd539b67a4f965d8572aae3ed9195fd4a1 2019-06-03 "ESIM implementation for commonsenseQA"`. Files: `bert/run_commonsense_qa.py`, `esim/*`. `README.md` points to the website's data and evaluation script, and says the leaderboard uses the `random` split.
   - `awk` on `fork:bert/run_commonsense_qa.py`: `LABELS = ['A'…'E']` `:172`; `DEV_FILE_NAME = 'dev_{split}_split.jsonl'` `:175`; `TEST_FILE_NAME = 'test_{split}_split_no_answers.jsonl'` `:176`; `_create_examples` `:209-230` (stem `:213`, choices sorted by label `:214-219`, `answerKey` → label index `:221`); eval `metric_fn` with `tf.argmax(logits)` and `tf.metrics.accuracy` `:607-612`; test prediction by `np.argmax(prediction)` `:786`.
   - `env -i … curl -sSL https://s3.amazonaws.com/commensenseqa/dev_rand_split.jsonl` (the data file the authors' website links) → 1221 lines, sha256 `3210497fdaae614a…`. `run.sh scripts/authors_vs_ours.py` → `authors rows 1221 unique ids 1221 ids == ours as sets True`, `answerKey differs 0 choices differ 0 stem not in our input 0`. The harness view of Case 1 is `The gimmicky low brow TV show was about animals when they what? ['A:sick', …, 'E:attack'] E`.
9. Tests, from the Engine root:
   - `uv run --isolated --extra inspect pytest tests/unit/inspect/test_benchmark_fingerprints.py -q -p no:cacheprovider -k commonsense_qa` → `1 passed, 94 deselected` (pin `"commonsense_qa": "203aa920ad7ad52b"` at `:68`)
   - `… pytest tests/unit/inspect/test_inspect_task_replay_benchmarks.py -q -p no:cacheprovider -k commonsense_qa` → `1 passed, 145 deselected`. `--co` names it `test_every_judge_less_benchmark_grades_with_no_network[commonsense_qa]` (`:586`). commonsense_qa is not in `_MCQ_KEYS` (`:50`), so the MCQ no-network test does not cover it.
10. Sampling knobs:
    - `awk 'NR>=551 && NR<=606 && /NAMED DEVIATION|Named Deviation|temperature|max_tokens|top_p|params|attempts|config/' benchmarks.py` → no line
    - `grep -n "\.config\b\|task\.config\|GenerateConfig" importer.py capture.py task_replay.py prepare.py single_shot.py task_replay_rows.py` → `single_shot.py:185` only, a judge-seed docstring
    - `sed -n '240,255p' capture.py` → the stand-in `generate` (`:243`) whose docstring says "the generation config are accepted and ignored: no model runs"
    - `grep -n "temperature" benchmarks.py` → description sentences on other rows declaring an unapplied temperature (`:3335`, `:3425`, `:3824`, `:4114`, `:4189`), none on this row
    - `grep -n "D10" docs/plan/2026-10-05-OME-1268-multi-score-benchmarks.md` → `:70`
    - Observation, not a dimension finding: the `fetch_pins.py:26-28` docstring says commonsense_qa's declaration has `shuffle_seed=1234`, but the declaration says `20260917` (`prepare.py:965`). The docstring is stale and no mark depends on it.
11. Paper: `env -i … curl https://arxiv.org/abs/1811.00937` → "Submitted on 2 Nov 2018 … last revised 15 Mar 2019 (this version, v2)". `https://ar5iv.labs.arxiv.org/html/1811.00937` was then read:
    - "We split the data into a training/development/test set with an 80/10/10 split … random split … we consider it the primary split"
    - "We evaluate all models on the test set using accuracy … and tune hyper-parameters … on the development set"
    - Table 5, "Test set accuracy for all models": BERT-large 55.9, GPT 45.5, Human 88.9
    - the human score comes from 100 random questions with five workers each, taken by majority vote
    - BERT/GPT are fine-tuned, "the hidden representations over each [CLS] token are run through a softmax layer"

    Then `git status --porcelain` → `?? docs/work/2026-11-09-fidelity-sweep.md` only, and `git rev-parse --short HEAD` → `48fe0ec5b`. Scratch deleted.

## Recommended paid runs

- **D2, temperature 0.** Run all 1,221 Cases twice with one Candidate that accepts `temperature`, once with `temperature=0` forced and once at the provider default. No judge is needed: grading is deterministic. A headline gap of at most 0.005 bounds D2 inside tolerance. A larger gap means the row should either apply the setting or declare it as a Named Deviation in its description. Either outcome, or an owner ruling that Candidate sampling is outside the exam, closes the `unverified`.

## Upstream notes

- **inspect_evals vs the original harness: a different examiner by design, `unbounded`.** [inspect_evals v0.20.0 `commonsense_qa`](https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0/src/inspect_evals/commonsense_qa) departs from [jonathanherzig/commonsenseqa@6f5690bd](https://github.com/jonathanherzig/commonsenseqa/tree/6f5690bd539b67a4f965d8572aae3ed9195fd4a1) and [Talmor et al. 2019 v2](https://arxiv.org/abs/1811.00937v2) in four ways:
  1. **Split.** The paper's Table 5 is test-split accuracy, measured on the 1,140 hidden-label questions through the [leaderboard](https://www.tau-nlp.org/csqa-leaderboard). inspect_evals uses the 1,221-question validation split, which the authors tuned on (`commonsense_qa.py:34`).
  2. **Examiner.** The harness fine-tunes BERT on the 9,741 training rows and takes `argmax` over five option logits (`fork:bert/run_commonsense_qa.py:607-612`, `:786`). inspect_evals asks a generative model, zero-shot, for `ANSWER: $LETTER` and parses that line (`inspect_ai:solver/_multiple_choice.py:99`, `:108`).
  3. **Prompt.** There is no text prompt in the harness: it encodes `[CLS] question [SEP] choice [SEP]` per choice.
  4. **Human baseline.** The 88.9% comes from 100 test questions, by majority vote of five workers.

  The harness reads logits, not text, so no answer sheet can be marked by both. The gap cannot be bounded without a run, hence `unbounded`. By the sweep's rule, the verdict would be `comparable-to-inspect`, not `comparable-to-paper`, once D2 is closed.
- **Harness vs paper.** They agree on the random split, accuracy, and argmax over option scores. Nothing to record.
- **The row's frontier score is a third process.** `FrontierScore(score=0.858, model="Llama 3.1 405B (pretrained)")` (`apps/screamingface-engine/src/screamingface_engine_inspect/benchmarks.py:598-604`; source the [Llama 3.1 model card](https://github.com/meta-llama/llama-models/blob/main/models/llama3_1/MODEL_CARD.md)) is 7-shot `acc_char` log-likelihood scoring of a pretrained model. That is neither the paper's process nor inspect_evals'. It is a provenance value, not part of this audit's verdict, but a reader should not set our headline beside it as like-for-like.
- **inspect_evals README miscounts the samples.** `inspect_evals:commonsense_qa/README.md:65` says "1,140 samples", which is the test split. The Task loads validation (1,221; `eval.yaml:11` agrees). This is cosmetic and changes no mark.
- **No published inspect_evals number.** The eval's README has no evaluation-report section, so "comparable-to-inspect" would mean comparable to a run of the pinned eval, not to a number inspect_evals printed.
