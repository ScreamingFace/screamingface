---
benchmark: inspect-lab_bench_protocolqa
origin: inspect_evals
verdict: unverified
verdict_reason: "OME-1907 (2026-11-13): grading now reads an answer inside a wrapper, such as 'ANSWER: $B' or 'ANSWER: **B**', that inspect_ai v0.3.263 reads as no answer (our Named Deviation for inspect_ai issue 5055), so a reply with a wrapper can grade differently from inspect's; only a paid run can bound how often that happens, so the rule gives unverified. Verdict before: comparable-to-inspect. "
audited: 2026-11-09
audited_at: 43d3942f6
fingerprint:
  benchmark: 236b15e7b2c90e9b
  harness_url: https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0/src/inspect_evals/lab_bench
references:
  paper: https://arxiv.org/abs/2407.10362v3
  original_harness: https://github.com/Future-House/LAB-Bench/tree/a767892307ad38a5f4f77cd00d30c2442aaea791
  inspect_evals: https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0
  inspect_ai: https://github.com/UKGovernmentBEIS/inspect_ai/tree/v0.3.263
parity_test: none
parity_test_reason: "no parity test exists for this row; this audit's answer sheets stand in for one: 108 Cases x 14 replies, run through our grade hook and through inspect_evals' own lab_bench_protocolqa Task under inspect eval() with the in-process mockllm stub"
---

# LAB-Bench ProtocolQA — Fidelity Record

## Verdict

**`comparable-to-inspect`.** Our LAB-Bench ProtocolQA grades the same way as [inspect_evals' `lab_bench_protocolqa` (v0.20.0)](https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0/src/inspect_evals/lab_bench) on all seven dimensions.

- **Prompts.** All 108 Candidate prompts are byte-identical to the user message inspect's own `eval()` sent for the same Sample.
- **Marks.** All 1,512 answer-sheet marks are identical (108 Cases × 14 replies).
- **Headline.** Our headline equals inspect's `accuracy()` to four decimals on six fixed mark vectors.

Our headline can therefore sit beside an inspect_evals run of this Task (accuracy over the 108 public questions). It cannot sit beside the [paper's Table 2](https://arxiv.org/abs/2407.10362v3) accuracy. inspect_evals gives the Candidate a different prompt and a different answer format from the [authors' harness](https://github.com/Future-House/LAB-Bench/tree/a767892307ad38a5f4f77cd00d30c2442aaea791), and it extracts answers differently (Upstream notes U1, U2). Every one of the 108 Cases is rendered differently, so every Case can mark differently.

The arithmetic:

- `sum of bounds against inspect_evals = 0/108 = 0.0000 ≤ COMPARABLE_TOLERANCE (0.005)`. The one deviation, D1, is cosmetic with bound 0.
- `inspect_evals vs original harness: prompt bytes differ on 108/108 Cases = 1.0000 > 0.005`. That is beyond tolerance.

So the rule gives `comparable-to-inspect`. The inspect-vs-harness gap is not an open deviation of ours, so the verdict is not `unverified`. That gap belongs to inspect_evals, it is recorded in Upstream notes, and its affected Cases are enumerated (all 108). How large it is in points would take a paid paired run (see Recommended paid runs). None of `prompt`, `answer extraction`, `metric` or `roll-up` is `unchecked`.

## Dimensions

| dimension | status | severity | bound | evidence |
|---|---|---|---|---|
| dataset | match | — | — | **Ours.** The row pins Hub `futurehouse/lab-bench` at `5c77cec648430f30611808808861eb86f81d5eaa`, with `case_count=108` and `shuffle_seed=7` / `choice_shuffle_seed=7` (`apps/screamingface-engine/src/screamingface_engine_inspect/prepare.py:1219-1231`; pin `:1226`, seeds `:1228-1229`). That is inspect_evals' own pin (`inspect_evals:lab_bench/lab_bench.py:33`). Replaying gives `cases 108 digest 06f94fdd… pinned 06f94fdd… equal True` (Checks 4). **Theirs.** inspect_evals asks `hf_dataset(… 'shuffle': True, 'shuffle_choices': True, 'revision': '5c77cec6…')` with no seed (`inspect_evals:lab_bench/lab_bench.py:75-76`). Given seed 7 for both shuffles, its own build gives `positions whose (choices, target) differ from our Grading Material: []` (Checks 6). Because inspect fixes no seed, our order is one draw from inspect's own shuffle. **Harness.** At `a767892` the harness reads `ProtocolQA/protocolqa-v1-public.jsonl` (`fork:labbench/utils.py:165`): 108 rows, sha256 `08e85d9c…`, the same bytes at HEAD `998a8e0`. Hub at the pin vs that file: `ids only in hub [] only in harness []`, and `protocol`/`question`/`ideal`/`distractors` differ on `[]`. Order is equal, and our 108 Case ids equal the Hub ids as a set with 0 duplicates (Checks 7). |
| prompt | match | — | — | inspect_evals' own Task (`multiple_choice(template=MULTIPLE_CHOICE_TEMPLATE, cot=True)`, `inspect_evals:lab_bench/lab_bench.py:152`, template `:47-58`; input `"Protocol: " + protocol + "\n\n" + question`, `inspect_evals:lab_bench/record_to_sample_helpers.py:81`) ran under inspect `eval()`. For all 108 Samples, the user message it sent equals our Candidate input byte for byte: `positions whose inspect user-message bytes != our Case input: []`. Each sample has one user message and no system message: `system messages: 0 non-assistant messages per sample: {1}` (Checks 8). The difference from the original harness is upstream (U1). |
| answer extraction | match | — | — | Ours replays inspect's own `parse_answers` + `set_choices_based_on_generated_response` (`apps/screamingface-engine/src/screamingface_engine_inspect/scorer_adapter.py:651`), the functions inspect's solver calls (`inspect_ai:solver/_multiple_choice.py:334`; regexes `:98`, `:107`; last match `:115`; upper-case `:121`; single letter `:148`). One structural difference cannot change a mark. The solver marks options only `if answers:` (`:335`), while we always mark them, so an unparsed reply leaves `False` where inspect leaves `None`. `precision_choice` reads only `correct is True` (`inspect_evals:lab_bench/scorer.py:44,54`), and the empty and unparseable sheets marked identically on both sides (Checks 9-10). |
| metric | match | — | — | The row's scorer is inspect_evals' own `precision_choice` with `no_answer="Insufficient information to answer the question."` (`apps/screamingface-engine/src/screamingface_engine_inspect/benchmarks.py:1618-1619`), the Task's own setting (`inspect_evals:lab_bench/lab_bench.py:153`). Answer sheets: 108 Cases × 14 replies = 1,512 marks through our grade hook vs inspect `eval()` → `marks compared 1512 differing 0` (Checks 9-10). Per kind, theirs then ours: gold, gold lower-case, CoT + `ANSWER: X.`, `**ANSWER: X**`, wrong-then-gold → C ×108 and 1.0. `(X)`, prose `The answer is X.`, `[ANSWER]X[/ANSWER]`, inline `answer: X is right`, wrong, empty, two letters, gold-then-wrong → I ×108 and 0.0. Opt-out letter → N ×108 and 0.0 (our map `"N": 0.0`, `scorer_adapter.py:111`). No Case failed grading on any sheet. No goldens with real replies exist for this row (`grep -rli protocolqa tests/` finds only catalogue tests). |
| roll-up | deviation | cosmetic | 0 (D1) | **Headline equal.** Six fixed C/I/N vectors over 108 Cases went through our `_accuracy` (`apps/screamingface-engine/src/screamingface_engine_inspect/single_shot.py:1275`; `score=round(sum(values) / len(cases), 4)` at `:1303`; chosen at `:1160-1161` because the row has no whole-run metric). They also went through inspect's `accuracy()` (`noanswer` → 0, `inspect_ai:scorer/_metric.py:283`) and the harness's `compute_metrics` (`fork:labbench/evaluator.py:118-130`). Results are equal to four decimals on every vector: all-C 1.0, all-I 0.0, alternating 0.5, every-3rd-N 0.6667, C/I/N cycle 0.3333, mixed 0.3241 (Checks 11-12). **Differs:** we publish accuracy only, while inspect also publishes precision, coverage and stderr (D1). `failure_policy="withhold"` (`benchmarks.py:1614`) never fired: no sheet produced an ungraded Case. |
| judge | not applicable | — | — | `imported_benchmark("lab_bench_protocolqa").judge` is `None` (Checks 2). The scorer is deterministic letter matching (`inspect_evals:lab_bench/scorer.py:17-59`), and the harness compares strings (`fork:labbench/evaluator.py:87-88`). |
| sampling | match | — | — | **Ours:** `declaration=BenchmarkDeclaration(… interaction='single_shot', … attempts=1)`, and the row sets no `max_tokens` or `temperature` (grep over `benchmarks.py:1594-1656` finds none, Checks 13). **inspect_evals:** `Epochs(1, "mode")` (`inspect_evals:lab_bench/lab_bench.py:154`), and `multiple_choice` takes `max_tokens: int \| None = None` (`inspect_ai:solver/_multiple_choice.py:247`), which the Task leaves unset. **Harness:** it passes `model` only to OpenAI (`fork:labbench/openai.py:14`) and adds `max_tokens=1024` for Anthropic (`fork:labbench/anthropic.py:14`). **Paper:** no temperature or token cap is stated; it averages three runs (Table 2 caption, p.23). These are knobs the paper leaves open. |

## Deviations

### D1 — precision and coverage are not published

- **Undeclared.** The row's description says "Benchmark score = plain accuracy over the cases run" (`apps/screamingface-engine/src/screamingface_engine_inspect/benchmarks.py:1606`). But no `# NAMED DEVIATION` line, `named_deviations/` scorer or linked README covers it.
- **Where.**
  - Ours: `_accuracy` publishes `score` (accuracy) plus `correct` and `scored_cases` (`apps/screamingface-engine/src/screamingface_engine_inspect/single_shot.py:1275-1310`).
  - Theirs: `@scorer(metrics=[accuracy(), precision(), coverage(), stderr()])` (`inspect_evals:lab_bench/scorer.py:17`). Precision drops NOANSWER Cases from the denominator (`inspect_evals:lab_bench/metrics.py:81`).
- **What differs.** Our result carries no LAB-Bench precision or coverage, and the published counts cannot rebuild them. A Case where the Candidate picked the opt-out scores 0.0, like a wrong answer (`scorer_adapter.py:111`). Our result's own `coverage` field means Cases graded, not LAB-Bench's "questions attempted", so a reader should not take it as LAB-Bench coverage.
- **Severity / bound.** `cosmetic`, `0`. No Case's mark and not the headline can change: accuracy is inspect's first metric and the paper's Table 2 metric. The six roll-up vectors give equal accuracy on every vector (Checks 11-12).

## Checks run

- [x] **Read-only on the checkout.** No tracked file changed, and nothing under the checkout was written by this audit; every file lived under the scratch folder. The status was not literally empty: before, `git status --porcelain` showed the calling session's untracked ledger, `docs/work/2026-11-09-fidelity-sweep.md`; after, the same file plus ten untracked `docs/benchmarks-fidelity/*.md` records written meanwhile by the calling sweep session (none for this Benchmark). Scratch: `SCRATCH=…/scratchpad/audit-lab_bench_protocolqa-xLbf`, deleted with `rm -rf "$SCRATCH"` (Checks 15).
- [x] **No keys, no model.**
  - `env -i PATH="$PATH" HOME="$SCRATCH" UV_CACHE_DIR="$SCRATCH/uv-cache" env | grep -iE 'key|token|secret'` printed nothing (`grep exit=1`).
  - Every later command ran under `env -i`. Checks 2-3 used the real `HOME` and uv cache, still under `env -i` with no key in the environment. From Checks 4 on: `HOME="$SCRATCH" UV_CACHE_DIR="$SCRATCH/uv-cache" HF_HOME="$SCRATCH/hf"` and `python -I`.
  - No model, gateway or provider was called. The "model" in the inspect runs was inspect_ai's in-process `mockllm/model`, which returned the pre-written sheet for the prompt it was given.
  - The harness repo ships a `.env`. Only its variable names were read (`HF_DATASET_REPO`, `PUBLIC_RELEASE`). It was never sourced, and no harness module that calls `load_dotenv` was imported.
- [x] **Harness over paper.** The paper (135 questions, public plus private, three-run mean) and the public harness (108) disagree; that is recorded in U4, not in Deviations.
- [x] **Declared is not a finding.** D1 is undeclared and cosmetic. The seeded order is not a deviation: inspect fixes no seed, and its own shuffle under seed 7 reproduces our 108 option orders (Checks 6).
- [x] **Every cell has evidence.** Each `match` names its command output or its two source locations.
- [x] **Every `file:line` copied from command output.** The citations come from these `grep -n`/`sed -n` runs:
  - ours: `grep -n 'lab_bench_protocolqa' prepare.py benchmarks.py`; `grep -n 'precision_choice"\|scorer_kwargs=…\|plain accuracy…\|failure_policy="withhold"\|inspect_evals_case_count=108' benchmarks.py`; `grep -n 'case_count=108\|shuffle_seed=7\|…' prepare.py`; `grep -n '_INSPECT_LETTER_SCORE_VALUES: Mapping\|set_choices_based_on_generated_response(state, parse_answers' scorer_adapter.py`; `grep -n '^def _accuracy\|score=round…\|if metric_factory is None' single_shot.py`
  - inspect_evals: `grep -n … lab_bench/{lab_bench,record_to_sample_helpers,scorer,metrics}.py` on a copy of the installed `inspect_evals` 0.20.0
  - inspect_ai: `grep -n … solver/_multiple_choice.py scorer/_metric.py` on a copy of the installed `inspect_ai` 0.3.263
  - harness: `grep -n … labbench/{zero_shot,utils,evaluator,anthropic,openai}.py ProtocolQA/task.py` after `git checkout a767892`
  - paper: `grep -n` on `pdftotext -layout` output, with pages counted from form feeds
- [x] **A verdict never claims more than its evidence.** No dimension is `unchecked`, and no `possibly-score-changing` deviation of ours is open.
- No `ours` override was set.

1. `git -C …/fidelity-sweep-pr1 status --porcelain` → `?? docs/work/2026-11-09-fidelity-sweep.md`; `git rev-parse --short HEAD` → `43d3942f6`.
2. Our side, from the Engine root: `env -i … uv run --isolated --extra inspect python -c "imported_benchmark('lab_bench_protocolqa')…"`. Output:
   - `fingerprint 236b15e7b2c90e9b`, `origin inspect_evals`, `harness_url https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0/src/inspect_evals/lab_bench`, `paper_url https://arxiv.org/abs/2407.10362`, `judge None`
   - `declaration BenchmarkDeclaration(failure_policy='withhold', interaction='single_shot', difficulty='hard', attempts=1)`
   - `whole_run_metric_factory None`, `named_scores ()`, `multiple_correct False`
   - versions `0.20.0 0.3.263` (inspect-evals, inspect-ai)
3. Copied the installed `inspect_evals/` and `inspect_ai/` trees into scratch to read and grep them.
4. `env -i … HF_HUB_DISABLE_XET=1 uv run --isolated --extra inspect python -I ours_cases.py` (calls `replay_with_provenance(TASK_REPLAY_CASES["lab_bench_protocolqa"])`) → `cases 108 digest 06f94fdd1c65c0872d6c6cde6afe35019a97e3ac40240771cebfa7fa022fc76f pinned 06f94fdd… equal True`. Option counts `{5: 77, 6: 21, 7: 9, 8: 1}`; every Case has exactly one opt-out option, and none has it as gold.
5. `git clone https://github.com/Future-House/LAB-Bench harness`. The history's first commit is `a767892 2024-07-13 "mirroring repo"`, the only commit before paper v3 (17 Jul 2024). `git diff a767892 HEAD -- labbench/zero_shot.py labbench/utils.py labbench/evaluator.py ProtocolQA/task.py` shows formatting, import paths (`chembench.utils` → `chembench.constant`/`chembench.prompter`), `.env` reading made optional, and an added `source` field. Template text and grading logic are unchanged; one template line is rewrapped onto three. The reference is pinned at `a767892`.
6. Theirs: `env -i … uv run --isolated --extra inspect python -I theirs.py`. It wraps `inspect_evals.lab_bench.lab_bench.hf_dataset` to add `seed=7` and `shuffle_choices=7` (written for this audit, not our `fetch_pins`), builds `lab_bench_protocolqa()`, and runs inspect `eval()` once per sheet kind with `mockllm/model` answering through a callable. Output:
   - `hf_dataset call (before seeding): [{'path': 'futurehouse/lab-bench', 'name': 'ProtocolQA', 'split': 'train', 'shuffle': True, 'shuffle_choices': True, 'revision': '5c77cec6…'}]`
   - `samples 108`
   - `positions whose (choices, target) differ from our Grading Material: []`
   - for each of the 14 kinds, `samples 108 unmatched prompts 0`
7. `env -i … HF_HUB_OFFLINE=1 uv run --isolated --extra inspect python -I dataset_cmp.py`. Output:
   - `hub rows 108 columns ['id','question','ideal','distractors','canary','source','protocol','subtask'] harness rows 108`
   - `ids only in hub [] only in harness []`; `protocol`, `question`, `ideal`, `distractors` each differ on `[]`
   - `hub order == harness order True`; `our 108 Case ids … == hub ids as a set True dupes 0`
   - harness file at `a767892` and at HEAD: both sha256 `08e85d9c0afb85a3919b78a44095eabdc031ad77652da2ccc59407a162bd63a4`, 108 lines
8. Prompt bytes, from the inspect `eval()` logs (gold-sheet run), compared per position with our Case inputs:
   - `positions whose inspect user-message bytes != our Case input: []`
   - `system messages: 0 non-assistant messages per sample: {1}`
   - `position mapping consistent: True`
9. Our side of the answer sheets: `env -i … uv run --isolated --extra inspect python -I ours_sheets.py`. It sends 14 replies per Case through `imported_benchmark(...).aggregation().grade_case(GradeRequest(...))`. Per kind, mean and `failures 0`: gold 1.0, gold_lower 1.0, gold_cot_period 1.0, gold_paren 0.0, gold_prose 0.0, gold_harness_tags 0.0, gold_bold 1.0, gold_inline 0.0, wrong 0.0, unsure 0.0, empty 0.0, two_letters 0.0, gold_then_wrong 0.0, wrong_then_gold 1.0.
10. Compared per Case (theirs `C`/`I`/`N` → 1/0/0) → `marks compared 1512 differing 0 []`. Theirs per kind: C ×108 on gold, gold_lower, gold_cot_period, gold_bold, wrong_then_gold; N ×108 on unsure; I ×108 on the rest. inspect's own metrics on the unsure run: `accuracy 0.0, precision 0.0, coverage 0.0`.
11. Roll-up, inspect and ours: `env -i … uv run --isolated --extra inspect python -I rollup.py vectors.json`. Each vector prints inspect's accuracy / precision / coverage, then ours, then `equal4dp`:
    - `all_C`: 1.0 / 1.0 / 1.0, ours 1.0, True
    - `all_I`: 0.0 / 0.0 / 1.0, ours 0.0, True
    - `alternating_C_I`: 0.5 / 0.5 / 1.0, ours 0.5, True
    - `every_3rd_N_else_C`: 0.6667 / 1.0 / 0.6667, ours 0.6667, True
    - `C_I_N_repeating`: 0.3333 / 0.5 / 0.6667, ours 0.3333, True
    - `first_40_C_then_I_with_every_7th_N`: 0.3241 / 0.3763 / 0.8611, ours 0.3241, True
12. Harness side, in a scratch venv: `uv venv --python 3.12` + `uv pip install chembench==0.3.0` (the version in the harness's `uv.lock`; install took ~13 min). `env -i … venv/bin/python -I harness_side.py`:
    - It execs `compute_metrics` from `git show a767892:labbench/evaluator.py` and gets the same accuracy / precision / coverage as Checks 11 on all six vectors (e.g. mixed `0.3241 / 0.3763 / 0.8611`).
    - It also probes the extractor (`zero_shot.py` logic, with no `llm_extractor` passed): `[ANSWER]C[/ANSWER]`→`'C'`; `[ANSWER]c[/ANSWER]`→raises `TypeError`; CoT then tag→`'C'`; `[ANSWER]C, A[/ANSWER]`→`'C'`; `[ANSWER]C[/ANSWER] … [ANSWER]A[/ANSWER]`→`'A'`; `[ANSWER]A[/ANSWER] … [ANSWER]C[/ANSWER]`→`'A'`; `ANSWER: C`→`None`; bare `C`→`'C'`; empty→raises `TypeError`.
13. Sampling: `grep -n "max_tokens\|temperature" benchmarks.py | awk '$1>=1594 && $1<=1656'` → no lines.
14. Paper: `curl https://arxiv.org/abs/2407.10362` → `Submitted on 14 Jul 2024 … last revised 17 Jul 2024 (this version, v3)`. `curl https://arxiv.org/pdf/2407.10362v3` + `pdftotext -layout`. Read:
    - Table 1 (p.5): ProtocolQA, 135 questions
    - §2.2 (p.6): 0-shot CoT, answers parsed from text, an option to decline; accuracy = correct / all, precision = correct / attempted
    - Table 2 caption (p.23): "measured over the entire dataset (both public and private splits), and averaged over three runs"
    - B.1 (p.25): 80% public subset
15. `rm -rf "$SCRATCH"` → `No such file or directory`. `git status --porcelain` → the pre-existing `docs/work/2026-11-09-fidelity-sweep.md` plus ten fidelity records from the calling session; no tracked file modified. `git rev-parse --short HEAD` → `43d3942f6`.

## Recommended paid runs

No paid run is pending for this verdict.

One optional run would size the inspect-vs-harness gap (U1 + U2), but only if the owner wants this row to aim at `comparable-to-paper`:

- **What:** a paired run of one model on the 108 Cases, once with inspect_evals' prompt and `ANSWER:` extraction, and once with the harness's `MCQ_INSTRUCT_TEMPLATE`, option labels, opt-out text, protocol join and `[ANSWER]` extraction.
- **Size:** 2 × 108 calls, three runs each to match the paper's averaging.
- **Judge:** none.

## Upstream notes

- **U1 — inspect_evals vs harness: prompt (bound 108/108 = 1.0000).** Every Case renders differently, in five ways:
  - **Template wording:** `inspect_evals:lab_bench/lab_bench.py:47-58` vs `fork:labbench/zero_shot.py:15-24`. inspect's version has a leading newline and "Think step by step." on its own paragraph; the harness's has "Options:" after a blank line.
  - **Answer instruction:** `'ANSWER: $LETTER'` (`inspect_evals:lab_bench/lab_bench.py:57`) vs `[ANSWER]…[/ANSWER]` tags (`fork:labbench/zero_shot.py:23-24`).
  - **Option labels:** `A) text` (`inspect_ai:solver/_multiple_choice.py:67`) vs `(A) text` (`fork:labbench/utils.py:139`).
  - **Opt-out text:** "Insufficient information to answer the question." with a period (`inspect_evals:lab_bench/record_to_sample_helpers.py:13`) vs without one (`fork:labbench/utils.py:24`).
  - **Protocol join:** `"Protocol: " + protocol + "\n\n" + question` (`inspect_evals:lab_bench/record_to_sample_helpers.py:81`) vs `self.protocol + input.question` with no separator (`fork:ProtocolQA/task.py:15`). On the first harness row that reads "…to reach the line labeled on the side.After completing the listed protocol…".

  A Candidate reads different bytes on all 108 Cases, so any Case's mark can move. How far the headline moves is unknown without the optional run above. This gap is what makes the verdict `comparable-to-inspect` rather than `comparable-to-paper`.
- **U2 — inspect_evals vs harness: answer extraction (inside U1's 108/108).** Each examiner reads its own format: inspect marks `[ANSWER]C[/ANSWER]` wrong, and the harness's extractor returns `None` for `ANSWER: C` (Checks 10, 12). Beyond the format, the rules differ in four ways:
  - **Two answers:** inspect takes the last `ANSWER:` line (`inspect_ai:solver/_multiple_choice.py:115`), while the harness sorts the set of tagged matches and takes the alphabetically first letter. Gold C then wrong A gives `'A'`, and so does wrong A then gold C (Checks 12).
  - **Hedged reply:** the harness credits `[ANSWER]C, A[/ANSWER]` when the gold letter is written first. inspect marks `ANSWER: C, A` wrong (`:148`).
  - **Case:** inspect accepts lower case (`:121`). The harness raises `TypeError` on `[ANSWER]c[/ANSWER]` and on an empty reply. That exception is not `UnanswerableError` (`fork:labbench/evaluator.py:84`), so it stops the harness run instead of marking the Case.
  - **Caveat:** these probes used chembench 0.3.0 with the HEAD call. The paper-era `chem-bench` (`fork:labbench/pyproject.toml:18` at `a767892`) was not installed, so whether its `prepare_mcq_answer` fell back to an LLM extractor is unchecked.
- **U3 — inspect_evals vs harness: metric and roll-up agree (bound 0).**
  - **Per-Case mark:** the harness counts `correct = agent_output == target_output` and `sure = agent_output != unsure` (`fork:labbench/evaluator.py:87-88`). So an unparsed reply is "sure" and wrong, the same as inspect's INCORRECT, and picking the opt-out is not sure, the same as inspect's NOANSWER.
  - **Roll-up:** `compute_metrics` (`:118-130`) equals inspect's accuracy / precision / coverage to four decimals on six vectors (Checks 11-12).
- **U4 — paper vs harness: the question set (harness wins; recorded, not counted).** The paper's numbers are over 135 ProtocolQA questions, public plus private, averaged over three runs (Table 1 p.5, Table 2 caption p.23). The public harness and the Hub hold the 108-question public subset (`fork:labbench/utils.py:165`, Checks 7). The paper reports that the private-vs-public mean accuracy gap across LAB-Bench is within five points (B.1, p.25), but gives no per-subtask figure for ProtocolQA.
- **U5 — option order is random on both upstream sides.** The harness reshuffles options on every run with an unseeded `random.shuffle` (`fork:labbench/utils.py:137`), and so does inspect_evals (`shuffle_choices=True`, no seed, `inspect_evals:lab_bench/lab_bench.py:76`). Ours fixes one draw of inspect's own shuffle (seed 7). Single runs on any of the three sides vary by option order; the paper's three-run mean averages over that.
