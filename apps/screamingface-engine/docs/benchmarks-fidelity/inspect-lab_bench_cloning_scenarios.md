---
benchmark: inspect-lab_bench_cloning_scenarios
origin: inspect_evals
verdict: comparable-to-inspect
verdict_reason: ""
audited: 2026-11-09
audited_at: 43d3942f6
fingerprint:
  benchmark: 9c6f66d6acae7f05
  harness_url: https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0/src/inspect_evals/lab_bench
references:
  paper: https://arxiv.org/abs/2407.10362v3
  original_harness: https://github.com/Future-House/LAB-Bench/tree/a767892307ad38a5f4f77cd00d30c2442aaea791
  inspect_evals: https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0
  inspect_ai: https://github.com/UKGovernmentBEIS/inspect_ai/tree/v0.3.263
parity_test: none
parity_test_reason: "No checked-in test grades CloningScenarios Cases through both scorers. tests/unit/inspect/test_inspect_task_replay_benchmarks.py::test_lab_bench_never_keys_every_case_to_one_letter pins only the option shuffle, and test_benchmark_fingerprints.py pins the fingerprint (both passed in this audit). This audit's answer sheets stand in: 33 Cases x 21 replies = 693 marks through our grade hook and through inspect_evals' own solver and scorer, all identical."
---

# LAB-Bench CloningScenarios — Fidelity Record

## Verdict

**`comparable-to-inspect`.** Our headline is plain accuracy over the 33 public Cloning Scenarios. It can sit beside a run of [inspect_evals' `lab_bench_cloning_scenarios` (v0.20.0)](https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0/src/inspect_evals/lab_bench), whose first metric is the same `accuracy()`. It cannot sit beside the [LAB-Bench paper's](https://arxiv.org/abs/2407.10362v3) CloningScenarios numbers (Table 2, p.23: Human 0.60, the seven models 0.09-0.28). Those were measured on all 41 questions, 33 public plus 8 private, averaged over three runs. They were also marked by a different examiner: an `[ANSWER]X[/ANSWER]` prompt, graded by chembench's tag regex with a Claude 2 fallback for every reply without tags.

Against inspect_evals we match on every dimension that can change a mark:
- **Cases:** the 33 Cases reproduce the sealed Case Digest and are inspect_evals' own Samples, in the order its seeded shuffles give.
- **Prompts:** all 33 Candidate inputs equal the prompt inspect_evals' own solver builds, byte for byte.
- **Marks:** 693 of 693 answer-sheet marks are identical.
- **Headline:** our accuracy equals inspect's `accuracy()` to four decimals on 7 mark vectors.

One undeclared, cosmetic deviation exists (D1: we publish accuracy only, not inspect's precision, coverage and stderr). So `sum of bounds against inspect_evals = 0/33 = 0.0000 ≤ COMPARABLE_TOLERANCE (0.005)`.

inspect_evals vs the original harness is above tolerance on the Case set alone: 8 of the 41 Cases behind the published number are private, `bound 8/41 = 0.1951 > 0.005`. On top of that, the prompt and extractor differ (`unknown`, and the harness's extractor calls a model). See Upstream notes. Verdict → `comparable-to-inspect`.


## Dimensions

| dimension | status | severity | bound | evidence |
|---|---|---|---|---|
| dataset | match | — | — | **Ours vs inspect_evals:** our row pins Hub `futurehouse/lab-bench` at `5c77cec6…` (`apps/screamingface-engine/src/screamingface_engine_inspect/prepare.py:1268`). That is inspect_evals' own constant (`inspect_evals:lab_bench/lab_bench.py:33`), with the same subset, split and row rule (`:64-78`, `:139-146`; `inspect_evals:lab_bench/record_to_sample_helpers.py:18-24`). Replaying our Case Preparation gave `cases 33 digest 0e21d741… pinned 0e21d741… equal True` (Checks 3). Comparing our 33 Cases with inspect_evals' unmodified `lab_bench_cloning_scenarios()` as (question, gold text, option set): `rows only ours: 0 rows only inspect default: 0 ids unique: 33` (Checks 5). **Order:** our row forces `shuffle_seed=7` and `choice_shuffle_seed=7` (`prepare.py:1270-1271`) through inspect's own `hf_dataset` (`apps/screamingface-engine/src/screamingface_engine_inspect/case_sources.py:409-412`). inspect_evals itself shuffles rows and options unseeded each run (`inspect_evals:lab_bench/lab_bench.py:67-68,75-76`; `inspect_ai:dataset/_sources/hf.py:131-132,265,285`): `seeded id order == default id order: False`. So our order is one draw of inspect's own shuffle, not a different rule. The mean ignores row order. Option order is covered under sampling. **Hub vs harness files:** on question, ideal and distractors, the Hub pin equals `fork:CloningScenarios/cloningscenarios-v1-public.jsonl` at both `a767892` and `998a8e0`: `rows 33 only hub [] only harness [] differing {}` (Checks 10). |
| prompt | match | — | — | All 33 Cases: inspect_evals' own `task_base` solver (`multiple_choice(template=MULTIPLE_CHOICE_TEMPLATE, cot=True)`, `inspect_evals:lab_bench/lab_bench.py:152`, template `:47-58`) ran on `hf_dataset(…, shuffle=True, seed=7, shuffle_choices=7)` with a stub `generate` that records `state.messages[-1]`. Result: `Cases whose Candidate input bytes != inspect_evals seeded render: []`, `Cases whose choices/target != seeded Sample: []`, sha256 of the joined inputs `a52d1a0fc965c84d` on both sides (Checks 4-5). inspect sends one user message and no system message (`single user message on their side for all: True`; Task config `system_message=None`). Options are written `A) …` by `inspect_ai:solver/_multiple_choice.py:57-68`. The prompt differs from the original harness's. See Upstream notes. |
| answer extraction | match | — | — | Ours replays inspect_ai's own pair, `set_choices_based_on_generated_response(state, parse_answers(state, multiple_correct))` (`apps/screamingface-engine/src/screamingface_engine_inspect/scorer_adapter.py:651`), with `multiple_correct=False` (Checks 2). The solver calls the same pair after `generate` (`inspect_ai:solver/_multiple_choice.py:332-340`; `parse_answers` `:82-152`). One difference in form: on an unparsed reply our adapter marks every option `False` where the solver leaves them `None`. `precision_choice` reads only `correct is True` (`inspect_evals:lab_bench/scorer.py:35-37`), so marks cannot differ. Answer sheets cover 21 reply forms per Case: gold as `ANSWER: X`, after CoT, lower case, with period, `(X)`, prose, the paper's tags, and tags after CoT; wrong; opt-out with and without period; empty; two letters; out of range; changed mind; trailing comma; `answer:x`; inline; wrong / opt-out / lower-case gold in tags. Result: `sheets 561 identical 561 differing 0` and `sheets 132 identical 132 differing 0` (Checks 6-7, 11). |
| metric | match | — | — | Our row's scorer is `inspect_evals.lab_bench.lab_bench:precision_choice` with `no_answer="Insufficient information to answer the question."` (`apps/screamingface-engine/src/screamingface_engine_inspect/benchmarks.py:1747-1748`). That is the Task's own `precision_choice(no_answer=UNCERTAIN_ANSWER_CHOICE)` (`inspect_evals:lab_bench/lab_bench.py:153`; constant `inspect_evals:lab_bench/record_to_sample_helpers.py:13`). Picking the opt-out gives `NOANSWER` (`inspect_evals:lab_bench/scorer.py:39-52`). Otherwise `C` iff the selected positions equal the target (`:54-56`). We map `C/I/N` → 1.0/0.0/0.0 (`scorer_adapter.py:111`), as inspect_ai's `value_to_float` does for `accuracy()` (`inspect_ai:scorer/_metric.py:319-324`). Per sheet kind, inspect/ours: gold forms `C/1.0`, wrong `I/0.0`, opt-out `N/0.0`, unparsed `I/0.0` (Checks 7). 693 of 693 identical. |
| roll-up | deviation | cosmetic | 0 (D1) | **Headline equal:** seven fixed vectors of 33 marks went through our `_accuracy` (`apps/screamingface-engine/src/screamingface_engine_inspect/single_shot.py:1275`, `score=round(sum(values) / len(cases), 4)` at `:1303`; `whole_run_metric_factory` is `None`, Checks 2), inspect_ai's `accuracy()` (`inspect_ai:scorer/_metrics/accuracy.py:15,37`) and the harness's `compute_metrics` (`fork:labbench/evaluator.py:128`). The vectors were all-C, all-I, all-N, alternating C/I, a C/I/N cycle, 10 C + 5 N + 18 I, and one drawn from the answer sheets. Headline on all three: 1.0000 / 0.0000 / 0.0000 / 0.5152 / 0.3333 / 0.3030 / 0.3939 (Checks 12-14). **Not published by us:** inspect's `precision()`, `coverage()` and `stderr()` (`inspect_evals:lab_bench/scorer.py:17`). On the same vectors those gave 0.5000/0.6667, 0.3571/0.8485 and 0.4483/0.8788 for the last three, equal to the harness's precision/coverage (Checks 12, 14). See D1. |
| judge | not applicable | — | — | `imported_benchmark("lab_bench_cloning_scenarios").judge` is `None` (Checks 2). `precision_choice` calls no model (`inspect_evals:lab_bench/scorer.py:17-61`). The original harness does call one: chembench's Claude 2 fallback. That is an inspect-vs-harness difference, see Upstream notes. |
| sampling | match | — | — | Ours: `params None`, `declaration=BenchmarkDeclaration(failure_policy='withhold', interaction='single_shot', difficulty='hard', attempts=1)` (Checks 2). The row sets no `max_tokens`, `temperature`, `params` or `# NAMED DEVIATION` (awk over `benchmarks.py:1722-1785` → none). inspect_evals: Task config all `None` (`max_tokens=None … temperature=None … seed=None`), `epochs 1` with the `mode` reducer (`inspect_evals:lab_bench/lab_bench.py:154`), `generate kwargs: {'max_tokens': None}` (Checks 4). Seeds: ours fixes row and option order with seed 7. inspect_evals leaves both unseeded, and so does the harness (`fork:labbench/utils.py:137`). A knob inspect_evals leaves open, so `match`. The harness's `max_tokens=1024` for Anthropic models and the paper's three-run average are in Upstream notes. |

## Deviations

### D1 — we publish accuracy only; inspect_evals also reports precision, coverage and stderr

- **Undeclared.** The row has no `# NAMED DEVIATION` line, no `dropped_scorers` and no `excluded_sample_ids` (awk over `benchmarks.py:1722-1785`, `sed -n 1253,1274p prepare.py`). No file under `named_deviations/` names lab_bench (`ls … | grep -ci lab` → `0`). The row's description does say "Benchmark score = plain accuracy over the cases run" (`benchmarks.py:1734`), but a description line is not one of the declared forms.
- **Where.** Ours: `_accuracy` publishes one score per run (`single_shot.py:1275-1303`). inspect_evals: `@scorer(metrics=[accuracy(), precision(), coverage(), stderr()])` (`inspect_evals:lab_bench/scorer.py:17`; precision `inspect_evals:lab_bench/metrics.py:80-88`, coverage `:111-116`).
- **What differs.** Only the extra columns. Our 0.0 per-Case score is the same for `I` and `N` (`scorer_adapter.py:111`), so precision and coverage cannot be recovered from our Report. The headline, accuracy, is inspect's first metric and the accuracy table of the paper (Table 2), and it is equal to four decimals (roll-up row).
- **Severity / bound.** `cosmetic`, `0`: no Case's mark and no headline changes.

## Checks run

- [x] **Read-only on the checkout.** HEAD stayed `43d3942f6`.
  - Before (Checks 1): `git status --porcelain` showed three `??` lines (`apps/screamingface-engine/docs/benchmarks-fidelity/frames_oracle.md`, `…/musique.md`, `docs/work/2026-11-09-fidelity-sweep.md`).
  - After (Checks 16): the same three, plus more `?? apps/screamingface-engine/docs/benchmarks-fidelity/*.md` records that the concurrent sweep session wrote while this audit ran (inspect-lab_bench_dbqa, inspect-lab_bench_litqa, inspect-mmlu_pro and others). None names this Benchmark. `git status --porcelain | grep -v 'apps/screamingface-engine/docs/benchmarks-fidelity/\|docs/work/2026-11-09-fidelity-sweep.md' | wc -l` gave `0` mid-audit and after.
  - Every file this audit created lived under `SCRATCH=/private/tmp/claude-501/…/scratchpad/audit-lab_bench_cloning_scenarios-FBET`, and the folder was removed at the end. The constraints file was written there by `uv export --frozen … -o $SCRATCH/constraints.txt`, which reads `uv.lock` and writes nothing in the checkout.
- [x] **No keys, no model.** `env -i PATH="$PATH" HOME="$SCRATCH" UV_CACHE_DIR="$SCRATCH/uv-cache" env | grep -iE 'key|token|secret'` printed nothing (`grep exit=1`).
  - Every command that ran third-party code used that prefix: the inspect_evals venv, the harness venv, `git clone` and `curl` of arXiv. Our-side `uv run --isolated --extra inspect` calls used it too, so the Engine replay also ran with no key in the environment. Scratch-venv Python ran with `-I`.
  - Stub `generate` / `get_completion` functions stood in for every Candidate.
  - chembench's `llm_extraction` (its Claude 2 fallback) was replaced by a stub that raises. `langchain_community` is not even installed in the harness venv (`ModuleNotFoundError`), so no model could have been reached.
  - No Hugging Face token was used: the dataset is not gated.
- [x] **Harness over paper.** Two places where paper and harness disagree are recorded in Upstream notes: the opt-out wording (period or not) and the line layout. Both go the harness's way. The 41-vs-33 Case set is not a paper-vs-harness disagreement: the harness ran on the full files internally.
- [x] **Declared is not a finding.** Nothing on this row is declared. D1 is undeclared. The forced seeds are covered under dataset and sampling as one draw of inspect's own shuffle.
- [x] **Every cell has evidence.** Each `match` names its command and output line, or the two source locations compared.
- [x] **Every `file:line` is copied from command output.** Commands used:
  - `grep -n` on our `benchmarks.py` (`key="lab_bench_cloning_scenarios"`, `scorer=`, `scorer_kwargs=`, `inspect_evals_case_count=33`, `Benchmark score = plain accuracy`), `prepare.py` (spec), `scorer_adapter.py` (`_INSPECT_LETTER_SCORE_VALUES`, `set_choices_based_on_generated_response(state, parse_answers`), `single_shot.py` (`^def _accuracy`, `score=round`) and `case_sources.py` (`forced.get("seed")`, `shuffle_choices") is not`).
  - `sed -n 1261,1272p prepare.py`, `sed -n 1715,1790p benchmarks.py`, `sed -n 600,700p scorer_adapter.py`, `sed -n 1275,1310p single_shot.py`, `sed -n 395,420p case_sources.py`.
  - `grep -n` on the installed `inspect_evals/lab_bench/{lab_bench,record_to_sample_helpers,scorer,metrics}.py`.
  - `grep -n` and Read on `inspect_ai/solver/_multiple_choice.py`, `scorer/_metric.py`, `scorer/_metrics/accuracy.py` and `dataset/_sources/hf.py`.
  - `grep -n` and Read on `fork:labbench/{zero_shot,utils,evaluator,anthropic}.py` and `fork:scripts/score_baseline.py` at `a767892`, and on `chembench:src/chembench/{utils,constant}.py` at `7ad84e63`.
- [x] **A verdict never claims more than its evidence.** `prompt`, `answer extraction`, `metric` and `roll-up` all carry evidence, and no `possibly-score-changing` deviation of ours is open.
- No `ours` override was set.

1. `git rev-parse --short HEAD` → `43d3942f6`, and `git status --porcelain` → the three pre-existing lines (first checkbox).
2. Our side: `uv run --isolated --extra inspect python -c "imported_benchmark('lab_bench_cloning_scenarios') …"`. Output:
   - versions `0.20.0 0.3.263` (inspect-evals, inspect-ai; `apps/screamingface-engine/pyproject.toml:69-70` pins the same), `fingerprint 9c6f66d6acae7f05`, `origin 'inspect_evals'`;
   - `harness_url '…/v0.20.0/src/inspect_evals/lab_bench'`, `paper_url 'https://arxiv.org/abs/2407.10362'`, `judge None`, `params None`;
   - `declaration=BenchmarkDeclaration(failure_policy='withhold', interaction='single_shot', difficulty='hard', attempts=1)`;
   - `whole_run_metric_factory = None`, `whole_run_headline = None`, `multiple_correct = False`, `named_scores = ()`, `extra_scorer_factories = ()`, `inverted_grade = False`, `verdict_grades = None`.
3. Replay: `env -i … HF_HUB_DISABLE_XET=1 uv run --isolated --extra inspect python $SCRATCH/scripts/ours_cases.py` (`replayed_cases(TASK_REPLAY_CASES["lab_bench_cloning_scenarios"])` + `case_digest`) → `cases 33 digest 0e21d7411577ba5b2b946ffd81f89d7b63269e47303228992a1066a531ddf2c7 pinned 0e21d741… equal True`. Grading Material keys `['target', 'choices']`, with no metadata (the row rule sets none).
4. inspect_evals reference venv: `env -i … uv venv --python 3.12` + `uv pip install inspect-ai==0.3.263 inspect-evals==0.20.0`.
   - The first import failed with `ModuleNotFoundError: No module named 'acp.helpers'`. I reinstalled with our lock as constraints (`uv export --frozen --extra inspect`, path lines dropped), which gave `agent-client-protocol 0.12.1`, the Engine's version.
   - `venv/bin/python -I scripts/theirs_cases.py seeded` and `… default` printed `seeded samples 33 epochs 1 [mode_score.reduce] config … system_message=None max_tokens=None … temperature=None … seed=None …`, and `default samples 33 …` the same.
5. Compare: `python3 -I scripts/compare.py` →
   - `ours 33 theirs seeded 33 theirs default 33`;
   - `Cases whose Candidate input bytes != inspect_evals seeded render: []`;
   - `single user message on their side for all: True generate kwargs: {"{'max_tokens': None}"}`;
   - `Cases whose choices/target != seeded Sample: []`;
   - `sha256 ours inputs a52d1a0fc965c84d theirs a52d1a0fc965c84d`;
   - `rows only ours: 0 rows only inspect default: 0 ids unique: 33`;
   - `seeded id order == default id order: False`;
   - `choices per Case: [5, 6, 7, 8, 9] gold letters: BGCCEDEBBEDAACEBCGCBECBDADAACBEGD`;
   - `unsure option present on every Case: True`.
6. Answer sheets: `python3 -I scripts/make_sheets.py` → `sheets 561 per Case 17`. Marked by inspect_evals' own Task solver (stub `generate` returning the sheet) and then its own `task.scorer[0]`: `venv/bin/python -I scripts/sheets_theirs.py` → `theirs marked 561`. No recorded goldens exist for this row: `tests/unit/inspect/goldens/` does not exist, and `find tests -path '*golden*' -iname '*lab_bench*'` and a grep of `tests/fixtures` both found nothing.
7. Our marks: `env -i … uv run --isolated --extra inspect python scripts/sheets_ours.py` (`imported_benchmark(…).aggregation().grade_case` on one `GradeRequest` per sheet, `finish_reason="stop"`) → `ours marked 561`. Then `python3 -I scripts/sheets_compare.py` → `sheets 561 identical 561 differing 0 []`. Per sheet kind, inspect/ours:
   - `C/1.0` × 33 on gold, gold_after_cot, gold_lower, gold_period, wrong_then_gold, gold_trailing_comma and gold_nospace_lower_key;
   - `I/0.0` × 33 on gold_paren, gold_prose, gold_paper_tags, wrong, empty, two_letters, out_of_range and gold_inline;
   - `N/0.0` × 33 on unsure and unsure_period.
8. Paper: `env -i … curl -sL https://arxiv.org/abs/2407.10362` lists v1 (14 Jul 2024), v2 (16 Jul) and v3 (17 Jul 2024). The v3 PDF was read with `pdftotext -layout`. Facts used:
   - Introduction: "We also introduce a set of 41 Cloning Scenarios";
   - Table 1: `CloningScenarios - 41 100%`;
   - results text: accuracy = "number of questions correct / number of questions", precision = "number of questions correct / coverage";
   - Fig. 3 caption: error bars "over three separate runs";
   - Table 2 (p.23): "measured over the entire dataset (both public and private splits), and averaged over three runs per model", CloningScenarios accuracy row `0.60 0.28 0.27 0.10 0.28 0.09 0.26 0.24`;
   - Fig. 7: "Overall performance of models on the public LAB-Bench subset", bars only;
   - Appendix D (p.37): the `[ANSWER]` prompt, "Answer choices were randomly permuted", opt-out "Insufficient information to answer the question." with a period;
   - D.3: chembench regex, "If that fails, an LLM (Anthropic's Claude 2) is prompted to attempt to parse an answer". The Llama 3 run covered 25 of 41 Cloning Scenarios, with the other 16 "treated the same way as questions where models selected the 'Insufficient information' option".
9. Harness: `env -i … git clone https://github.com/Future-House/LAB-Bench harness`. HEAD is `998a8e0 2025-09-27`. The earliest commit is `a767892 2024-07-13 "mirroring repo"`, one day before paper v1, and I checked it out.
   - `git diff a767892 998a8e0 -- labbench scripts` shows import moves, the prompt's last sentence re-wrapped onto three lines, `assert`→`raise`, and an optional `source` field. The grading rule is unchanged.
   - Install: `uv pip install --exclude-newer 2024-07-14 -e labbench` failed (`chem-bench was not found in the package registry`). chembench was cloned instead (`https://github.com/lamalab-org/chembench`) at `7ad84e632fb3cb6505711575759457bf0afb65f7` (2024-07-12, the last commit before the harness commit), with `pint fastcore loguru pydantic python-dotenv Pillow tqdm datasets` installed at `--exclude-newer 2024-07-14` (`datasets 2.20.0`, `pydantic 2.8.2`). A full `chembench` install at that date was still resolving after about 10 minutes and was stopped.
   - The harness's `labbench/__init__.py` imports the provider clients (`vertexai`, missing). So the scripts load `labbench.utils`, `labbench.zero_shot` and `labbench.evaluator` through a bare package stub, and its own code runs unchanged.
10. Dataset vs harness: `python3 -I scripts/ds_compare.py` → `harness_a767892.jsonl rows 33 only hub [] only harness [] differing {}` and `harness_998a8e0.jsonl rows 33 only hub [] only harness [] differing {}`. Between the two commits only the `tag` and `version` fields changed, on all 33 rows. `git log -- CloningScenarios/cloningscenarios-v1-public.jsonl` → `867c92b 2024-08-20`, `a767892 2024-07-13`.
11. Harness marks: `env -i … hvenv/bin/python -I scripts/harness_marks.py`. This runs the stubbed `BaseZeroShotAgent.run_task` (`fork:labbench/zero_shot.py:42-86`) with the Case's option order, then the rule `correct = agent_output == target_output`, `sure = agent_output != unsure` (`fork:labbench/evaluator.py:87-88`).
    - Output: `harness marks 561 llm-fallback calls stubbed 528`.
    - `python3 -I scripts/harness_compare.py` → `inspect_evals vs harness: identical 0 differing 561`. On gold_paper_tags it gave `I/C` × 33. The other 16 kinds were `…/FALLBACK` × 33 (no tags, so the harness would ask Claude 2).
    - Four harness-format sheets per Case (132 more): ours vs inspect `sheets 132 identical 132 differing 0`; inspect vs harness `identical 66 differing 66`. Per kind: tags_wrong `I/I`, tags_unsure `I/N`, tags_gold_lower `I/I`, tags_gold_after_cot `I/C`, each × 33, with `llm-fallback calls stubbed 0`.
    - Harness prompt for Case 1 (DNA runs elided): `"The following is a multiple choice question about biology.\nPlease answer by responding with the letter of the correct answer.\nThink step by step.\n\nQuestion: … What enzymes should be used to cut the plasmid?\n\nOptions:\n(A) Insufficient information to answer the question\n(B) PacI and BstEII\n…\n\nYou MUST include the letter of the correct answer within the following tags: [ANSWER] and [/ANSWER].\nFor example, '[ANSWER]<answer>[/ANSWER]', …"`.
    - Ours: `"\nThe following is a multiple choice question about biology.\nPlease answer by responding with the letter of the correct answer.\n\nThink step by step.\n\nQuestion: … cut the plasmid?\nOptions:\nA) Insufficient information to answer the question.\nB) PacI and BstEII\n…\n\nYou MUST include the letter of the correct answer within the following format: 'ANSWER: $LETTER' (without quotes). …\n"`.
12. Roll-up, inspect: `venv/bin/python -I scripts/rollup_theirs.py vectors.json` gave accuracy / precision / coverage:
    - all_C 1.0000/1.0000/1.0000; all_I 0.0000/0.0000/1.0000; all_N 0.0000/0.0000/0.0000;
    - alternating_C_I 0.5152/0.5152/1.0000; cycle_C_I_N 0.3333/0.5000/0.6667;
    - C_first_10_N_next_5_I_rest 0.3030/0.3571/0.8485; from_answer_sheets 0.3939/0.4483/0.8788.
13. Roll-up, ours: `env -i … uv run --isolated --extra inspect python scripts/rollup_ours.py vectors.json` (the production `_accuracy`, fed `SimpleNamespace` Case results carrying only `grade.score/metrics/scores`, scores from `_INSPECT_LETTER_SCORE_VALUES`) → headline 1.0000, 0.0000, 0.0000, 0.5152, 0.3333, 0.3030, 0.3939, with `scored_cases 33` on each.
14. Roll-up, harness: `hvenv/bin/python -I scripts/rollup_harness.py vectors.json` (`Evaluator.compute_metrics`, `fork:labbench/evaluator.py:117-132`) → the same accuracy, precision and coverage as step 12 on every vector, `n_total 33`.
15. Tests: `env -i … PYTHONDONTWRITEBYTECODE=1 uv run --isolated --extra inspect pytest "tests/unit/inspect/test_inspect_task_replay_benchmarks.py::test_lab_bench_never_keys_every_case_to_one_letter" tests/unit/inspect/test_benchmark_fingerprints.py -q -p no:cacheprovider` → `103 passed, 1 warning in 38.10s`. `test_benchmark_fingerprints.py:82` pins `"lab_bench_cloning_scenarios": "9c6f66d6acae7f05"`.
16. `git status --porcelain` after, and the scratch folder removed: see the first checkbox.

## Recommended paid runs

None is needed for this verdict. Optional, only to size the inspect-vs-harness gap on the public Cases: run all 33 Cases for one Candidate under both examiners, in the same option order.

- (a) Our live path.
- (b) The harness prompt from `fork:labbench/zero_shot.py:15-24`, graded by `fork:labbench/zero_shot.py:68-78` with its Claude 2 fallback live.

That is 66 Candidate calls plus up to 33 Claude 2 extraction calls. Repeat 3 times, as the paper does. The run cannot reach the 8 private Cases, so the paper's 41-Case numbers stay out of reach either way.

## Upstream notes

- **inspect_evals vs harness: the Case set (the comparable-to-inspect evidence).**
  - **What the published number used.** The paper's CloningScenarios numbers are over all 41 questions (Table 1; Table 2 "both public and private splits"). The harness picks its files by `PUBLIC_RELEASE` (`fork:labbench/utils.py:159-172`). With `True` it reads only `*-public.jsonl` (`:164-165`). The published run used the non-public files, which are not in the repo.
  - **What inspect_evals and we have.** The 33 public rows. They equal the harness's public file on question, ideal and distractors (Checks 10).
  - **Bound.** Dropping 8 of 41 Cases can move accuracy by at most `8/41 = 0.1951`, far above 0.005.
  - **The row's human baseline.** The row's `human_baseline=0.6` is Table 2's Human figure on those 41 questions.
  - **The 2025 fix.** The harness CHANGELOG's 2025-02-14 fix to "a Cloning Scenario" leaves no trace in the public rows' question, ideal or distractors at either commit, so the audit cannot see which row it touched.
- **inspect_evals vs harness: prompt.** The harness template (`fork:labbench/zero_shot.py:15-24`) differs from inspect_evals' (`inspect_evals:lab_bench/lab_bench.py:47-58`) in five ways:
  - the answer instruction: `[ANSWER]<answer>[/ANSWER]` tags vs `ANSWER: $LETTER`;
  - option labels: `(A) …` (`fork:labbench/utils.py:139`) vs `A) …`;
  - the opt-out text: no final period (`fork:labbench/utils.py:24`) vs a period;
  - "Think step by step." directly after the instruction line (`fork:labbench/zero_shot.py:33`) vs its own paragraph;
  - a blank line before "Options:" in the harness only, and a leading and trailing newline in inspect_evals only.

  Severity `possibly-score-changing`, bound `unknown`. It rides the optional paid run.
- **inspect_evals vs harness: answer extraction and judge.** The harness first looks for tags (`chembench:src/chembench/constant.py:65`, `chembench:src/chembench/utils.py:287-291`). Without them it asks an LLM, `ChatAnthropic(temperature=0)` (`chembench:src/chembench/utils.py:80,296`), which is Claude 2 per paper §D.3. inspect_evals reads only `ANSWER:` lines and calls no model. On our sheets the two marked 0 of 561 alike: 528 would go to Claude 2, and on the paper's own tag format the harness gives `C` where inspect_evals gives `I` (Checks 11). So the published number was partly graded by a model inspect_evals does not use, a different process by design. Bound `unbounded`.
  - Harness quirks, recorded only:
    - A lower-case letter in tags is marked wrong, because `run_regex` matches case-insensitively and returns `c`, but `agent_output == target_output` is case-sensitive (`chembench:src/chembench/utils.py:253`; `fork:labbench/evaluator.py:87`; tags_gold_lower `I` × 33).
    - The fallback relabels the options in a seed-42 permutation before asking the LLM (`chembench:src/chembench/utils.py:84-87`).
- **inspect_evals vs harness: unsure on error.** A prompt too long for the provider raises `UnanswerableError` and is counted as an opt-out (`fork:labbench/evaluator.py:82-84`). The paper's Llama 3 ran only 25 of 41 Cloning Scenarios this way (§D.3). Under inspect_evals such a sample errors out. Ours withholds it as a 0 under `failure_policy="withhold"`. No answer sheet exercises it.
- **inspect_evals vs harness: sampling and roll-up.**
  - The harness sets `max_tokens=1024` for Anthropic Candidates only (`fork:labbench/anthropic.py:14`) and passes only `model` otherwise. inspect_evals and ours set nothing.
  - The paper averages three runs. inspect_evals and ours run one epoch.
  - Pooled accuracy, precision and coverage are computed identically by all three (Checks 12-14).
- **Paper vs harness: opt-out wording and layout (harness wins).** The paper prints the opt-out with a final period and lays out the prompt with "Think step by step." as its own paragraph (p.37). The harness sends neither. inspect_evals follows the paper's spelling. Both differences are folded into the prompt note above.
- **Harness pin.** The audit read `a767892` (2024-07-13), the commit nearest paper v1. Up to `998a8e0` (2025-09-27) the grading rule and the public rows' Q/A fields are unchanged. The prompt's last sentence was re-wrapped onto three lines (Checks 9).
- **Row's frontier score.** `FrontierScore(score=0.612, model="o3", source_url="https://arxiv.org/pdf/2505.06108")` comes from a different paper. This audit did not open it, so whether that number came from inspect_evals' examiner is not checked here.
