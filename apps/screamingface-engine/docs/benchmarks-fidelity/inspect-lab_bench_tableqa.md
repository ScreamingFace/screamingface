---
benchmark: inspect-lab_bench_tableqa
origin: inspect_evals
verdict: unverified
verdict_reason: "OME-1907 (2026-11-13): grading now reads an answer inside a wrapper, such as 'ANSWER: $B' or 'ANSWER: **B**', that inspect_ai v0.3.263 reads as no answer (our Named Deviation for inspect_ai issue 5055), so a reply with a wrapper can grade differently from inspect's; only a paid run can bound how often that happens, so the rule gives unverified. Verdict before: comparable-to-inspect. "
audited: 2026-11-09
audited_at: 43d3942f6
fingerprint:
  benchmark: 9990079555f06a35
  harness_url: https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0/src/inspect_evals/lab_bench
references:
  paper: https://arxiv.org/abs/2407.10362v3
  original_harness: https://github.com/Future-House/LAB-Bench/tree/a767892307ad38a5f4f77cd00d30c2442aaea791
  inspect_evals: https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0
  inspect_ai: https://github.com/UKGovernmentBEIS/inspect_ai/tree/v0.3.263
parity_test: none
parity_test_reason: "No checked-in test grades TableQA Cases through both scorers; the two lab_bench tests only pin that a choice shuffle seed exists and reaches the key. For this record the answer sheets ran inspect_evals' own Task solver and precision_choice scorer against our grade hook in scratch: 244 Cases x 15 replies = 3,660 marks, all identical."
---

# LAB-Bench TableQA — Fidelity Record

## Verdict

**`comparable-to-inspect`.** Our TableQA headline is plain accuracy over the 244 public Cases, each carrying one to three table pictures. It can sit beside a number from [inspect_evals' `lab_bench_tableqa` (v0.20.0)](https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0/src/inspect_evals/lab_bench). It cannot sit beside the [LAB-Bench paper's](https://arxiv.org/abs/2407.10362v3) TableQA numbers, including the row's frontier score (Claude 3.5 Sonnet 0.83) and human baseline (0.84), which the row cites from the paper's Appendix B, Table 2.

Ours matches inspect_evals on every dimension that can change a mark:
- **Prompt:** all 244 Case inputs equal the message inspect_evals' own solver renders: same role, same part order (pictures, then text), the text byte for byte, and every picture's `data:image/png;base64,…` URL byte for byte. Neither side sends a system message.
- **Marks:** 244 Cases × 15 pre-written replies = 3,660 marks, all identical to inspect_evals' own `precision_choice` scorer.
- **Headline:** our mean equals inspect's `accuracy()` to four decimals on 20 fixed mark vectors.

The one difference against inspect_evals is cosmetic (D1): we do not publish its secondary `precision`, `coverage` and `stderr` metrics. Arithmetic: `sum of bounds against inspect_evals = 0/244 = 0.0000 ≤ COMPARABLE_TOLERANCE (0.005)`.

Against the [authors' harness](https://github.com/Future-House/LAB-Bench/tree/a767892307ad38a5f4f77cd00d30c2442aaea791), inspect_evals differs beyond tolerance:
- **Prompt:** a different template that asks for `[ANSWER]X[/ANSWER]` instead of `ANSWER: X`.
- **Answer extraction:** the harness reads the tags, and when they are missing it asks an Anthropic model to pull the letter out. inspect_evals reads `ANSWER: X` and nothing else. On every Case, a correct reply in one side's format is marked wrong by the other.
- **Dataset:** the paper's numbers cover the public plus the private split. We and inspect_evals run the 244 public questions.

The bound on the prompt and extraction difference is `unbounded`, because it depends on the model. So the rule gives `comparable-to-inspect`, not `comparable-to-paper`. Details are in Upstream notes.

## Dimensions

| dimension | status | severity | bound | evidence |
|---|---|---|---|---|
| dataset | match | — | — | **Same pin as inspect_evals.** Ours: `"futurehouse/lab-bench": "5c77cec648430f30611808808861eb86f81d5eaa"` (`apps/screamingface-engine/src/screamingface_engine_inspect/prepare.py:1942`), `case_count=244` (`:1937`). inspect_evals: `LAB_BENCH_DATASET_REVISION = "5c77cec…"` (`inspect_evals:lab_bench/lab_bench.py:33`), split `train`, config `TableQA` (`:70-78`, `:106-110`).<br>**Seal holds.** Our production replay child (`replayed_cases`) → `count 244 pinned 244`, `digest 9be147a0… pinned 9be147a0… equal True` (Checks 3).<br>**Rows equal inspect's Samples.** `material: Cases whose target/choices != inspect Sample: []` (Checks 5).<br>**Rows equal the authors' files.** Against the harness's `TableQA/tableqa-v1-public.jsonl` and `TableQA/tables/*.png` at HEAD `998a8e0`: `ids only ours [] only harness []`, question, ideal, distractor set, picture count and picture bytes (sha256) differ on `[]`. At `a767892`, the paper-time commit, only the question text differs, on Cases 26 and 149 (Upstream notes U4) (Checks 7).<br>**Order.** Row and option order come from inspect's own shuffles (`hf_dataset(shuffle=True, shuffle_choices=True)`, `inspect_evals:lab_bench/lab_bench.py:64-78`). The row's `shuffle_seed=7, choice_shuffle_seed=7` (`prepare.py:1944-1945`) are forced in by `fetch_pins.py:130,134`. inspect_evals passes no seed, so each inspect run is a fresh draw from the same shuffle, and ours is the seed-7 draw. Accuracy is a plain mean, so row order cannot change it. Gold letters spread over A–H (`A 32, B 42, C 43, D 44, E 38, F 25, G 11, H 9`). `test_lab_bench_benchmarks_pin_a_choice_order` and `test_lab_bench_never_keys_every_case_to_one_letter[lab_bench_tableqa]`: `2 passed` (Checks 9). |
| prompt | match | — | — | **All 244 Cases rendered both ways.** Ours: the Case input from the replay child, a `screamingface.candidate-input.v2` envelope holding one user message. Theirs: inspect_evals' own `task_base(ds).solver` (`multiple_choice(template=MULTIPLE_CHOICE_TEMPLATE, cot=True)`, `inspect_evals:lab_bench/lab_bench.py:152`, template `:47-58`). It ran over a dataset rebuilt with inspect_evals' own `hf_dataset` call plus explicit `seed=7, shuffle_choices=7`, without our seed-forcing code. The messages were captured at `generate()`.<br>Result: `prompt: Cases whose Candidate input (text bytes + image data URLs, role, part order) != inspect's rendered messages: []` (Checks 5). That covers all 262 pictures (229 Cases with 1, 12 with 2, 3 with 3). Each is the dataset's PNG bytes in a `data:image/png;base64,` URL (`inspect_evals:lab_bench/record_to_sample_helpers.py:61-76`, `inspect_evals:lab_bench/utils.py:4`), with nothing re-encoded on either side.<br>Rendering: `inspect_ai:solver/_multiple_choice.py:57-79` (`A) …` options, leading `\n`, the curly `’` quotes, all kept), `state.user_prompt.text = prompt(…)` (`:326`). |
| answer extraction | match | — | — | **Same code, same results.** Ours replays inspect's own `parse_answers` + `set_choices_based_on_generated_response` (`apps/screamingface-engine/src/screamingface_engine_inspect/scorer_adapter.py:651`). Theirs runs them inside the solver (`inspect_ai:solver/_multiple_choice.py:82`, `:155`, `:332-335`).<br>Answer sheets, 15 replies per Case: gold as `ANSWER: X`, `answer: x`, `ANSWER: X.`, CoT then `ANSWER: X`, `ANSWER: X,`, `ANSWER: (X)`, `The answer is X.`, bare `X`, `[ANSWER]X[/ANSWER]`, a wrong letter, the opt-out letter, two letters, out of range `Z`, wrong-then-gold, and empty.<br>Result: `answer sheets: 3660 marks; identical 3660 differing 0` (Checks 5). Under both, `(X)`, the sentence form, bare `X` and the harness tags extract nothing and are marked wrong (sums 0/244 each). No recorded goldens exist for this Benchmark (`grep -rln "lab_bench\|tableqa" tests/fixtures tests/e2e`: no matches). |
| metric | match | — | — | **Same scorer.** Ours: the row names inspect_evals' own `precision_choice` with `no_answer="Insufficient information to answer the question."` (`apps/screamingface-engine/src/screamingface_engine_inspect/benchmarks.py:6756-6757`). The letters map as `{"C": 1.0, "I": 0.0, "P": 0.5, "N": 0.0}` (`scorer_adapter.py:111`). Theirs: `inspect_evals:lab_bench/scorer.py:17-59`, where choosing the opt-out gives `NOANSWER` (`:48-49`). inspect's `accuracy()` reads `N` as 0.0 (`inspect_ai:scorer/_metric.py:323-324`).<br>Every Case float is equal on all 3,660 sheets. Per sheet: every gold form that extracts → ours sum 244, the opt-out sheet → theirs `NOANSWER` ×244 and ours 0 ×244 (Checks 5). |
| roll-up | deviation | cosmetic | 0 | **Headline equal.** Ours: `_accuracy` = `round(sum(values) / len(cases), 4)` (`apps/screamingface-engine/src/screamingface_engine_inspect/single_shot.py:1275`, `:1303`), chosen when the row has no whole-run metric (`:1160`). Theirs: `accuracy()` (`inspect_ai:scorer/_metrics/accuracy.py:15`), the first of `metrics=[accuracy(), precision(), coverage(), stderr()]` (`inspect_evals:lab_bench/scorer.py:17`).<br>20 vectors (all-C, all-I, alternating C/I, every 3rd N, a C/I/N cycle, and the marks of all 15 answer-sheet columns): `equal True` on every one, e.g. `C_I_N_cycle ours 0.3361 inspect_accuracy 0.3361 (inspect precision 0.5031 coverage 0.6680)` (Checks 8).<br>**The difference (D1):** `precision`, `coverage` and `stderr` are not published. The declared `failure_policy="withhold"` (`benchmarks.py:6714`; `apps/screamingface-engine/src/screamingface_engine/benchmarks/aggregation.py:106`) counts a failed Candidate call as 0. That only matters when a call fails; no answered Case's mark changes. |
| judge | not applicable | — | — | `imported_benchmark("lab_bench_tableqa").judge` → `None` (Checks 3). `precision_choice` is deterministic. (The authors' harness does call a model to extract answers; see Upstream notes U2.) |
| sampling | match | — | — | **Ours:** `declaration=BenchmarkDeclaration(failure_policy='withhold', interaction='single_shot', difficulty='medium', attempts=1)` (Checks 3). No `max_tokens` or `temperature` on the row (`grep -n 'max_tokens\|temperature'` over `benchmarks.py:6692-6758`: none).<br>**Theirs:** `multiple_choice(… max_tokens=None)` (`inspect_ai:solver/_multiple_choice.py:247`), no `GenerateConfig` on the Task (`inspect_evals:lab_bench/lab_bench.py:149-157`), `epochs=Epochs(1, "mode")` (`:154`). The mode of one epoch is our single attempt.<br>**Harness and paper:** the harness fixes no temperature. Only its Anthropic wrapper defaults `max_tokens` to 1024 (`fork:labbench/anthropic.py:14`). The row says the paper's number is a mean of 3 runs, 0-shot (`benchmarks.py:6746`). A knob left open. |

## Deviations

### D1 — inspect_evals' secondary metrics not published

- **Undeclared, cosmetic.** The row's description says "Benchmark score = plain accuracy over the cases run; the eval's precision and coverage are not reproduced" (`apps/screamingface-engine/src/screamingface_engine_inspect/benchmarks.py:6706`). That is not one of the declared forms: there is no `# NAMED DEVIATION` line and no README paragraph.
- **Where.** Ours: `single_shot.py:1275-1310` publishes the mean plus `correct` and `scored_cases`. Theirs: `inspect_evals:lab_bench/scorer.py:17` also reports `precision()` (`inspect_evals:lab_bench/metrics.py:62-90`), `coverage()` (`:93-118`) and `stderr()`.
- **What differs.** LAB-Bench's own emphasis is precision: correct out of attempted, where choosing "Insufficient information" is not an attempt. We do not compute it, though the per-Case marks we keep are enough to. The headline (accuracy) is unchanged.
- **Severity / bound.** `cosmetic`, `0`. No Case's mark and no headline digit changes (Checks 8).

## Checks run

- [x] **Read-only on the checkout.** Nothing in the checkout is from this audit. `git status --porcelain` was **not empty before**. It showed three untracked files from the calling session: `docs/work/2026-11-09-fidelity-sweep.md`, `…/benchmarks-fidelity/frames_oracle.md` and `…/musique.md`. After, it showed those plus ten more `?? apps/screamingface-engine/docs/benchmarks-fidelity/*.md` records the calling session wrote during the audit (none named `inspect-lab_bench_tableqa.md`). This audit wrote nothing under the checkout. Every file lived under `$SCRATCH=/private/tmp/claude-501/…/scratchpad/audit-lab_bench_tableqa-8p3S`, deleted at the end. The replay child's own `/private/tmp/task-replay-*` temporary folder removed itself (`ls` → no matches).
- [x] **No keys, no model.** `env -i PATH="$PATH" HOME="$SCRATCH" UV_CACHE_DIR="$SCRATCH/uv-cache" env | grep -iE 'key|token|secret'` → empty output, `grep exit=1`.
  - **One exception.** The first command, which only located the installed `inspect_evals/lab_bench` folder and printed versions, ran `uv run --isolated --extra inspect python -c …` *without* the `env -i` prefix. It imported `inspect_evals` and `inspect_ai`, printed a path and `0.20.0 0.3.263`, and made no network or model call.
  - Every later command, ours and third-party, ran under the prefix.
  - The harness's `get_completion` was replaced by a stand-in returning pre-written replies. chembench's LLM fallback `llm_extraction` was replaced by a recorder that returns no letter. inspect's `generate` was replaced by a stand-in that sets the reply.
  - No model, gateway or provider was called. The harness's `.env` holds only `HF_DATASET_REPO=futurehouse/lab-bench` and `PUBLIC_RELEASE=True`.
- [x] **Harness over paper.** The disagreement between the paper's full set (public plus private) and the harness's public 244 is recorded in Upstream notes, not Deviations.
- [x] **Declared is not a finding.** No `# NAMED DEVIATION` line, `named_deviations/` scorer, `dropped_scorers` or `excluded_sample_ids` touches this row. D1 is undeclared and cosmetic, bound 0. The seed pin is not counted as a deviation, because inspect's own shuffle produces it (dataset row).
- [x] **Every cell has evidence.** Each `match` names its command and output lines, or its two source locations.
- [x] **Every `file:line` copied from command output.** Commands:
  - `grep -n` on `benchmarks.py` (`key="lab_bench_tableqa"|Serving order and choice order|precision and coverage are not|failure_policy="withhold"|scorer=…precision_choice|scorer_kwargs=|mean of 3 runs|max_tokens|temperature`, filtered to lines 6690-6770).
  - `grep -n` on `prepare.py` (`"lab_bench_tableqa": TaskReplayCasesSpec|case_count=244|case_digest="9be147|shuffle_seed=7|choice_shuffle_seed=7|"futurehouse/lab-bench": "5c77`), `scorer_adapter.py` (`_INSPECT_LETTER_SCORE_VALUES: Mapping|set_choices_based_on_generated_response(state, parse_answers`), `single_shot.py` (`^def _accuracy|score=round(sum(values) / len(cases), 4)|_accuracy$`), `fetch_pins.py` (`if forced.get("shuffle") is True|if forced.get("shuffle_choices") is True`) and `aggregation.py` (`return tuple(cases) if failure_policy == "withhold"`).
  - `cat -n` and `grep -n` on each inspect_evals `lab_bench/*.py` file copied from the installed package.
  - `grep -n` on `inspect_ai:solver/_multiple_choice.py`, `scorer/_metric.py` and `scorer/_metrics/accuracy.py`.
  - `grep -n` on the harness's `labbench/{utils,zero_shot,evaluator,anthropic,openai}.py`, `TableQA/task.py` and `scripts/score_baseline.py` at `a767892`, and on chembench's `src/chembench/{utils,constant}.py` at `7ad84e6`.
- [x] **A verdict never claims more than its evidence.** No dimension is `unchecked`, and no `possibly-score-changing` deviation is open against inspect_evals.
- No `ours` override was set.

1. Checkout `…/.claude/worktrees/fidelity-sweep-pr1`: `git rev-parse --short HEAD` → `43d3942f6`. `git status --porcelain` → the three untracked files above.
2. `SCRATCH=$(mktemp -d …/audit-lab_bench_tableqa-XXXX)` → `…/audit-lab_bench_tableqa-8p3S`. Key grep → empty (above). Copied the installed `inspect_evals/lab_bench/` and `inspect_ai/{solver,scorer}/` into `$SCRATCH` under `env -i` for reading.
3. Our side, from the Engine root: `env -i … HF_HUB_DISABLE_XET=1 uv run --isolated --extra inspect python -I ours.py` printed:
   - `fingerprint 9990079555f06a35`, `origin 'inspect_evals'`, `harness_url 'https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0/src/inspect_evals/lab_bench'`, `paper_url 'https://arxiv.org/abs/2407.10362'`
   - `declaration BenchmarkDeclaration(failure_policy='withhold', interaction='single_shot', difficulty='medium', attempts=1)`, `judge None`
   - `replay seconds 286.5`, `count 244 pinned 244`, `digest 9be147a0caa0ba845731b8d93a7e9b4af406708e93cba62d4bc440cae87ff412 pinned 9be147a0caa0ba845731b8d93a7e9b4af406708e93cba62d4bc440cae87ff412 equal True`. That is `replayed_cases(TASK_REPLAY_CASES["lab_bench_tableqa"])`, the production replay child.
4. Harness: `git clone https://github.com/Future-House/LAB-Bench harness` → HEAD `998a8e0a40cf116c80e1b0e7a805ebb5fb9fa838` (2025-09-27); `git checkout a767892307ad38a5f4f77cd00d30c2442aaea791` (2024-07-13, "mirroring repo", the first public commit, the code at the paper's time). `git diff --stat a767892 HEAD -- labbench TableQA` shows only import moves, lint rewrites and env defaults in the grading files, and edits to `tableqa-v1-public.jsonl`.
   - **Install.** The harness's dependency `chem-bench` is not on PyPI at the pin date: `uv pip install --exclude-newer 2024-07-14 … chem-bench` → `chem-bench was not found in the package registry`.
   - **Workaround.** Cloned [lamalab-org/chembench at `7ad84e6`](https://github.com/lamalab-org/chembench/tree/7ad84e632fb3cb6505711575759457bf0afb65f7) (2024-07-12, last commit before the pin) and installed only what its `utils.py` imports (`pint fastcore loguru`, plus `pydantic~=2.0 Pillow python-dotenv datasets tqdm`, all `--exclude-newer 2024-07-14`) into `$SCRATCH/venv`.
   - **Provider SDKs left out.** A stub `labbench/__init__.py` drops the four provider agents. `utils.py`, `evaluator.py` and `zero_shot.py` are the harness's files (`cmp` → identical ×3), and `TableQA/` is a symlink to the clone.
5. `env -i … uv run --isolated --extra inspect python -I compare.py ours.json compare.json` (inspect_evals' `hf_dataset(path, name="TableQA", split="train", sample_fields=record_to_sample_tableqa, shuffle=True, seed=7, shuffle_choices=7, revision=LAB_BENCH_DATASET_REVISION)`, then `task_base(ds).solver` with a stand-in `generate`, then `precision_choice(no_answer=UNCERTAIN_ANSWER_CHOICE)`; ours via `imported_benchmark("lab_bench_tableqa").aggregation().grade_case`):
   - `samples 244 cases 244`, `multiple_correct False`
   - `prompt: Cases whose Candidate input (text bytes + image data URLs, role, part order) != inspect's rendered messages: []`
   - `material: Cases whose target/choices != inspect Sample: []`
   - `answer sheets: 3660 marks; identical 3660 differing 0 []`
   - per-sheet ours sums: `gold`, `gold_lower`, `gold_period`, `gold_after_cot`, `gold_trailing_comma`, `last_of_two` → 244; `gold_parenthesised`, `gold_prose`, `gold_bare`, `gold_harness_tags`, `wrong`, `refuse`, `two_letters`, `out_of_range`, `empty` → 0; `refuse` → `theirs_NOANSWER 244`.
6. `env -i … PYTHONPATH=$SCRATCH/hstub:$SCRATCH/chembench/src HF_DATASET_REPO=futurehouse/lab-bench PUBLIC_RELEASE=True $SCRATCH/venv/bin/python harness_sheets.py` ran the harness's own `Evaluator(Eval.TableQA).score_agent(BaseZeroShotAgent.run_task)` at `a767892`:
   - `harness instances 244`
   - `tagged_gold {'accuracy': 1.0, 'precision': 1.0, 'coverage': 1.0, 'n_total': 244} llm_fallback_calls 0`
   - `tagged_wrong {'accuracy': 0.0, …, 'coverage': 1.0} llm_fallback_calls 0`
   - `tagged_refuse {'accuracy': 0.0, 'precision': 0.0, 'coverage': 0.0} llm_fallback_calls 0`
   - `inspect_format_gold {'accuracy': 0.0, …, 'coverage': 1.0} llm_fallback_calls 244`
   - `empty {'accuracy': 0.0, …} llm_fallback_calls 244`
   - The printed example prompt (1 image): `…Please answer by responding with the letter of the correct answer.\nThink step by step.\n\nQuestion: …\n\nOptions:\n(A) Thaha et al 2010\n(B) Insufficient information to answer the question\n(C) Simillis et al 2018\n…\n\nYou MUST include the letter of the correct answer within the following tags: [ANSWER] and [/ANSWER].…`
7. `env -i … python3 -I dataset_vs_harness.py` (ours.json + compare.json Sample ids vs `git show <rev>:TableQA/tableqa-v1-public.jsonl` and `git show <rev>:TableQA/<table-path>`):
   - `harness@a767892: rows 244; ids only ours []; only harness []`, `question differs [26, 149]`, `ideal differs []`, `distractor set differs []`, `image count differs []`, `image bytes differ []`
   - `harness@998a8e0: rows 244; ids only ours []; only harness []`, all five lists `[]`
   - The two questions: Case 26 (`307cb0ea…`) `…2.0mm baps…` → `…2.0mm gaps…`; Case 149 (`515e45ae…`) a trailing `\n` dropped. Changed upstream in `4e1a3d8`/`7c7d22b`/`dafdc64`/`122cc50` (2025-07).
8. `env -i … uv run --isolated --extra inspect python -I rollup.py compare.json` (our `single_shot._accuracy` over stand-in Case results vs inspect `accuracy()`, plus inspect_evals' `precision()`/`coverage()` for reference), every line `equal True`:
   - `all_C ours 1.0000 inspect_accuracy 1.0000`
   - `all_I 0.0000 / 0.0000`
   - `alternating_C_I 0.5000 / 0.5000`
   - `every_3rd_N_else_C 0.6639 / 0.6639 (precision 1.0000 coverage 0.6639)`
   - `C_I_N_cycle 0.3361 / 0.3361 (precision 0.5031 coverage 0.6680)`
   - all 15 `sheet_*` vectors equal.
9. `env -i … uv run --isolated --extra inspect pytest "tests/unit/inspect/test_inspect_imported_benchmarks.py::test_lab_bench_benchmarks_pin_a_choice_order" "tests/unit/inspect/test_inspect_task_replay_benchmarks.py::test_lab_bench_never_keys_every_case_to_one_letter[lab_bench_tableqa]" -q -p no:cacheprovider` → `2 passed, 1 warning in 40.49s`. Gold-letter spread from compare.json: `A 32, B 42, C 43, D 44, E 38, F 25, G 11, H 9`. Pictures per Case: `1: 229, 2: 12, 3: 3`.
10. After: `git status --porcelain` → no file from this audit (see the first checkbox). The scratch folder was then deleted.

## Recommended paid runs

None needed for this verdict: no judge, and every dimension against inspect_evals is settled without a model.

One run is optional. It would put a number on the inspect_evals-vs-harness gap (U1, U2):
- **What:** one model over the 244 Cases twice, once with inspect_evals' prompt and extractor and once with the harness's `MCQ_INSTRUCT_TEMPLATE` and `[ANSWER]` extraction.
- **The catch:** the harness's tag-less replies need its Anthropic LLM fallback, which is itself a model call.
- **Size:** 488 Candidate calls plus up to 244 extractor calls.

It would not change the verdict, which already reads `comparable-to-inspect`.

## Upstream notes

Where [inspect_evals](https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0/src/inspect_evals/lab_bench) differs from the [authors' harness at `a767892`](https://github.com/Future-House/LAB-Bench/tree/a767892307ad38a5f4f77cd00d30c2442aaea791). This is the `comparable-to-inspect` evidence. None of it is counted against us.

- **U1 — prompt template (inspect_evals vs harness; `unbounded`).**
  - **Harness:** `MCQ_INSTRUCT_TEMPLATE` (`fork:labbench/zero_shot.py:15-24`). It asks for `[ANSWER]<answer>[/ANSWER]` (`:23`), lists options as `(A) …` (`fork:labbench/utils.py:139`), puts `Think step by step.` straight after the instruction line (chembench `COT_PROMPT`, `src/chembench/constant.py:61`), and runs `post_process_prompts` (`zero_shot.py:52`). Its opt-out option is `"Insufficient information to answer the question"` with no full stop (`fork:labbench/utils.py:24`), inserted and shuffled by an unseeded `random.shuffle` (`:131-146`).
  - **inspect_evals:** asks for `ANSWER: $LETTER` with `A) …` options (`inspect_evals:lab_bench/lab_bench.py:47-58`), and its opt-out ends in a full stop (`inspect_evals:lab_bench/record_to_sample_helpers.py:13`).
  - **Bound:** the wording changes what the model writes, so it cannot be bounded without a paid run.
- **U2 — answer extraction, with a model in the harness (inspect_evals vs harness; `unbounded`).**
  - **Harness:** chembench's `prepare_mcq_answer` (`fork:labbench/zero_shot.py:68-78`) runs the `MCQ_REGEX_TEMPLATE_1` tag regex (`src/chembench/constant.py:65`). With `llm_fallback: bool = True` (`src/chembench/utils.py:267`), any reply without tags goes to `llm_extraction` (`:296`). That builds `ChatAnthropic(temperature=0)` (`:80`) and asks it for the letter. The options it shows the extractor are re-permuted with `permute_options(…, seed)` (`:83-90`).
  - **inspect_evals:** reads `ANSWER: X` only (`inspect_ai:solver/_multiple_choice.py:82`).
  - **Evidence:** a correct `ANSWER: X` reply → harness: 244/244 sent to the LLM fallback. A correct `[ANSWER]X[/ANSWER]` reply → inspect_evals: 0/244 correct (Checks 5, 6).
  - **Bound:** the paper's number therefore includes model-extracted marks; `unbounded`.
- **U3 — picture delivery (inspect_evals vs harness; `possibly-score-changing`, `unknown`).**
  - **Harness:** re-saves each table through PIL (`fork:labbench/utils.py:149-156`). Its OpenAI wrapper sends the text before the pictures (`fork:labbench/openai.py:27-36`). Its Anthropic wrapper sends the pictures first (`fork:labbench/anthropic.py:23-36`), as inspect_evals does.
  - **inspect_evals:** sends the dataset's PNG bytes untouched. Those bytes equal the harness's `TableQA/tables/*.png` files (Checks 7).
- **U4 — dataset (paper vs harness vs inspect_evals).**
  - **Paper:** its TableQA numbers cover the public plus the private split. The row's comment says so (`apps/screamingface-engine/src/screamingface_engine_inspect/benchmarks.py:6744`). This audit did not open the paper.
  - **Harness public file and Hub:** equal on all 244 rows at HEAD. The paper-time file differs only in two question texts: Case 26's `baps` → `gaps` typo and Case 149's trailing newline (Checks 7). That is `2/244 = 0.0082`, but it is an authors' correction, not ours.
- **U5 — metric and roll-up agree.** The harness's `correct = agent_output == target_output` / `sure = agent_output != unsure` (`fork:labbench/evaluator.py:87-88`) and `accuracy = n_correct / n_total` (`:128`) give the same accuracy as inspect_evals' `precision_choice` + `accuracy()` on every tagged sheet. `tagged_refuse` reads `accuracy 0.0, coverage 0.0` on the harness and `accuracy 0.0000, coverage 0.0000` on inspect_evals (Checks 5, 6).
- **U6 — sampling.** The harness's Anthropic wrapper defaults `max_tokens` to 1024 (`fork:labbench/anthropic.py:14`). The baseline script turns on CoT (`fork:scripts/score_baseline.py:63`). The row reports the paper's number as a mean of 3 runs (`benchmarks.py:6746`). inspect_evals fixes nothing and runs one epoch.
