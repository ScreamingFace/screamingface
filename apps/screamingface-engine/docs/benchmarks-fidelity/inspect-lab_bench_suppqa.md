---
benchmark: inspect-lab_bench_suppqa
origin: inspect_evals
verdict: unverified
verdict_reason: "OME-1907 (2026-11-13): grading now reads an answer inside a wrapper, such as 'ANSWER: $B' or 'ANSWER: **B**', that inspect_ai v0.3.263 reads as no answer (our Named Deviation for inspect_ai issue 5055), so a reply with a wrapper can grade differently from inspect's; only a paid run can bound how often that happens, so the rule gives unverified. Verdict before: comparable-to-inspect. "
audited: 2026-11-09
audited_at: 43d3942f6
fingerprint:
  benchmark: 3aae3cdf14efeab8
  harness_url: https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0/src/inspect_evals/lab_bench
references:
  paper: https://arxiv.org/abs/2407.10362v3
  original_harness: https://github.com/Future-House/LAB-Bench/tree/a767892307ad38a5f4f77cd00d30c2442aaea791
  inspect_evals: https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0
  inspect_ai: https://github.com/UKGovernmentBEIS/inspect_ai/tree/v0.3.263
parity_test: none
parity_test_reason: "No parity test sends lab_bench_suppqa replies through both scorers. test_inspect_imported_benchmarks.py::test_lab_bench_benchmarks_pin_a_choice_order only checks that the choice-shuffle seed is declared. This audit's answer sheets (Checks run 8-10) do that job for now."
---

# LAB-Bench SuppQA — Fidelity Record

## Verdict

**`comparable-to-inspect`.** Our headline is accuracy over the 82 public SuppQA questions, with the "Insufficient information" choice counting as not correct. It can sit beside a run of [inspect_evals' `lab_bench_suppqa` at v0.20.0](https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0/src/inspect_evals/lab_bench), but not beside the [paper's](https://arxiv.org/abs/2407.10362v3) Table 2 SuppQA row. Against inspect_evals everything matches. The Candidate gets exactly inspect's rendered prompt on all 82 Cases: same row order, same choice order, same bytes. Our grade hook gives inspect's own letter (C/I/N) on all 1,640 answer-sheet marks. Six fixed mark vectors roll up to inspect's `accuracy()` to four decimals. The one difference is declared nowhere and is cosmetic: we do not publish inspect's secondary `precision`, `coverage` and `stderr` metrics. So `sum of bounds against inspect_evals = 0/82 = 0.0000 ≤ COMPARABLE_TOLERANCE (0.005)`. inspect_evals itself is a different examiner from the [authors' harness](https://github.com/Future-House/LAB-Bench/tree/a767892307ad38a5f4f77cd00d30c2442aaea791), beyond tolerance, in four ways:
- **Prompt.** The harness asks for `[ANSWER]X[/ANSWER]` tags; inspect asks for `ANSWER: X`.
- **Answer extraction.** Each side accepts only its own format: 10 of the 20 sheet types mark differently on all 82 Cases, and one more crashes the harness's checker. The paper-era checker also falls back to an Anthropic model when no tag matches.
- **Cases.** The paper's number covers all 102 questions, the 20% private split included. We and inspect_evals have only the 82 public ones.
- **Runs.** The paper averages three runs; inspect makes one.

The bound for inspect_evals vs the harness is `unbounded` (Upstream notes), so `comparable-to-paper` is ruled out and `comparable-to-inspect` holds.

## Dimensions

| dimension | status | severity | bound | evidence |
|---|---|---|---|---|
| dataset | match | — | — | Ours: Hub `futurehouse/lab-bench` config `SuppQA` split `train` at `5c77cec6…`, pinned at `apps/screamingface-engine/src/screamingface_engine_inspect/prepare.py:1183` and in inspect_evals (`inspect_evals:lab_bench/lab_bench.py:33`). Our full Task replay gave `cases 82 pinned 82` and `digest 5233348a… equal True` (Checks run 5). Rebuilt independently from the installed inspect_evals (`hf_dataset` with the task's own arguments plus `seed=7, shuffle_choices=7`, the two seeds on `prepare.py:1186-1187`): the same 82 Samples in the same order, with `Cases whose target/choices != inspect's seeded Sample: []` (Checks run 7). Two unseeded builds of inspect's own call give a different row and choice order each time (`draw1 == draw2: False`) but the same Cases (`same Cases ignoring order …: True`). So our order is one fixed draw of inspect's own shuffle (`inspect_evals:lab_bench/lab_bench.py:64-78`). Against the harness file `fork:SuppQA/suppqa-v1-public.jsonl` (82 lines, sha256 `9282d4b8…`, unchanged a767892 → 998a8e0): ids on one side only `[]` both ways; gold text, choice set and question text differ on `[]` (Checks run 7). |
| prompt | match | — | — | All 82 Cases. Inspect's side was rendered by THEIR `multiple_choice(template=MULTIPLE_CHOICE_TEMPLATE, cot=True)` solver (`inspect_evals:lab_bench/lab_bench.py:47-58,152`; `inspect_ai:solver/_multiple_choice.py:57,71,326`), with a stub `generate` that records the messages and calls no model. Result: `messages per Case: [1] roles: ['user']`, and against our Case inputs, `Cases whose Candidate input bytes != inspect's rendered prompt: []` (Checks run 7). No system message on either side: the Task declares none (`inspect_evals:lab_bench/lab_bench.py:149-157`). Our Case input is the rendered text the Candidate is sent. |
| answer extraction | match | — | — | Ours replays inspect's own `parse_answers` + `set_choices_based_on_generated_response` (`apps/screamingface-engine/src/screamingface_engine_inspect/scorer_adapter.py:651`; theirs `inspect_ai:solver/_multiple_choice.py:82,155,334-335`). One code-path difference: inspect marks choices only `if answers:` (`:335`), while we always mark them, all False when nothing parses. That cannot change a mark, because `precision_choice` counts only `choice.correct is True` (`inspect_evals:lab_bench/scorer.py:30,36`). The `empty`, `no_answer_line` and `out_of_range` sheets read `I` on both sides. Answer sheets: 82 Cases × 20 replies = 1,640 marks, `letter differs: 0`, `score differs: 0`, `failures: []` (Checks run 8-10). |
| metric | match | — | — | The same scorer: our row names `inspect_evals.lab_bench.lab_bench:precision_choice` with `no_answer="Insufficient information to answer the question."` (`apps/screamingface-engine/src/screamingface_engine_inspect/benchmarks.py:1491`), equal to the Task's (`inspect_evals:lab_bench/lab_bench.py:153`; `inspect_evals:lab_bench/record_to_sample_helpers.py:13`). The answer sheets agree mark for mark (above). Our letter map `C 1.0, I 0.0, P 0.5, N 0.0` (`scorer_adapter.py:111`) equals inspect's `value_to_float` for the accuracy metric (`inspect_ai:scorer/_metric.py:323-324`, noanswer → 0.0). Per sheet on both sides: the five `ANSWER: <gold>` forms (plain, lower-case, trailing period, after reasoning, trailing comma) and `wrong_then_gold` give C; `unsure` / `unsure_cot` give N; everything else gives I. |
| roll-up | deviation | cosmetic | 0 | Headline: ours `_accuracy` (`apps/screamingface-engine/src/screamingface_engine_inspect/single_shot.py:1275,1303`, chosen at `:1160` because the row has no whole-run metric) against inspect's `accuracy()` (`inspect_ai:scorer/_metrics/accuracy.py:15`), first of the scorer's metrics (`inspect_evals:lab_bench/scorer.py:17`). Six fixed 82-Case vectors were equal to four decimals: all-C 1.0000; all-I 0.0000; all-N 0.0000; alternating C/I 0.5000; C/I/N cycling 0.3415; sheet marks 0.3171 (Checks run 11-12). D1: inspect's `precision`, `coverage` and `stderr` are not published. |
| judge | not applicable | — | — | `imported_benchmark("lab_bench_suppqa").judge` → `None` (Checks run 2). The inspect Task's only scorer is deterministic `precision_choice`, no `model_graded_*` (`inspect_evals:lab_bench/lab_bench.py:153`). The paper-era harness's model fallback extractor is an inspect_evals-vs-harness difference (Upstream notes). |
| sampling | match | — | — | Ours: `BenchmarkDeclaration(... interaction='single_shot', ..., attempts=1)`, and no `max_tokens` / `temperature` on the row (`/usr/bin/grep` over `benchmarks.py:1467-1529`: no hits; Checks run 13). inspect_evals: `epochs=Epochs(1, "mode")` (`inspect_evals:lab_bench/lab_bench.py:154`); `multiple_choice` `max_tokens=None`; no `GenerateConfig` in the Task (grep exit 1). Both make one attempt and leave decoding to the provider. |

## Deviations

### D1 — inspect's secondary metrics are not published

- **Undeclared** (no `# NAMED DEVIATION`, `dropped_scorers` or README paragraph). The row's description says only "Benchmark score = plain accuracy over the cases run" (`apps/screamingface-engine/src/screamingface_engine_inspect/benchmarks.py:1479`).
- **Where.** Ours: `_accuracy` publishes `score` (accuracy) plus `correct` and `scored_cases` (`single_shot.py:1275-1309`). Theirs: `@scorer(metrics=[accuracy(), precision(), coverage(), stderr()])` (`inspect_evals:lab_bench/scorer.py:17`); `precision` and `coverage` are at `inspect_evals:lab_bench/metrics.py:63,94`.
- **What differs.** inspect reports precision (correct ÷ answered) and coverage (answered ÷ all) beside accuracy. The paper reports both too (Tables 3, 4). We publish accuracy only, and our per-Case score keeps no I/N split (both 0.0). The split is in each Case's check evidence (`"metadata": {"value": "C" …}`, Checks run 8), so a reader can still work out precision and coverage.
- **Severity / bound.** `cosmetic`, `0`: no Case's mark and not the headline. Accuracy equals inspect's on every vector tried (Checks run 11-12).

## Checks run

- [x] **Read-only on the checkout.** `git status --porcelain` before and after shows only the untracked records and the ledger the calling session writes into this worktree concurrently. No tracked file changed. Every file this audit created lived under `$SCRATCH=/private/tmp/claude-501/…/scratchpad/audit-lab_bench_suppqa-pFgD`, deleted at the end. Python ran with `PYTHONDONTWRITEBYTECODE=1` after the first two calls. Those two may have written gitignored `__pycache__/*.pyc` under the checkout's `src/` (17 `.pyc` newer than the brief; other audits share the checkout, so not attributed or deleted).
- [x] **No keys, no model.** `env -i PATH="$PATH" HOME="$SCRATCH" UV_CACHE_DIR="$SCRATCH/uv-cache" env | grep -iE 'key|token|secret'` → empty (`grep exit=1`). Every third-party command (uv, git clone, curl to arxiv.org / pypi.org, the inspect and chembench scripts) ran under that prefix. inspect's solver was driven by a stub `generate` that sets a canned reply. The harness's extractor ran without `llm_extractor`. No model, gateway or provider was called.
- [x] **Harness over paper.** The paper (102 Cases, 3 runs) and the harness's public release (82 Cases) disagree on the Case set; recorded in Upstream notes, not counted here.
- [x] **Declared is not a finding.** D1 is undeclared and cosmetic (bound 0). The row's seeds are a "Fold" comment (`prepare.py:1171`), not a deviation: the rebuild shows they pick one of inspect's own shuffles.
- [x] **Every cell has evidence.** Each `match` names its command, output lines and source locations above.
- [x] **Every `file:line` is copied from command output.** Line numbers came from `/usr/bin/grep -n` or `sed -n` on the single pinned files: `prepare.py`, `benchmarks.py`, `scorer_adapter.py`, `single_shot.py` in the checkout; `lab_bench.py`, `scorer.py`, `metrics.py`, `record_to_sample_helpers.py` copied out of the installed inspect_evals 0.20.0; `solver/_multiple_choice.py`, `scorer/_metric.py`, `scorer/_metrics/accuracy.py` from inspect_ai 0.3.263; `labbench/{utils,zero_shot,evaluator,anthropic}.py`, `labbench/pyproject.toml`, `SuppQA/task.py` in the fork at a767892; `src/chembench/utils.py` at chembench 7ad84e6; `chembench/prompter.py` in chembench 0.3.0. (`/usr/bin/grep`, because an `rtk` shell proxy rewrites plain `grep` output.)
- [x] **A verdict never claims more than its evidence.** No core dimension is `unchecked`; no `possibly-score-changing` deviation is open against inspect_evals.
- No `ours` override was set.

1. `git status --porcelain` (checkout) → only concurrent untracked records + ledger. `git rev-parse --short HEAD` → `43d3942f6`. `mktemp -d …/audit-lab_bench_suppqa-XXXX` → `audit-lab_bench_suppqa-pFgD`. Env check → empty, `grep exit=1`.
2. Our side: `env -i … HF_HUB_DISABLE_XET=1 uv run --isolated --extra inspect python scripts/ours_info.py` → `fingerprint 3aae3cdf14efeab8`, `judge None`, `origin 'inspect_evals'`, `harness_url '…/inspect_evals/tree/v0.20.0/src/inspect_evals/lab_bench'`, `paper_url 'https://arxiv.org/abs/2407.10362'`, `case_count 82`, `declaration=BenchmarkDeclaration(failure_policy='withhold', interaction='single_shot', difficulty='hard', attempts=1)`, `inspect-evals 0.20.0`, `inspect-ai 0.3.263`. A second call showed `multiple_correct False`, `whole_run_metric_factory None`, `named_scores ()`, `inverted False`, `verdict_grades None`.
3. Copied `inspect_evals/lab_bench/`, `inspect_evals/utils/huggingface.py` and `inspect_ai/{solver,scorer,dataset}` out of that environment into scratch for reading.
4. Original harness: `git clone https://github.com/Future-House/LAB-Bench harness`. HEAD = `998a8e0a… 2025-09-27`. First commit `a767892307ad… 2024-07-19 "mirroring repo"` (two days after paper v3); `git checkout a767892`. `git diff a767892 HEAD -- SuppQA labbench/{zero_shot,utils,evaluator}.py`: import moves, `noqa`s, env-var defaults, and the template's last paragraph split onto three lines. No change to choice randomisation, extraction calls or metric. `git diff --stat a767892 HEAD -- SuppQA/*.jsonl` → empty. The paper-era `labbench/pyproject.toml:18` depends on unpinned `chem-bench`, which PyPI does not have (`{"message": "Not Found"}`). PyPI's `chembench` has only `0.3.0` (2025-02-27). So the paper-era checker cannot be installed as written. Installed `chembench==0.3.0` (the HEAD lock's pin) in `$SCRATCH/venv` in 1:18 to run HEAD's extraction call. Read the paper-era extractor from `lamalab-org/chem-bench` at `7ad84e63` (newest commit before 2024-07-14, blobless clone).
5. `env -i … uv run --isolated --extra inspect python scripts/ours_cases.py` (`replay_with_provenance(TASK_REPLAY_CASES["lab_bench_suppqa"])`, the image-side Case Preparation) → `cases 82 pinned 82`, `digest 5233348a35d4e988fd71f1741ded483b9d8ffae3a0e8979203fb6ab0e7aa90f9 … equal True`, provenance `seeds_applied {"choice_shuffle_seed": 7, "shuffle_seed": 7}`, `samples yielded 82 excluded 0 kept 82`.
6. Paper: `curl https://arxiv.org/abs/2407.10362` → v1 14 Jul, v2 16 Jul, v3 17 Jul 2024. `pdftotext` on v3. Facts used: Table 1 "SuppQA 102"; §method "0-shot chain-of-thought … parsing the answers directly from the models' text completions"; Table 2 "Accuracy … measured over the entire dataset (both public and private splits), and averaged over three runs per model"; §B.1 "kept 20% of questions … private".
7. Inspect's side: `env -i … PYTHONPATH=$SCRATCH/scripts uv run --isolated --extra inspect python scripts/theirs.py` (imports only inspect_ai / inspect_evals) → `unseeded draw sizes [82, 82] seeded 82`; `unseeded draw1 == draw2 (ids+choice order): False`; `unseeded id order equal: False`; `unseeded vs seeded same Cases ignoring order …: True`; `rendered 82 sheets/row 20 marks 1640`; `messages per Case: [1] roles: ['user']`. Then `python3 -I scripts/dataset_cmp.py` → `Cases whose Candidate input bytes != inspect's rendered prompt: []`, `Cases whose target/choices != inspect's seeded Sample: []`, `ids 1..82 in order: True`, harness `ids on inspect side only: []  on harness side only: []`, `Cases whose gold / choice set / question differ from the harness row: []`, `choices per Case: [5, 6, 7, 8, 9]`.
8. Answer sheets, ours: `uv run --isolated --extra inspect python scripts/ours_sheets.py`, through the production hook `imported_benchmark("lab_bench_suppqa").aggregation().grade_case`. There are 20 sheets per Case, lettered against that Case's own choice order:
   - the gold as `ANSWER: X`, `ANSWER: x`, `ANSWER: X.`, after reasoning on the last line, `ANSWER: (X)`, bare `X`, `The answer is X.`, `[ANSWER]X[/ANSWER]`, inline, `ANSWER: X,`, `ANSWER: X, W`;
   - wrong-then-gold and gold-then-wrong on two lines;
   - two wrong letters;
   - the "Insufficient information" letter, bare and after reasoning;
   - `ANSWER: Z`, the empty reply, and a reply with no answer line.

   Output: `graded 82 sheets/row 20 marks 1640`. A sample check entry carries `"metadata": {"value": "C", "answer": "D"}`.
9. No recorded real replies exist for this Benchmark: no goldens directory in the checkout's tests, and no test fixture names `suppqa`.
10. `python3 -I scripts/cmp_sheets.py ours_sheets.json theirs.json` → `marks compared 1640`, `letter differs: 0 []`, `score differs: 0`, `failures: []`; per-sheet tallies are identical on both sides.
11. Roll-up, theirs: `uv run … python scripts/rollup_theirs.py fork:labbench/evaluator.py theirs.json`, using inspect's `accuracy()`, inspect_evals' `precision()` / `coverage()`, and the harness's `compute_metrics` pulled verbatim by `ast`:
    - `all-C` 1.0000 1.0000 1.0000 on both;
    - `all-I` 0/0/1 on both;
    - `all-N` 0/0/0 on both;
    - `alternating C/I` 0.5/0.5/1 on both;
    - `C/I/N cycling` → inspect acc/prec/cov `0.3415 0.5091 0.6707`, harness `0.3415 0.5091 0.6707`;
    - `sheet i mod 20` → `0.3171 0.3514 0.9024` on both.
12. Roll-up, ours: `uv run … python scripts/rollup_ours.py theirs.json` → `all-C 1.0000`, `all-I 0.0000`, `all-N 0.0000`, `alternating C/I 0.5000`, `C/I/N cycling 0.3415`, `sheet i mod 20 0.3171`.
13. Sampling: `sed -n '1467,1529p' benchmarks.py | /usr/bin/grep -n -i "max_tokens\|temperature\|attempts\|seed\|params\|NAMED DEVIATION\|dropped_scorers\|excluded"` → one hit, the description's word "seeds", and no knob. `/usr/bin/grep -n "GenerateConfig\|max_tokens\|temperature\|config=" inspect_evals:lab_bench/lab_bench.py` → exit 1.
14. `uv run --isolated --extra inspect pytest "tests/unit/inspect/test_inspect_imported_benchmarks.py::test_lab_bench_benchmarks_pin_a_choice_order" -q -p no:cacheprovider` → `1 passed in 9.03s`.
15. Harness extraction (HEAD 998a8e0 call shape `prepare_mcq_answer(reply, MCQ_REGEX_TEMPLATE_1, example=…)`, `run_regex(create_multiple_choice_regex(…), …, return_first=True)`, chembench 0.3.0, no `llm_extractor`; `correct = answer == target`, `sure = answer != unsure` as `fork:labbench/evaluator.py:87-88`): `env -i … $SCRATCH/venv/bin/python -I scripts/harness_sheets.py` → the same 1,640 sheets. Compared with inspect, 10 sheet types mark differently on 82/82 Cases and 1 more raises: `gold_ANSWER`, `gold_lower`, `gold_period`, `gold_cot_last_line`, `gold_trailing_comma`, `wrong_then_gold` C→I; `gold_bare`, `gold_harness_tags` I→C; `unsure`, `unsure_cot` N→I; `empty` I→raises `TypeError` (chembench 0.3.0 `prepare_mcq_answer` returns `None`, `chembench/prompter.py:898-914`).
16. `git status --porcelain` (checkout) → the same concurrent untracked files only. Report written outside the repo; scratch removed with `python3 -c "import shutil, sys; shutil.rmtree(sys.argv[1])" "$SCRATCH"`.

## Recommended paid runs

None for this record: ours vs inspect_evals is closed at 0.

Optional, to size the inspect_evals-vs-paper gap (Upstream notes U1-U2): run one Candidate the paper reports (for example `claude-3-5-sonnet-20240620`) 3 times on the 82 public Cases under each prompt and extractor. That is our Benchmark (inspect's prompt and parser) against the harness's `MCQ_INSTRUCT_TEMPLATE` with tag parsing. About 2 × 3 × 82 = 492 Candidate calls, no judge. It measures U1 + U2 together; U3 (the 20 private Cases) cannot be measured by anyone outside FutureHouse.

## Upstream notes

- **U1 — inspect_evals' prompt is not the harness's prompt (inspect vs harness; bound `unbounded`, needs a paid run).**
  - inspect (`inspect_evals:lab_bench/lab_bench.py:47-58`) says "Think step by step." on its own line before the question. It lists choices as `A) text` (`inspect_ai:solver/_multiple_choice.py:57`) and asks for `'ANSWER: $LETTER'`.
  - The harness (`fork:labbench/zero_shot.py:15-24`, `:33`, `:50`) puts "Think step by step." (chembench `COT_PROMPT`) on the instruction line. It adds a blank line before "Options:", uses the `(A) text` choice form (`fork:labbench/utils.py:139`), asks for `[ANSWER]<answer>[/ANSWER]` tags, and runs the prompt through chembench's `post_process_prompts` (`:52`).
  - The opt-out choice also differs: inspect has `"Insufficient information to answer the question."` with a period (`inspect_evals:lab_bench/record_to_sample_helpers.py:13`), the harness has it without one (`fork:labbench/utils.py:24`).
  - Both shuffle choices randomly per run: inspect `hf_dataset(shuffle_choices=True)`, the harness `random.shuffle(perm)` (`fork:labbench/utils.py:137`).
  - The question text (`Paper title: …\nDOI: …\n<question>`) is the same on both sides (`fork:SuppQA/task.py:18-19`; `inspect_evals:lab_bench/record_to_sample_helpers.py:27-38`).
- **U2 — answer extraction differs, and the paper-era harness falls back to a model (inspect vs harness; bound `unbounded`).**
  - Each examiner accepts only its own format. On the same 1,640 sheets, 10 sheet types mark differently on every Case and an empty reply crashes the HEAD harness's checker (Checks run 15).
  - At the paper's time the harness called chembench's `prepare_mcq_answer` with its default `llm_fallback=True` (`chembench@7ad84e6:src/chembench/utils.py:267,294-298`). When no tag matched, the reply went to `ChatAnthropic(temperature=0)` (`:80`) to pull out a letter. So the paper's marks include a model-based extractor on replies that missed the tags; inspect marks those `I`.
  - The exact chembench commit the authors installed is not recorded (`fork:labbench/pyproject.toml:18`, unpinned `chem-bench`, not on PyPI). HEAD's harness (998a8e0, chembench 0.3.0) no longer falls back to a model.
  - A reply with no answer counts as answered-and-wrong on both sides: the harness has `sure = agent_output != unsure` with `None` (`fork:labbench/evaluator.py:88`), and inspect gives `I`.
- **U3 — the paper's number covers 102 Cases; inspect_evals and we have the 82 public ones (paper vs harness release; bound `unbounded`).**
  - Paper Table 1 lists SuppQA as 102 questions. Table 2's accuracy is "measured over the entire dataset (both public and private splits), and averaged over three runs per model" (§B.1: 20% held private).
  - The harness's public release loads only `*-public.jsonl` (`fork:labbench/utils.py:165`), 82 rows, the same 82 as the Hub config inspect reads (Checks run 7).
  - Our row's `frontier_score` (0.2, Meta-Llama-3-70B-Instruct, `benchmarks.py:1517`) is therefore a 102-Case, 3-run, harness-prompt number. It is not one of our runs.
- **U4 — sampling (recorded, not counted).** The harness's Anthropic agent defaults `max_tokens=1024` (`fork:labbench/anthropic.py:14`); its OpenAI agent passes only the model (provider defaults). The paper averages 3 runs. inspect_evals makes one epoch with no `max_tokens`. The paper states no temperature.
- **U5 — the metric and roll-up definitions agree (inspect vs harness; bound 0).** Accuracy is correct ÷ all, precision is correct ÷ sure, coverage is sure ÷ all. `fork:labbench/evaluator.py:128-130` equals `inspect_ai:scorer/_metrics/accuracy.py:15` with `inspect_evals:lab_bench/metrics.py:63,94` on all six vectors to four decimals (Checks run 11).
