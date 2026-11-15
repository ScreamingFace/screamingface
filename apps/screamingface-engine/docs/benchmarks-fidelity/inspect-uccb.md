---
benchmark: inspect-uccb
origin: inspect_evals
verdict: not-comparable
verdict_reason: "The only published UCCB numbers (the inspect_evals README table: Claude Sonnet 4.5 82.0%, GPT-5 55.0%, ...) came from a different examiner by design. The dataset authors' own external script graded each reply 1 to 5 with GPT-4o and reported Avg Score / 5 x 100, with the Candidate at temperature 0.7 and 300 max tokens. That script is not published. Ours grades each reply C/I with the pinned house judge openrouter/openai/gpt-5.4 (a declared NAMED DEVIATION) and takes the plain mean. inspect_evals' own default judge is gpt-4o-mini, and its README says no inspect-native number exists. Against inspect_evals the record would read unverified. Dataset, Candidate text, judge prompt bytes, judge-reply parsing and marks all match (51,950 answer-sheet marks, 0 differing). The plain mean also matches on four vectors with no unparseable verdict. But four possibly-score-changing deviations are open: the judge model (D3), a verdict-less Case counting 0 where inspect drops it (D4), the system message folded into the user turn (D2), and the Candidate settings temperature 0 / max_tokens 512 not imposed (D5). No paid run can move this verdict off not-comparable."
audited: 2026-11-09
audited_at: 48fe0ec5b
fingerprint:
  benchmark: 2dbcedb55406dc6e
  harness_url: https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0/src/inspect_evals/uccb
references:
  paper: https://huggingface.co/datasets/CraneAILabs/UCCB/blob/c08d96b5574d3c772b0ae7e61b0f278066f18134/README.md
  original_harness: https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0/src/inspect_evals/uccb/uccb_evaluation_results
  inspect_evals: https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0
  inspect_ai: https://github.com/UKGovernmentBEIS/inspect_ai/tree/v0.3.263
parity_test: none
parity_test_reason: "No test puts the reference's marks beside ours for this Benchmark. The closest pins all passed in this audit: tests/unit/inspect/test_single_turn_judged_imports.py::test_uccb_shows_the_judge_the_reference_answer_from_the_cases_metadata (one stand-in Case through our judged route), tests/unit/inspect/test_judge_reads_the_sample_input.py (the judge quotes the Sample's question, not the folded system text), and tests/unit/inspect/test_benchmark_fingerprints.py (the fingerprint, pinned at :61). The parity evidence is the answer sheets below: 51,950 marks per examiner, run through our production judged aggregate route and through the Task's own solver chain and scorer."
---

# UCCB — Fidelity Record

## Verdict

**`not-comparable`.** Our headline is plain accuracy over the 1,039 questions of the [Ugandan Cultural Context Benchmark](https://huggingface.co/datasets/CraneAILabs/UCCB/blob/c08d96b5574d3c772b0ae7e61b0f278066f18134/README.md). Each Case is graded C/I by an LLM judge, using [inspect_evals v0.20.0 `uccb`](https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0/src/inspect_evals/uccb)'s own grading template.

**No published number was produced by this examiner.** UCCB has no paper, and the card's leaderboard is "planned" (card `README.md:46`). The only published numbers are the table in the inspect_evals README (`inspect_evals:uccb/README.md:109-115`). The eval's contributor, who is also a dataset author, produced them with an external script, `uccb_eval_threaded.py`, which is not published (`uccb_evaluation_results/evaluation.md:329`). That script:
- graded every reply on a 1 to 5 rubric;
- used `openai/gpt-4o` via OpenRouter as the judge, at temperature 0.3;
- ran the Candidate at temperature 0.7 with 300 max tokens;
- reported `Avg Score / 5 × 100` (`evaluation.md:6-7`, `:210-224`, `:317-323`; README `:107`, `:131`).

inspect_evals' own README says no inspect-native number exists (`README.md:107`). Our examiner differs from that script by design: a different judge model, a binary verdict instead of a 1 to 5 score, and a different roll-up. So by rule (spec §2.3) the verdict is `not-comparable`.

**Below the judge's model, ours matches inspect_evals.** These all matched:
- all 1,039 Cases' ids, questions, gold and metadata;
- the Candidate's text, byte for byte (the role differs, D2);
- the judge prompt bytes on 51,950 / 51,950 sheets;
- the judge-reply parsing and the marks on 51,950 / 51,950 sheets;
- the mean, to four decimals, on the four vectors with no verdict-less Case.

**The arithmetic:**
- **Against the authors' published numbers:** D3 is a different examiner by design (judge model, scale and roll-up all differ), `unbounded` → `not-comparable`.
- **Against inspect_evals:** `D1 0 + D2 unknown + D3 unknown + D4 unknown + D5 unknown`. Four `possibly-score-changing` deviations are open, so this would read `unverified`. D4 alone is worth up to `u/1039` for `u` verdict-less Cases, already 0.0048 at `u = 5`. Even with all four bounded, the verdict against the published numbers stays `not-comparable`.

## Dimensions

| dimension | status | severity | bound | evidence |
|---|---|---|---|---|
| dataset | deviation | cosmetic | 0 (D1) | **Replay (Checks run 3).** Our declaration's pins were enforced in process. It gave `task built: samples 1039`, `captured 1039 Cases`, `case_digest computed 5d3ec34b pinned 5d3ec34b equal True` and `case_set_digest computed fa61fff5 pinned fa61fff5 equal True`. Ours: `CraneAILabs/UCCB` at `c08d96b5…` (`apps/screamingface-engine/src/screamingface_engine_inspect/prepare.py:1591`, pin at `:1598-1600`). Theirs: `hf_dataset(path=DATASET_PATH, split="test", …, revision=UCCB_DATASET_REVISION)` with the same sha (`inspect_evals:uccb/uccb.py:33-34`, `:86-92`). **Per row against the raw parquet** at that revision (sha256 `17b8e821…`), Checks run 4: `raw rows 1039`, `unique raw ids 1039`, `sample ids == raw id set True only ours [] only raw []`. Zero rows differ in question, answer, metadata, Case target, Case metadata or kept `sample_input` (no counter printed). There are 24 categories, with no empty question or answer. The authors' results files hold the same 1,039 ids with identical question and answer text, for all six models (Checks run 5). **Order:** `Case order == raw file order: False`. Ours is the fixed `shuffle_seed=20260917` (`prepare.py:1601`). inspect's is `shuffle=True`, unseeded (`uccb.py:75`, `:90`). That difference is D1. |
| prompt | deviation | possibly-score-changing | unknown (D2) | **Prompt bytes, every Case (Checks run 3-4).** The Task's own solver chain, `[system_message(UCCB_SYSTEM_MESSAGE), generate(max_tokens=512)]` (`inspect_evals:uccb/uccb.py:37-39`, `:95`, `:105`), was run on all 1,039 Samples with a stub `generate`. It gave `inspect roles ('system', 'user'): 1039`, with 0 Cases where `our input != inspect system + blank line + user` and 0 where `our input != independent rebuild`. sha256 of all Case inputs: `f435820a3dce9985`. The text is equal, but the role differs. Our fold joins the messages with `_MESSAGE_SEPARATOR` (`apps/screamingface-engine/src/screamingface_engine_inspect/capture.py:79`, `:538`). inspect inserts a `ChatMessageSystem` (`inspect_ai:solver/_prompt.py:46`, `:70`). No `cot` arg is set on either side: our `task_args=None` (Checks run 2), and the default is `cot=False` (`uccb.py:72`). |
| answer extraction | match | — | — | The same function runs on both sides. Ours is `scorer="inspect_ai.scorer:model_graded_qa"` (`apps/screamingface-engine/src/screamingface_engine_inspect/benchmarks.py:5785`), with only `model` and `template` set. Checks run 6 printed `scorer_kwargs keys ['model', 'template']`, and `instructions`, `grade_pattern`, `partial_credit` and `include_history` are all unset. So both sides use the default instructions and the permissive `GRADE:` pattern (`inspect_ai:scorer/_model.py:261-281`, `:315-335`). **Answer sheets (Checks run 7):** 1,039 Cases × 5 Candidate replies × 10 judge replies = `marks per examiner 51950`. `differing Cases 0` held on all 50 sheet types. The judge replies cover `GRADE: C`, `GRADE: I`, reasoning then `GRADE: C`, `GRADE: C` … `GRADE: I` (last wins), `GRADE: Correct`, `GRADE: P` (not offered), lower-case `grade: c`, `CORRECT` with no `GRADE:`, `GRADE: CI`, and an empty reply. Every no-verdict reply is a failed Case for us (`invalid_score_value`, or `scorer_error` for the empty judge reply, `apps/screamingface-engine/src/screamingface_engine_inspect/judge_provider.py:308-311`) and `unscored` for inspect. The mark is the same; the failure code is only a name. |
| metric | match | — | — | The per-Case rule is C → 1.0, I → 0.0, and no verdict → no grade, on both sides (the same `model_graded_qa`, `inspect_ai:scorer/_model.py:336-360`). Our grader quotes the Sample's own question to the judge, not the folded system text. It takes the kept `sample_input` (`apps/screamingface-engine/src/screamingface_engine_inspect/scorer_adapter.py:622-630`), just as inspect's judge reads `state.input_text` (`inspect_ai:scorer/_model.py:299`). The template is byte-equal: `ours template == inspect UCCB_GRADING_TEMPLATE: True len 1030` (Checks run 6). The judge prompt bytes are equal on all 51,950 sheets (`judge prompt bytes: total theirs 51950 differing (multiset, both ways) 0`), as one user message on both sides (`message roles {('user',): 51950}`; `inspect_ai:scorer/_model.py:312`). An empty Candidate reply is sent to the judge on both sides, 1,039 judge calls per sheet type (inspect_evals v0.20.0 has no no-response guard, U5). The fixture test `test_uccb_shows_the_judge_the_reference_answer_from_the_cases_metadata` passed (Checks run 9). |
| roll-up | deviation | possibly-score-changing | unknown (D4) | Ours is `_accuracy`, `round(sum(values) / len(cases), 4)` (`apps/screamingface-engine/src/screamingface_engine_inspect/single_shot.py:1275`, `:1303`). It runs over every selected Case under `failure_policy="withhold"` (`benchmarks.py:5780`; `apps/screamingface-engine/src/screamingface_engine/benchmarks/aggregation.py:106`). inspect's is `accuracy()` = `total / float(len(scores))` (`inspect_ai:scorer/_metrics/accuracy.py:34-37`), over the Samples left after NaN-unscored ones are filtered out (`inspect_ai:_eval/task/results.py:405-414`). **Vectors (Checks run 8)** went through inspect's real `eval()` of the Task (mockllm Candidate, stub grader) and our production aggregate route. Four vectors were equal to four decimals: all C 1.0000, all I 0.0000, alternating 0.5005, every 3rd C 0.3340. Two vectors with verdict-less Cases differ. Every 10th unparseable gave inspect `1.0000 (unscored=103)` and ours `0.9009`. The thirds vector, with every 7th unparseable, gave inspect `0.3333 (unscored=148)` and ours `0.2859`. Those two are D4. |
| judge | deviation | possibly-score-changing (vs inspect_evals); different examiner by design (vs the published numbers) | unknown | **D3, declared** (`# NAMED DEVIATION`, `benchmarks.py:5819-5821`). Ours: `openrouter/openai/gpt-5.4` (`:5822`), params `web_search=false`, `max_tokens=4096` (`:5823`), temperature not set. The route seen on every sheet was `judge paths {'/openrouter/openai/gpt-5.4'} params {"max_tokens": "4096", "web_search": "false"}` (Checks run 7). The scorer's model is `screamingface/openrouter/openai/gpt-5.4` (`:5787`). inspect_evals: `scorer_model="openai/gpt-4o-mini"` (`inspect_evals:uccb/uccb.py:74`, `:110-113`). Its grader is not the active model, so it does not inherit the Task's `temperature=0.0`; it gets operational settings only (`inspect_ai:model/_model.py:1907-1929`). The authors' published numbers used `openai/gpt-4o` via OpenRouter, a 1 to 5 rubric and temperature 0.3 (`evaluation.md:6-7`, `:210-224`, `:321`). |
| sampling | deviation | possibly-score-changing | unknown (D5) | inspect_evals fixes the Candidate at `temperature=0.0` (`inspect_evals:uccb/uccb.py:115`), printed as `task config … temperature=0.0` (Checks run 3), and `max_tokens=512` (`:73`, `:105`), printed as `gen kw {"max_tokens": "512", …}: 1039`. It uses one epoch (no `epochs=`). Ours: no `params` on the row (`params None`, Checks run 6) and `attempts=1` (Checks run 2). The row's description states the gap in prose (`benchmarks.py:5772`), but no `NAMED DEVIATION` line declares it. The authors' script used temperature 0.7 and 300 max tokens (`evaluation.md:320-321`). |

## Deviations

### D1 — Case order is a seeded shuffle; inspect's is unseeded

- **Declared?** Undeclared by the rule. The row's description says it in prose (`apps/screamingface-engine/src/screamingface_engine_inspect/benchmarks.py:5769-5770`). There is no `NAMED DEVIATION` line.
- **Where.** Ours: `shuffle_seed=20260917` (`prepare.py:1601`). Theirs: `shuffle=True` with no seed (`inspect_evals:uccb/uccb.py:75`, `:90`).
- **What differs.** Only the order the Cases are served in. The set, the text and the gold are identical (dataset row).
- **Severity / bound.** `cosmetic`, `0`. Accuracy is order-free, and every Case is graded independently.

### D2 — the eval's system message rides inside the user prompt

- **Declared?** Undeclared on the row. The description says "The model answers in free text under the eval's own system message" (`benchmarks.py:5766-5767`), but it does not say the message arrives as user text. The plugin-wide comment `capture.py:75-77` is not one of the declaration forms the rule accepts.
- **Where.** Ours: one user text, system text + `"\n\n"` + question (`capture.py:79`, `:538`). Theirs: a system turn, then the user turn (`inspect_evals:uccb/uccb.py:95`; `inspect_ai:solver/_prompt.py:70`).
- **What differs.** The role, not the bytes. The text is equal on 1,039 / 1,039 Cases. The judge is unaffected, because it quotes the Sample's question (metric row).
- **Severity / bound.** `possibly-score-changing`, `unknown`. A Candidate may follow a system instruction ("Be specific and detailed") differently from user text. This needs a paired run.

### D3 — the judge is the pinned house model, not gpt-4o-mini (and not the authors' GPT-4o 1–5 rubric)

- **Declared.** `# NAMED DEVIATION: the eval's default judge is openai/gpt-4o-mini. This Benchmark pins the house judge XSTest and CoCoNot also call (owner decision on OME-1602, 2026-10-14).` (`benchmarks.py:5819-5821`). The description repeats it (`:5771`).
- **Where.** Ours: `scorer_kwargs["model"]` (`benchmarks.py:5787`) and `JudgeSpec` (`:5818-5824`). Theirs: `scorer_model="openai/gpt-4o-mini"` (`inspect_evals:uccb/uccb.py:74`). The authors' run used GPT-4o with a 5-point rubric (`evaluation.md:6-7`, `:210-224`).
- **What differs.** Only the model that answers the judge prompt. The prompt bytes and the parsing are identical (51,950 sheets). Our judge call also carries `max_tokens=4096`, where inspect's grader sends no `max_tokens`.
- **Severity / bound.** Against inspect_evals: `possibly-score-changing`, `unknown`; only a judge-only paired run can size it. Against the published numbers: a different examiner by design (judge model, scale and roll-up), which alone makes the verdict `not-comparable`.

### D4 — a Case the judge gives no verdict on counts 0 in our mean; inspect drops it

- **Declared?** Undeclared by the rule. `failure_policy="withhold"` is on the row (`benchmarks.py:5780`) and is an Engine-wide policy (OME-1642; `aggregation.py:106`). No `NAMED DEVIATION` line or README names the difference from inspect's aggregation.
- **Where.** Ours: `aggregation.py:106` hands every selected Case to `_accuracy`, which divides by `len(cases)` (`single_shot.py:1303`). Theirs: `inspect_ai:_eval/task/results.py:405-414` filters the NaN-unscored Samples out before `accuracy()`.
- **What differs.** Take `s` Cases graded C and `u` Cases with no verdict. Ours is `s/1039`; inspect's is `s/(1039 − u)`. The gap is `s·u / (1039·(1039 − u)) ≤ u/1039`. On the vectors: 0.9009 vs 1.0000 with `u = 103`, and 0.2859 vs 0.3333 with `u = 148`. A reply counts as no verdict when it is `GRADE: P` (partial credit is off), `GRADE: CI`, has no `GRADE:`, or is empty.
- **Severity / bound.** `possibly-score-changing`, `unknown`. How often gpt-5.4 fails to emit a parseable `GRADE:` is judge behaviour that only a paid run can count. Each such Case can move the headline by up to 1/1039 = 0.00096 against inspect's.

### D5 — inspect_evals runs the Candidate at temperature 0 with 512 max tokens; we impose neither

- **Declared?** Undeclared by the rule. The description states it (`benchmarks.py:5772-5773`), but there is no `NAMED DEVIATION` line.
- **Where.** Theirs: `config=GenerateConfig(temperature=0.0)` (`inspect_evals:uccb/uccb.py:115`) and `generate(max_tokens=max_tokens)` with default 512 (`:73`, `:105`). Ours: no settings on the row.
- **What differs.** The Candidate's decoding: provider defaults and no length cap here, versus greedy decoding with a 512-token cap in inspect_evals. A reasoning Candidate capped at 512 can return an empty or cut-off answer, which the judge then grades (U2 shows how often this happened at 300 tokens).
- **Severity / bound.** `possibly-score-changing`, `unknown`. It changes what the Candidate writes, not how a written reply is marked.

## Checks run

- [x] **Read-only on the checkout.** The audited checkout is `/Users/khoaguin/Desktop/projects/OpenMined/screamingface-stack/screamingface/.claude/worktrees/fidelity-sweep-pr1`, HEAD `48fe0ec5b` before and after. `git status --porcelain` listed only `docs/work/2026-11-09-fidelity-sweep.md` before and after; that is the calling session's sweep ledger, not this audit's. Every file this audit wrote lived under `SCRATCH=/private/tmp/claude-501/-Users-khoaguin-Desktop-projects-OpenMined-screamingface-stack-screamingface/553f1d23-8817-40ee-9c41-b0f8b3470b2e/scratchpad/audit-inspect-uccb-elY2`. It was deleted at the end with `python3 -c "import shutil, sys; shutil.rmtree(sys.argv[1])" "$SCRATCH"`. The first four `uv run` calls ran without `PYTHONDONTWRITEBYTECODE`, so they may have written gitignored `__pycache__` files under the checkout's `src/`. Later calls set it.
- [x] **No keys, no model.** `env -i PATH="$PATH" HOME="$SCRATCH" UV_CACHE_DIR="$SCRATCH/uv-cache" env | grep -iE 'key|token|secret'` printed nothing (`grep exit=1`). Every script also printed `env names matching key/token/secret: []` from inside its process. Every third-party command ran under that `env -i` prefix: `uv run`, `git clone`, `curl` of the Hub and the GitHub API, and pytest. The Candidate was a stub `generate` or inspect's `mockllm/model`. The judge was a stub object returning fixed text (inspect side) or a scripted Engine node (our side). No model, gateway or provider was called. The Hub was read unauthenticated, since UCCB is not gated.
- [x] **Harness over paper.** UCCB has no paper. The dataset card stands in for it (`references.paper`), and the authors' published numbers come from their external pipeline, whose outputs are the reference (`references.original_harness`). The pipeline's code is not published: `uccb_eval_threaded.py` is named at `evaluation.md:329`, and `git ls-tree -r --name-only v0.20.0 | grep -ci uccb_eval_threaded` printed `0`.
- [x] **Declared is not a finding.** D3 is declared (`NAMED DEVIATION`). D1, D2, D4 and D5 are undeclared findings. D1, D3 and D5 are also stated in the row's description prose, which the rule does not count.
- [x] **Every cell has evidence.** Each `match` names its command and output lines below.
- [x] **Every `file:line` is copied from command output.** Ours come from `grep -n`, `awk 'NR>=5758 && NR<=5852 && /…/ {print NR": "$0}'` and `sed -n` on the checkout's files (Checks run 10). `inspect_evals:` citations come from `cat -n` on scratch copies of the installed v0.20.0 files. Those copies are byte-equal to the `v0.20.0` tag: `git show v0.20.0:src/inspect_evals/uccb/<f> | cmp -` printed `== v0.20.0` for `uccb.py`, `README.md` and `eval.yaml`. `inspect_ai:` citations come from `cat -n`, `grep -n` and `sed -n` on scratch copies of the installed 0.3.263 files. `evaluation.md:` citations come from `git show v0.20.0:src/inspect_evals/uccb/uccb_evaluation_results/evaluation.md | cat -n`. Card citations come from `cat -n` on the card fetched at `c08d96b5`.
- [x] **A verdict never claims more than its evidence.** No dimension is `unchecked`. The verdict rests on the published numbers' examiner (D3, declared), not on any open bound.
- No `ours` override was set.

1. `git status --porcelain` → only the sweep ledger. `git rev-parse --short HEAD` → `48fe0ec5b`. Scratch created with `mktemp -d …/audit-inspect-uccb-XXXX`. The key check printed nothing (`grep exit=1`).
2. Our side: `env -i … uv run --isolated --extra inspect python -I $SCRATCH/scripts/info.py $SCRATCH/ref` printed:
   - `fingerprint 2dbcedb55406dc6e`, `origin inspect_evals`, `harness_url https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0/src/inspect_evals/uccb`, `paper_url https://huggingface.co/datasets/CraneAILabs/UCCB`;
   - `declaration BenchmarkDeclaration(failure_policy='withhold', interaction='single_shot', difficulty='medium', attempts=1)`;
   - `judge JudgeSpec(model='openrouter/openai/gpt-5.4', params=(('web_search', 'false'), ('max_tokens', '4096')), model_role=None, …)`;
   - `whole_run_metric_factory None`, `epoch_reducer_factory None`, `inverted_grade False`, `verdict_grades None`;
   - `TaskReplayCasesSpec(task='inspect_evals.uccb.uccb:uccb', case_count=1039, case_digest='5d3ec34b…', task_args=None, keep_sample_metadata=True, …, excluded_sample_ids=None, license='cc-by-nc-sa-4.0', source_pins={'CraneAILabs/UCCB': 'c08d96b5…'}, shuffle_seed=20260917, …, keep_sample_input=True)`;
   - `versions inspect_evals 0.20.0 inspect_ai 0.3.263`.

   The script copied `inspect_evals/uccb/` and the inspect_ai helpers to scratch. inspect_evals history: `env -i … git clone --filter=blob:none --no-checkout https://github.com/UKGovernmentBEIS/inspect_evals`, then `git log -- src/inspect_evals/uccb`. That showed `42ea9595 2025-10-16 UCCB implementation (#527)`, `aa2afe05 2025-11-17 Move UCCB eval results folder`, `4cf59d96 2026-08-21 fix(uccb): align the judge template with the GRADE extraction` (an ancestor of v0.20.0) and `e726805f 2026-10-13 Llm grader skip no response (#2669)` (not an ancestor of v0.20.0). `git rev-parse v0.20.0` → `360484a0…`.
3. Replay: `env -i … HF_HUB_DISABLE_XET=1 HF_HOME=$SCRATCH/hf XDG_CACHE_HOME=… INSPECT_EVALS_CACHE_DIR=… INSPECT_EVAL_MODEL=none/none uv run --isolated --extra inspect python -I $SCRATCH/scripts/replay.py $SCRATCH`. It follows `_replay_in_this_process` (`task_replay.py:414-448`), minus the prefetch: `CaseSourceRecorder(cache).install(fetch_pins_of(spec))`, then the task function, then `captured_case_records(task, spec)`. Output:
   - `task built: samples 1039`, `captured 1039 Cases`;
   - `case_digest computed 5d3ec34b pinned 5d3ec34b equal True`, `case_set_digest computed fa61fff5 pinned fa61fff5 equal True`;
   - `task config … temperature=0.0 …`, scorer `_model_graded_qa_single`, metrics `accuracy, stderr`.

   It then ran the Task's own solver chain on each Sample with a stub `generate`. The first Case printed as the system text, a blank line, then `What fuel sources are typically used for smoking the banana leaves?`, with `sample_input` equal to the question alone. inspect's messages were `[('system', …), ('user', 'What fuel sources …')] {'tool_calls': 'loop', 'max_tokens': '512'}`.
4. Dataset and prompt: `curl -sL https://huggingface.co/datasets/CraneAILabs/UCCB/resolve/c08d96b5…/data/test-00000-of-00001.parquet` → sha256 `17b8e821d6b09777…`. Then `env -i … python -I $SCRATCH/scripts/dataset_prompt.py` printed:
   - `raw rows 1039 columns ['answer', 'category', 'id', 'question']`, `unique raw ids 1039`;
   - `sample ids == raw id set True only ours [] only raw []`;
   - no mismatch counter, so zero Cases differ in question, target, metadata, Case target, Case metadata or kept `sample_input`;
   - `inspect roles ('system', 'user'): 1039`, `gen kw {"max_tokens": "512", "tool_calls": "loop"}: 1039`;
   - `Case order == raw file order: False`, `Case ids 1..N: True`, `categories 24`, `empty answers in raw 0 empty questions 0`, `braces in questions 0 in answers 0`;
   - `sha256 of all Case inputs in Case order: f435820a3dce9985`.
5. The authors' pipeline outputs: `git show v0.20.0:src/inspect_evals/uccb/uccb_evaluation_results/<model>/detailed_results.json` for six models, then `env -i … python -I $SCRATCH/scripts/ext.py`. Every model printed `items 1039 same id set True order==raw True question diffs 0 answer diffs 0`. Per model:
   - `anthropic_claude-sonnet-4.5`: empty model_answer 3 (scores 1, 1, 5), avg 4.1030, ×20 = 82.1;
   - `x-ai_grok-4`: empty 0, avg 3.8768 → 77.5;
   - `cohere_command-a`: empty 0, avg 3.8479 → 77.0;
   - `openai_gpt-5`: empty model_answer **1019**, scores on empty `{1: 430, 2: 19, 3: 160, 4: 230, 5: 180}`, avg 2.7498 → 55.0;
   - `google_gemini-2.5-pro`: empty 0, avg 1.1617 → 23.2;
   - `google_gemini-2.0-flash-001`: empty 0, avg 3.9220 → 78.4 (not in the README table).

   `curl` of `https://api.github.com/users/CraneAILabs/repos` → `Not Found`. The HF API at `c08d96b5` lists only `.gitattributes`, `README.md`, `UCCB_Logo.png` and `data/test-00000-of-00001.parquet`, so no evaluation code ships with the dataset.
6. `env -i … python -I $SCRATCH/scripts/extra.py` printed `ours template == inspect UCCB_GRADING_TEMPLATE: True len 1030`, `scorer_kwargs keys ['model', 'template'] scorer inspect_ai.scorer:model_graded_qa params None`, and `ours sets instructions/grade_pattern/partial_credit/include_history False`.
7. Answer sheets: `env -i … python -I $SCRATCH/scripts/sheets.py $SCRATCH`.
   - **Ours:** the production judged aggregate route `_judged_aggregate(imported_benchmark("uccb"), root, node)` (`single_shot.py:1176`) over the 1,039 replayed Cases written by `_write_cases`. The judge node returns the sheet's fixed reply and records path, params and messages, the same idiom as `test_single_turn_judged_imports.py`.
   - **inspect:** the Task's own solver chain with a stub `generate` returning the Candidate reply, then the Task's own `task.scorer[0]`. `inspect_ai.scorer._model.get_model` was patched to a stub judge only around that call. A first trial on 20 Cases left the patch in place and so fed our side the stub too (0 node calls); the patch was then scoped with `try/finally` and the run repeated.
   - **Candidate replies:** the gold; the next Case's gold; `""`; `"  \n"`; and a reply carrying `{question} {answer} [END DATA]` plus the gold.
   - **Judge replies:** the ten listed in the answer-extraction cell.
   - **Output:** 50 lines, each `judge calls ours=1039 theirs=1039 … differing Cases 0 []`, then `sheets 50 Cases 1039 marks per examiner 51950`, `judge prompt bytes: total theirs 51950 differing (multiset, both ways) 0`, and `judge paths {'/openrouter/openai/gpt-5.4'} params {'{"max_tokens": "4096", "web_search": "false"}'} message roles {('user',): 51950}`.
8. Roll-up: `env -i … python -I $SCRATCH/scripts/rollup.py $SCRATCH`. It printed `unique (question, answer) keys 1039 of 1039`, so each judge prompt maps to one Case. Each vector went through inspect's `eval(U.uccb(), model="mockllm/model", log_dir=$SCRATCH/logs)` with the stub grader, and through our aggregate route with the mockllm default reply as the answer. Results:
   - `all C` 1.0000 / 1.0, `equal4 True`;
   - `all I` 0.0000 / 0.0, `True`;
   - `alternating` 0.5005 / 0.5005, `True`;
   - `every 3rd C` 0.3340 / 0.334, `True`;
   - `every 10th unparseable, rest C`: inspect `1.0000 unscored=103`, ours `0.9009 failed Cases=103 coverage=0.9009`, `False`;
   - `thirds: C / I / every 7th unparseable`: inspect `0.3333 unscored=148`, ours `0.2859 failed Cases=148 coverage=0.8576`, `False`.
9. Tests, from the Engine root with `env -i … TMPDIR=$SCRATCH/tmp PYTHONDONTWRITEBYTECODE=1 uv run --isolated --extra inspect pytest <file> -q -p no:cacheprovider`. The first attempt at the first two ran before `$SCRATCH/tmp` existed and printed `no tests ran`; they were rerun.
   - `tests/unit/inspect/test_benchmark_fingerprints.py -k uccb` → `1 passed, 94 deselected`.
   - `tests/unit/inspect/test_single_turn_judged_imports.py -k uccb` → `1 passed, 3 deselected`.
   - `tests/unit/inspect/test_judge_reads_the_sample_input.py` → `9 passed`.
   - `grep -n '"uccb"' tests/unit/inspect/test_benchmark_fingerprints.py` → `61: "uccb": "2dbcedb55406dc6e"`.
10. Our citations:
    - `grep -n 'uccb' benchmarks.py prepare.py` → `5759`, `5781`, `5840`; `prepare.py:1586-1592`.
    - `awk` over `benchmarks.py:5758-5852` → `5762` description, `5769-5770` shuffle prose, `5772` temperature prose, `5780` failure_policy, `5785` scorer, `5819` NAMED DEVIATION, `5822` model, `5823` params, `5827` paper_url, `5840` harness_url, `5847` frontier_score, `5852` case count. `sed -n '5784,5787p;5817,5825p'` → the `model` kwarg at `5787` and the JudgeSpec at `5818-5824`.
    - `grep -n` in `prepare.py` → `1591`, `1596` (`keep_sample_input=True`), `1601` (`shuffle_seed`). `capture.py` → `79`, `538`. `scorer_adapter.py` → `622`, `628-629`. `judge_provider.py` → `308`, `311`. `aggregation.py` → `106`. `single_shot.py` → `1275`, `1303`.
    - inspect_ai: `grep -n` on `_eval/task/results.py` → `406-414`; `sed -n '1900,1930p' model/_model.py` → `_resolve_config` at `1907-1929`; `grep -n` on `solver/_prompt.py` → `46`, `70`.
11. Paper / card: `curl -sL https://huggingface.co/datasets/CraneAILabs/UCCB/raw/c08d96b5…/README.md`. It has 216 lines; `:46` reads "A public leaderboard for the UCCB Suite is planned." It carries no results table.
12. Clean-up: `python3 -c "import shutil, sys; shutil.rmtree(sys.argv[1])" "$SCRATCH"`. `git status --porcelain` → only the sweep ledger. HEAD `48fe0ec5b`.

## Recommended paid runs

None of these can change the verdict: the published numbers' examiner differs by design. They would size the gap to inspect_evals.

- **D3 + D4, judge-only (cheapest).** Take one Candidate's 1,039 replies, collected once. Grade them with `openai/gpt-4o-mini` (inspect's default) and with `openrouter/openai/gpt-5.4` (ours), using the identical prompt bytes. Two readouts:
  - **Agreement:** the per-Case C/I agreement and the headline difference, which bounds D3.
  - **Parse failures:** the count `u` of gpt-5.4 replies with no parseable `GRADE:`, which bounds D4 at `u/1039`.
  - **Cost:** about 2 × 1,039 judge calls of roughly 600 input tokens each.
- **D2 + D5, Candidate pair.** Use one Candidate on all 1,039 Cases with the gpt-5.4 judge fixed.
  - **Arm A:** inspect's own `eval()` (system turn, `temperature=0`, `max_tokens=512`).
  - **Arm B:** our served Case as one user message with no settings.
  - Run each arm twice to get the noise floor. Compare the headlines.
  - **Cost:** about 4 × 1,039 Candidate calls plus their judge calls.

## Upstream notes

- **U1 — inspect_evals vs the authors' pipeline: a different examiner, `unbounded`.** The table in [inspect_evals' README](https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0/src/inspect_evals/uccb) (`README.md:109-115`) was produced by the authors' unpublished `uccb_eval_threaded.py` (`evaluation.md:329`). That script differs from the inspect task on four points:
  - **Judge:** GPT-4o via OpenRouter, where the inspect task uses gpt-4o-mini.
  - **Score:** a 1 to 5 weighted rubric (accuracy 50%, cultural nuance 30%, completeness 20%; `evaluation.md:210-224`), where the inspect task gives a binary C/I.
  - **Sampling:** Candidate temperature 0.7 and judge temperature 0.3 with 300 max tokens (`evaluation.md:317-323`), where the inspect task uses Candidate temperature 0 and 512 max tokens.
  - **Headline:** `Avg Score / 5 × 100` (`README.md:131`), where the inspect task takes the plain mean.

  The README itself says so: "No inspect-native reference numbers exist for this task" (`README.md:107`). The README's "Evaluation Details" also list "Temperature: 0.0" and "Max Tokens: 512" (`README.md:121-122`), which contradicts the pipeline's own report (`evaluation.md:320-321`). The pipeline's report wins, since it produced the numbers.
- **U2 — the published GPT-5 number mostly grades empty replies.** In `openai_gpt-5/detailed_results.json`, 1,019 of 1,039 `model_answer` fields are empty. The judge still scored them 1–5 (`{1: 430, 2: 19, 3: 160, 4: 230, 5: 180}`), so "GPT-5 55.0%" reflects the judge's reading of blank answers under a 300-token cap. Claude Sonnet 4.5 has 3 empty answers, one of them scored 5 (Checks run 5).
- **U3 — README rounding.** The results files give Claude 4.1030 → 82.06 and Grok 3.8768 → 77.54. The README prints 82.0% and 77.6%. This is cosmetic.
- **U4 — before inspect_evals 3-A (2026-08-20) the task never produced a valid accuracy.** The template asked for CORRECT/INCORRECT, while the extractor expects `GRADE: C/I`. So every Sample was INCORRECT on inspect_ai < 0.3.245, and unscored on later versions (`README.md:146-148`). Our pin (v0.20.0) includes the fix `4cf59d96`, and our template is the fixed one (byte-equal, Checks run 6).
- **U5 — inspect_evals changed empty-reply grading after our pin.** `e726805f` (2026-10-13, version 4-A, not in v0.20.0) wraps the scorer in `preset_score_on_no_response`. An empty or whitespace-only reply then scores INCORRECT without a judge call. Under v0.20.0, and on our side, the judge grades it (1,039 judge calls on the `empty` and `whitespace only` sheets). A future pin bump would change those Cases. Bound 0 for this record.
- **U6 — no paper; the card's leaderboard is planned.** `references.paper` points at the dataset card at the pinned revision (`README.md:46` of the card). The row correctly carries `frontier_score=NotPublished` (`benchmarks.py:5847`).
