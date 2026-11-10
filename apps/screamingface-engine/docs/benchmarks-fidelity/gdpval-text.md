---
benchmark: gdpval-text
origin: screamingface
verdict: not-comparable
verdict_reason: "GDPval's published number is a win rate from blinded human-expert pairwise comparison against a professional's deliverable (paper gdpval_paper.tex:220, :244, :351); the declared harness (inspect_evals gdpval v0.20.0) carries no marking code and sends deliverables to OpenAI's hosted GPT-5-based pairwise grader (inspect_evals:gdpval/README.md:7, :85). Ours is a rubric mean marked by openrouter/google/gemini-3.1-pro-preview, one criterion at a time, over 102 of the 220 tasks, answered as plain text with no tools. A different examiner and a different metric by design (spec §2.3), declared in the row description (benchmarks.py:4448-4453)."
audited: 2026-11-09
audited_at: 43d3942f6
fingerprint:
  benchmark: f6ea752427e71362
  harness_url: https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0/src/inspect_evals/gdpval
references:
  paper: https://arxiv.org/abs/2510.04374v1
  original_harness: https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0/src/inspect_evals/gdpval
  inspect_evals: https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0
  inspect_ai: https://github.com/UKGovernmentBEIS/inspect_ai/tree/v0.3.263
parity_test: none
parity_test_reason: "The declared harness has nothing to run beside our scorer: its in-harness scorer is exact() against the placeholder target 'NONE' (inspect_evals:gdpval/gdpval.py:22, util.py:156), and the real marks come from OpenAI's hosted grader, which is a service and not code. tests/unit/inspect/test_local_task_gdpval.py (7 passed) pins our scorer against the deleted hand-built grader, not against a reference examiner."
---

# GDPval Text Subset — Fidelity Record

## Verdict

**`not-comparable`.** Our headline would sit beside GDPval's published win rate. The paper reports it from blinded expert pairwise comparisons, for example 47.6% wins-or-ties for Claude Opus 4.1 on the 220-task gold subset ([arXiv 2510.04374v1](https://arxiv.org/abs/2510.04374v1), `arxiv-src:v1/gdpval_paper.tex:244`). The [OpenAI leaderboard](https://evals.openai.com/gdpval/leaderboard) reports the same metric from its automated grader. **That number came from a different examiner and a different metric by design.** Its examiners are human occupational experts, or a hosted grader based on GPT-5-high (`gdpval_paper.tex:220`, `:224`, `:753`). They choose model or human deliverable per task (score in {0, 0.5, 1}, `:738`), and the scores are rolled into a win rate (`:351`). Ours is `openrouter/google/gemini-3.1-pro-preview` ticking expert rubric lines one at a time. Each Case scores earned over winnable points, and the headline is the mean over 102 Cases. The 102 are the prose-only subset of the 220, answered as plain text with no tools. Spec §2.3 puts "a published number produced by a different process by design (vendor- or human-run grading, a judge model other than the one the paper's number used)" under `not-comparable`, so the verdict does not depend on the bound arithmetic. The row says the same in plain words: "Scores are therefore not comparable to the published GDPval leaderboard" (`apps/screamingface-engine/src/screamingface_engine_inspect/benchmarks.py:4448-4453`). For the record, the arithmetic is still shown. The one enumerable bound is the dataset subset: 118 of the 220 reference rows are not served, `118/220 = 0.5364`, already above `COMPARABLE_TOLERANCE (0.005)`. The other six dimensions are `unbounded`, because the reference examiner has no code to rerun. Every difference is declared: none is a finding. What holds on our own side, with evidence:
- the Cases re-render to the sealed Case Digest `06dd52ec…` (all 102);
- our grader arithmetic equals earned/winnable on five fixed judge policies over all 4,447 real criteria;
- the verdict parser accepts only a JSON boolean `criteria_met`.

## Dimensions

| dimension | status | severity | bound | evidence |
|---|---|---|---|---|
| dataset | deviation | score-changing | `118/220 = 0.5364` (reference rows not served: every `task_id` at the pin outside `subset.py` `TEXT_SUBSET_TASK_IDS`, i.e. the 111 non-prose tasks plus the 7 `EXCLUDED_TASK_IDS`) + 17 served Cases whose reference files differ at the harness's pin (D1) | Ours: `openai/gdpval@11e7900c` (`local_tasks/gdpval/gdpval.py:72`, `prepare.py:1363-1374` source pin), 220 rows, split `train`; the 102 frozen ids are all present and unique, in frozen order; the prose-only rule (reference and deliverable extensions ⊆ {.docx,.doc,.txt,.md,.pdf}) reproduces 109 = 102 + the 7 exclusions exactly; rubric criteria 4,553, the filter removes 106 (224 of 7,183 positive points) → 4,447 served; 36 Cases carry 58 reference files (Checks 4). Theirs: `openai/gdpval@a3848a2a` (`inspect_evals:gdpval/util.py:13`), 220 rows, same ids, `rubric_json` absent on all 220; prompts of our 102 are identical across the two pins (`[]` differ), reference-file lists differ for 17 of them (Checks 4, 5). Declared: `gdpval.py:69-71` ("Do NOT copy inspect_evals' pin … predates the rubrics"), README `:16-19`, row description `benchmarks.py:4443-4444`. |
| prompt | deviation | score-changing | `unbounded` (D2) | All 102 Cases rendered both ways (Checks 4). Ours, `load_text_subset()` → `prepared_case(…, TASK_REPLAY_CASES["gdpval-text"])`: `case_digest recomputed 06dd52ec… == sealed True`. Each Case is the stripped request (`gdpval.py:123`), then for each reference file a `--- Reference file: <name> ---` header and its flattened text, joined by blank lines (`:124-129`). One user message, no system message, `solver=generate()` (`:271`). The served form is the candidate-input envelope (`benchmarks.py:4490`), which the connector unwraps for a single model. Theirs: `input=f"{record['prompt']}{DEFAULT_PROMPT_SUFFIX}"` (`inspect_evals:gdpval/util.py:155`), suffix `:315-326` (tools, package list, "Write your files in a new folder named `deliverable_files`"), reference files mounted in a Docker sandbox, not inlined (`util.py:165-171`). Result: `Cases whose Candidate input bytes equal theirs 0` of 102. 66 of 66 no-reference Cases equal `prompt.strip()` on our side; 30 prompts lose leading or trailing whitespace to the strip. Case 1 diff: ours ends `Please create a SOAP note for the visit.`; theirs adds a trailing space and the 12-line suffix. Declared: README `:8-12` ("a different exam (agentic, in a sandbox, all 220 tasks)"), `:28-32`; row description `benchmarks.py:4448-4450`. |
| answer extraction | deviation | score-changing | `unbounded` (D3) | Ours: the whole Candidate reply, `state.output.completion`, goes to the judge as `<submission>` (`gdpval.py:234-238`, `prompts.py:30-32`); there is no file. Theirs: the deliverable is the files in `deliverable_files/` (`inspect_evals:gdpval/extract_output.py:16-75`), plus the final message as `deliverable_text`, which is the first scorer's `Score.answer` (`util.py:246-248`), i.e. `exact()`'s `answer = state.output.completion` (`inspect_ai:scorer/_classification.py:52`, `:56`). Both are uploaded to the hosted grader. The text half matches; the file half has no counterpart in ours. Declared: row description `benchmarks.py:4448-4450` ("submissions are plain text where 83 of these tasks expected a formatted document"), `rubric_filter.py:1-11`. |
| metric | deviation | score-changing (by design) | `unbounded` (D4) | Ours: per Case, earned (met lines' points, penalties subtract) / winnable (positive points), unclamped (`gdpval.py:253-260`). 106 container criteria are dropped at build time (`rubric_filter.py:87-93`). Five scripted-judge policies over the 102 real Cases (4,447 judge calls each) give per-Case marks equal to that formula computed straight from the served rubrics (Checks 7). Conservation vs the hand-built grader: `7 passed` (Checks 6). Theirs: in-harness `scorer: Scorer = exact()` (`inspect_evals:gdpval/gdpval.py:22`) against `target="NONE"` (`util.py:156`), a placeholder. Answer sheets through it: a full memo → `I`, empty → `I`, `NONE` → `C`, `none.` → `C` (Checks 8). The real mark is the hosted grader's pairwise preference vs the human deliverable (`inspect_evals:gdpval/README.md:7`, `:85`, `:135`), in {0, 0.5, 1} (`arxiv-src:v1/gdpval_paper.tex:738`). The paper never mentions rubrics (`grep -n -i rubric gdpval_paper.tex` → no match). Declared: row description `benchmarks.py:4450-4452`, frontier score `NotPublished` (`:4526-4529`). |
| roll-up | deviation | score-changing (by design) | `unbounded` (D5) | Ours, through the real aggregator `benchmark_aggregate_async(imported_benchmark("gdpval-text"), …)` with a scripted judge (Checks 7). All lines met iff points > 0 → 1.0; never met → 0.0; odd Cases all-positive, even none → 0.5; every line met (10 Cases carry 66 penalty lines) → 0.9016; all-positive with Case 3's judge never parsing → 0.9902 (Case 3 fails as `judge_reply_invalid` and counts 0 over 102 under `failure_policy="withhold"`, `benchmarks.py:4460`). Each equals the formula's plain mean and inspect_ai `mean()` to four decimals. Theirs: the win rate, the share of deliverables graded better than the human one (`gdpval_paper.tex:351`), reported as wins or wins-and-ties (`:244`; `inspect_evals:gdpval/README.md:89`). The paper used 3 samples × 3 human graders per task (`:244` footnote); the automated grader grades 3 times with a bootstrap CI (`README.md:85`). No aggregator code exists to feed the vectors to. Declared: row description `benchmarks.py:4447` ("Benchmark score = the plain average of the case scores"). Doc note (ours, not a mark difference): README `:46` and `gdpval.py:25-26` say "plain mean over graded Cases", but a failed Case counts 0 over all selected Cases (0.9902 above, not 1.0; `test_local_task_gdpval.py:159-162`). |
| judge | deviation | score-changing (by design) | `unbounded` (D6) | Ours: `openrouter/google/gemini-3.1-pro-preview`, params `web_search=false, temperature=0.2, reasoning_effort=low, max_tokens=8192` (`benchmarks.py:4472-4482`; computed `JudgeSpec(…)` in Checks 2). One user message per criterion with our grader prompt (`prompts.py:19-54`, filled at `:86`; bytes pinned by `test_each_judge_call_is_the_hand_built_one`, Checks 6). Reply parsing is `parse_verdict` (`gdpval.py:165-180`): 14 sheets (Checks 9); only a real JSON boolean `criteria_met` counts. `"true"`, `1`, `null`, `{}`, an empty reply, prose and a JSON array → `None` (redrawn twice, then `judge_reply_invalid`); the first object wins when two are present. Theirs: human occupational experts, blinded and pairwise (`gdpval_paper.tex:220`, `:244`), or OpenAI's automated grader "based on GPT-5-high" (`:753`) with 66% agreement with humans (`:224`). It is hosted, its prompt is unpublished, and it marks 12 of 220 tasks ungradable (`:762`). No prompt bytes exist to compare. Declared: `# WHY this judge` on the JudgeSpec (`benchmarks.py:4468-4471`), README `:48-49`. |
| sampling | deviation | score-changing | `unbounded` (D7) | Ours: `BenchmarkDeclaration(interaction='single_shot', attempts=1)` (Checks 2). There are no tools, and no Candidate `max_tokens`/`temperature`/`retrieval_policy`, either on the row (`sed -n '4438,4533p' benchmarks.py \| grep -c "retrieval_policy\|attempts=\|max_tokens=\|temperature="` → `0`) or in the Task (`grep -n "attempts\|max_tokens\|temperature\|retrieval\|tools" gdpval.py` → none). Theirs: `use_tools([bash(CMD_TIMEOUT), python(CMD_TIMEOUT)])`, `CMD_TIMEOUT = 180`, a Docker sandbox (`inspect_evals:gdpval/gdpval.py:13`, `:46`, `:52`), and an agent loop via `generate()`. Paper: "we enabled the web search tool and the code interpreter tool, with background sampling", Claude sampled via its UI, and each model sampled 3 times per prompt (`gdpval_paper.tex:244`). Declared: README `:11` ("agentic, in a sandbox"), row description `benchmarks.py:4448-4450`. |

## Deviations

### D1 — 102 of the 220 tasks, at a later dataset revision

- **Declared.** Row description `apps/screamingface-engine/src/screamingface_engine_inspect/benchmarks.py:4443-4444` ("The prose-only slice of GDPval's 220-task open gold set: 102 …"), README `local_tasks/gdpval/README.md:16-19`, the frozen selection and its exclusions with reasons (`local_tasks/gdpval/subset.py:1-16`, `:133-141`), the pin choice (`local_tasks/gdpval/gdpval.py:69-72`).
- **Where.** Ours: `openai/gdpval@11e7900c`, `TEXT_SUBSET_TASK_IDS` (`subset.py:23-126`) selected by `select_rows` (`gdpval.py:98-112`). Theirs: all 220 rows of `openai/gdpval@a3848a2a` (`inspect_evals:gdpval/util.py:13`, `:19-29`; `eval.yaml:11` `dataset_samples: 220`).
- **What differs.** There are two differences. (a) 118 reference rows are not served: the 111 tasks with a non-prose reference or deliverable, plus 7 whose references flatten to under 200 characters or raise `XMLSyntaxError` (`subset.py:128-141`). (b) At the harness's pin, 17 of our 102 Cases carry a different reference-file list (Checks 5), in three kinds:
  - **Same files, reordered** (6 Cases): 32, 38, 41, 45, 52, 85.
  - **A file renamed** (8 Cases): 24 (`BOILERPLATE (1).pages` there, `Boilerplate.docx` here), 29, 51, 55, 77, 78, 90, 102.
  - **A different file count** (3 Cases): 36 and 57 have 3 files there and 1 here; 37 has 0 there and 1 here.

  Prompts are identical across the pins for all 102.
- **Severity / bound.** `score-changing`. For (a), `118/220 = 0.5364` against the reference row set; the ids are enumerable as the pin's 220 `task_id`s minus `TEXT_SUBSET_TASK_IDS`. For (b), `17/102`, Case ids as listed. The bound is already far above tolerance; the verdict rests on D4–D6 regardless.

### D2 — the Candidate prompt: references inlined as text, no tools suffix

- **Declared.** README `:8-12`, `:28-32`; row description `benchmarks.py:4448-4450`; reference flattening `local_tasks/gdpval/references.py:1-12`.
- **Where.** Ours `gdpval.py:115-134` (`REFERENCE_HEADER` at `:80`). Theirs `inspect_evals:gdpval/util.py:153-173`, suffix `:315-326`, sandbox files `:165-171`.
- **What differs.** Ours has no tool or package instructions and no `deliverable_files` instruction. The request is stripped (30 of 102 prompts carry edge whitespace). Each PDF/DOCX reference is flattened to text with pdfplumber or python-docx and pasted into the prompt, so layout, images and native formats are lost. Theirs keeps the files as files and appends its suffix. Their pin also lists different files for 17 Cases (D1).
- **Severity / bound.** `score-changing`, `unbounded`. 0 of 102 inputs are byte-equal, and the effect of a different instruction and a flattened reference on a deliverable's quality cannot be enumerated per Case.

### D3 — the deliverable is the reply text only

- **Declared.** Row description `benchmarks.py:4448-4450`; `rubric_filter.py:1-11` ("This benchmark never produces a file").
- **Where.** Ours `gdpval.py:234-238`. Theirs `inspect_evals:gdpval/extract_output.py:16-75`, `util.py:246-248`.
- **What differs.** The reference grades files plus the final message. The final message is pulled the same way on both sides (the whole completion). Ours has no files. The row states 83 of the 102 tasks expected a formatted document.
- **Severity / bound.** `score-changing`, `unbounded`.

### D4 — the mark is a rubric fraction, not a pairwise preference

- **Declared.** Row description `benchmarks.py:4450-4452`; `frontier_score=NotPublished(…)` `:4526-4529`; Task docstring `gdpval.py:32-33` ("this score is NOT GDPval's published metric").
- **Where.** Ours `gdpval.py:253-260`, `rubric_filter.py:74-93`. Theirs: in-harness `exact()` vs `"NONE"` (`inspect_evals:gdpval/gdpval.py:22`, `util.py:156`), a placeholder; the real mark comes from the hosted grader (`README.md:7`, `:135`), `{0, 0.5, 1}` per comparison (`arxiv-src:v1/gdpval_paper.tex:738`).
- **What differs.** Everything. Ours ticks 4,447 expert rubric lines; the rubrics were added in dataset v2 (`gdpval.py:69-71`) and appear nowhere in the paper. Theirs asks "is this deliverable better than the human expert's?" Ours also drops 106 container criteria, worth 224 of 7,183 positive points (3.1%), and keeps penalties unclamped.
- **Severity / bound.** `score-changing` by design, `unbounded`.

### D5 — the roll-up is a plain mean over 102, not a win rate

- **Declared.** Row description `benchmarks.py:4447`; README `:44-46`.
- **Where.** Ours: the mean scorer, `@scorer(metrics=[mean(), stderr()])` (`gdpval.py:184`), via the aggregate, with failed Cases counting 0 (`benchmarks.py:4460`). Theirs: the win rate (`gdpval_paper.tex:351`), with wins and wins-and-ties both reported (`:244`, `inspect_evals:gdpval/README.md:89`), over 3 samples × 3 graders (`:244`) or 3 grader sweeps (`README.md:85`).
- **Severity / bound.** `score-changing` by design, `unbounded`.

### D6 — the judge is ours

- **Declared.** `# WHY this judge` comment on the JudgeSpec (`benchmarks.py:4468-4471`: "GDPval's official grading is blinded expert PAIRWISE comparison … OpenAI's automated stand-in is a hosted service, not a model we can call — so the judge is OUR choice"), README `:48-49`.
- **Where.** Ours `benchmarks.py:4472-4482`, `prompts.py:19-54`, `gdpval.py:165-180`. Theirs `gdpval_paper.tex:220`, `:224`, `:753`.
- **What differs.** There are three differences:
  - **Examiner:** a human expert, or a GPT-5-high-based hosted grader, against `gemini-3.1-pro-preview`.
  - **Comparison:** one rubric line at a time, against a pairwise ranking with access to the deliverable files.
  - **Prompt and parsing:** ours are our own; theirs are unpublished.
- **Severity / bound.** `score-changing` by design, `unbounded`. This is the §2.3 clause "a judge model other than the one the paper's number used".

### D7 — single shot, no tools, no retrieval

- **Declared.** README `:11`; row description `benchmarks.py:4448-4450`.
- **Where.** Ours: `interaction='single_shot', attempts=1`, `solver=generate()` with no tools (`gdpval.py:271`). Theirs: bash and python tools at 180 s in a Docker sandbox (`inspect_evals:gdpval/gdpval.py:13`, `:46`, `:52`). Paper: web search and code interpreter, background sampling, 3 samples per prompt (`gdpval_paper.tex:244`).
- **Severity / bound.** `score-changing`, `unbounded`.

## Checks run

- [x] **Read-only on the checkout.** Checks 1 and 11 filter `git status --porcelain` to drop the calling session's records and sweep ledger, which it writes into this worktree concurrently. The filtered output was empty before and after. Every file this audit wrote is under `$SCRATCH` (`HF_HOME`, `TMPDIR` and `UV_CACHE_DIR` all pointed there, so the reference-file cache `default_reference_cache` landed in `$SCRATCH/tmp`). `$SCRATCH=/private/tmp/claude-501/…/scratchpad/audit-gdpval-text-GjJL`, deleted at the end with `shutil.rmtree`.
- [x] **No keys, no model.** `env -i PATH="$PATH" HOME="$SCRATCH" UV_CACHE_DIR="$SCRATCH/uv-cache" env | grep -iE 'key|token|secret'` → empty, `grep-exit=1`. Every command ran under that prefix, plus `HF_HOME`, `HF_HUB_DISABLE_XET=1` and `TMPDIR` set to scratch paths. Hub loads were unauthenticated: "You are sending unauthenticated requests to the HF Hub". No model, gateway or provider was called. Roll-up and metric checks used a scripted judge bound through `JudgeTransport`; no deliverable was uploaded to OpenAI's grader.
- [x] **Harness over paper.** The declared harness is inspect_evals `gdpval` at v0.20.0 (`benchmarks.py:4510-4511`), installed and read. It produces deliverables and has no marking code, so the examiner behind both the paper's number and the harness's number is outside any code: human experts in the paper, the hosted grader for the harness. The paper-vs-harness differences are in Upstream notes.
- [x] **Declared is not a finding.** D1–D7 are all declared: the row description, the JudgeSpec `# WHY this judge` comment, the local Task README, and the `gdpval.py` and `subset.py` docstrings. No undeclared mark-changing difference was found. One documentation inaccuracy on our side is recorded under roll-up (README `:46`, `gdpval.py:25-26`).
- [x] **Every cell has evidence.** No `match` is claimed. Each `deviation` names both source locations and the command output that shows it.
- [x] **Every `file:line` is copied from command output.** Ours comes from `cat -n` on `gdpval.py`, `prompts.py`, `rubric_filter.py`, `subset.py`, `references.py` and `test_local_task_gdpval.py`. It also comes from `grep -n ''`/`sed -n` on `benchmarks.py` (rows 4438-4533), `prepare.py:1355-1380`, and `grep -n ""` on the README. Theirs comes from `cat -n` on `inspect_evals:gdpval/{gdpval.py,eval.yaml,hooks.py,README.md,util.py,extract_output.py}` and `sed -n '40,75p'` on `inspect_ai:scorer/_classification.py`. The paper comes from `grep -n -i` and `sed -n` on `arxiv-src:v1/gdpval_paper.tex`. Paths: ours under `apps/screamingface-engine/src/screamingface_engine_inspect/` unless given in full.
- [x] **A verdict never claims more than its evidence.** None of prompt, answer extraction, metric or roll-up is `unchecked`. Each was compared on every Case, or on fixed sheets and vectors, as far as the reference has code. The verdict rests on the by-design clause, not on a paid-run question.
- No `ours` override was set.

1. `git rev-parse --short HEAD` → `43d3942f6` (checkout `.claude/worktrees/fidelity-sweep-pr1`). `git status --porcelain`, minus the calling session's `docs/benchmarks-fidelity/*.md` and `docs/work/2026-11-09-fidelity-sweep.md`, → empty (`exit=1`).
2. From the Engine root, `uv run --isolated --extra inspect python $SCRATCH/scripts/ours.py` printed:
   - `type ImportedBenchmark`, `fingerprint f6ea752427e71362` (= `published_revision`, `benchmarks.py:4440`);
   - `origin screamingface`, `harness_url https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0/src/inspect_evals/gdpval`, `paper_url https://arxiv.org/abs/2510.04374`;
   - `judge JudgeSpec(model='openrouter/google/gemini-3.1-pro-preview', params=(('web_search','false'),('temperature','0.2'),('reasoning_effort','low'),('max_tokens','8192')), …)`;
   - `declaration BenchmarkDeclaration(failure_policy='withhold', interaction='single_shot', difficulty='hard', attempts=1)`, `case_count 102`;
   - `TASK_REPLAY_CASES["gdpval-text"]`: `case_digest='06dd52ec…'`, `keep_sample_metadata=True`, `has_answer_key=False`, `excluded_sample_ids=None`, `source_pins={'openai/gdpval': '11e7900c…'}`, `needs_hf_token=False`, `keep_sample_input=True`;
   - `inspect-evals 0.20.0 inspect-ai 0.3.263`.
3. `uv venv $SCRATCH/venv` + `uv pip install inspect-evals==0.20.0 inspect-ai==0.3.263` (scratch) → read `inspect_evals/gdpval/`, which holds `gdpval.py`, `util.py`, `extract_output.py`, `hooks.py`, `eval.yaml`, `README.md`, `Dockerfile` and `docker-requirements.txt`. Importing `inspect_ai.solver` in this venv failed (`ModuleNotFoundError: No module named 'acp.helpers'`, a dependency drift). Steps 4, 5 and 8 therefore ran inspect_evals' and inspect_ai's code from the Engine's isolated environment, which pins the same `inspect-evals 0.20.0` and `inspect-ai 0.3.263` (step 2).
4. `uv run --isolated --extra inspect --extra benchmarks python $SCRATCH/scripts/dataset_prompt.py` (3 min 33 s, 58 reference files downloaded into `$SCRATCH/tmp`):
   - Our pin: `ours revision 11e7900c… splits {'train': 220}`; columns include `rubric_json`, `deliverable_files`. `frozen ids 102 unique 102 all present True`, `excluded ids present 7 overlap with frozen 0`, `prose-only reproduce 109 == frozen+excluded True`.
   - Rubrics: `criteria total 4553 kept 4447 removed 106 positive points total 7183 removed positive 224`. `tasks with refs 36 ref files 58`.
   - Their pin: `their pin "a3848a2a…"`, `theirs rows 220 rubric_json non-null 0` (columns lack `rubric_json`), `ids equal across pins True`. `frozen ids whose prompt differs across pins []`. `frozen ids whose reference_files differ across pins` → 17 ids. `reference rows not served 118`.
   - Our rendering: `ours samples 102 ids in frozen order True`, `case_digest recomputed 06dd52eca719f1f4b5a6da90cab234d9af4af7245497ae06ec37e391ef75d7fb == sealed True`, `rubric items served 4447`.
   - Prompt bytes: `Cases whose Candidate input bytes equal theirs 0`, `theirs input == prompt + DEFAULT_PROMPT_SUFFIX 102 /102`, `their files per Case (refs) 61`. Ours: `ours input starts with prompt.strip() 102 /102`, `no-ref Cases whose input == prompt.strip() 66 of 66`, `prompt with trailing/leading whitespace stripped by ours 30`.
   - Sizes: `ours input chars min/median/max 953 2643 56611`, `sha256 all ours inputs 5f49f3bf…`. `diff ours_case1.txt theirs_case1.txt` → `11c11,23`: their line 11 carries a trailing space, then the 12-line suffix.
5. `…python $SCRATCH/scripts/refdiff.py` → `differing 17 of which only the hash dir differs 0`. Per Case: 24 `Boilerplate.docx` vs `BOILERPLATE (1).pages`; 29, 55, 77, 78, 90, 102 renamed; 51 renamed and reordered; 32, 38, 41, 45, 52, 85 reordered; 36 `1` vs `3`; 57 `1` vs `3`; 37 `1` vs `0`.
6. `uv run --isolated --extra inspect pytest tests/unit/inspect/test_local_task_gdpval.py -q -p no:cacheprovider` → `7 passed, 2 warnings in 149.93s`.
7. Roll-up and metric, `…python $SCRATCH/scripts/rollup.py` (all 102 real prepared Cases, `benchmark_aggregate_async(imported_benchmark("gdpval-text"), …)`, scripted judge bound via `JudgeTransport` with the row's params, the test file's machinery):

   | judge policy | judge calls | ours | formula mean | inspect `mean()` | equal | statuses |
   |---|---|---|---|---|---|---|
   | met iff points > 0 | 4447 | 1.0 | 1.0 | 1.0 | True | 102 scored |
   | never met | 4447 | 0.0 | 0.0 | 0.0 | True | 102 scored |
   | odd Cases all-positive, even none | 4447 | 0.5 | 0.5 | 0.5 | True | 102 scored |
   | every line met | 4447 | 0.9016 | 0.9016 | 0.9016 | True | 102 scored |
   | met iff points > 0, Case 3's judge never parsing | 4382 | 0.9902 | 0.9902 (Case 3 = 0) | 0.9902 | True | 101 scored, 1 failed, `scored_cases=101` |

   Also printed: `Cases with a penalty line 10 penalty lines 66`; `result metric keys ['correct', 'scored_cases']`.
8. Their in-harness scorer, `…python $SCRATCH/scripts/sheets.py theirs` (inspect_ai `exact()` vs `Target("NONE")`): `'a full professional memo' -> ('I', …)`, `'empty' -> ('I', '')`, `'the literal NONE' -> ('C', 'NONE')`, `'lower-case none.' -> ('C', 'none.')`.
9. Judge-reply sheets, `…python $SCRATCH/scripts/sheets.py ours` (`parse_verdict`):
   - Parsed: bare true → `(True,'ok')`; bare false → `(False,'no')`; fenced → `(True,'ok')`; prose then JSON → `(False,'no')`; no explanation → `(True,'')`; two objects, first false → `(False,'')`.
   - `None` (redrawn): `"true"`, `1`, `null`, missing key, `{}`, empty reply, prose only, `[true]`.
10. Paper, from `curl -sL https://arxiv.org/abs/2510.04374` (only `[v1] Sun, 5 Oct 2025`) and `curl -sL https://arxiv.org/e-print/2510.04374v1` (gzip tar; `gdpval_paper.tex`, 1,051 lines). `grep -n -i "pairwise\|win rate\|automated grader\|rubric\|…"` and `sed -n '228,246p'` gave:
    - `:81` the primary metric is the win rate;
    - `:220` blinded expert pairwise comparisons;
    - `:224` the automated grader, 66% agreement;
    - `:244` the headline 47.6% wins-or-ties for Claude Opus 4.1, plus the sampling footnote (web search, code interpreter, background sampling, 3 samples × 3 graders);
    - `:295` "human expert comparison is still our recommended method of grading";
    - `:351` the win rate definition;
    - `:738` scores in {0, 0.5, 1};
    - `:753` "based on GPT-5-high";
    - `:762` 12 of 220 tasks ungradable.

    `rubric` → no match.
11. After: `git rev-parse --short HEAD` → `48fe0ec5b`. One commit landed during the audit, the calling session's `docs(screamingface-engine): Fidelity Records for the 19 SOTA-board …`. `git diff --stat 43d3942f6 HEAD -- apps/screamingface-engine/src apps/screamingface-engine/tests` → empty, so nothing this audit read moved, and `audited_at` stays `43d3942f6`. The filtered `git status --porcelain` → empty. `python3 -c "import shutil, sys; shutil.rmtree(sys.argv[1])" "$SCRATCH"` → the folder is gone.

## Recommended paid runs

None. No paid run can make this number comparable: the reference examiner is human experts, or a hosted OpenAI service that grades by pairwise preference against the human deliverable. Agreement between our Gemini rubric judge and that grader would be a separate research question, not a fidelity check.

## Upstream notes

- **Paper vs harness, the examiner.** The paper's headline is blinded human-expert pairwise grading (`arxiv-src:v1/gdpval_paper.tex:220`, `:244`), and the paper calls the automated grader "experimental" and "not a full substitute" (`:295`, `:307`). The declared harness, inspect_evals `gdpval`, defers all grading to that automated grader (`inspect_evals:gdpval/README.md:7`, `:93`). Its own replication shows the gap between them: GPT-5 at low thinking scores 47.3% ± 6.2% on the automated grader, against the official leaderboard's 31.9% wins-only and 34.6% wins-and-ties (`README.md:79-89`). Bound: `unbounded`, since the human grades are unpublished.
- **Paper vs harness, the scaffold.** The paper used OpenAI's code interpreter and web search with background sampling, and sampled Claude through its UI (`gdpval_paper.tex:244`). inspect_evals substitutes bash and python tools in a Docker sandbox ("Inspect doesn't support the code interpreter API", `README.md:141-143`), and its default suffix is its own wording (`util.py:315-326`). The paper's A.3 prompt-tuning text is kept as `PROMPT_ELICIT_CAPABILITIES_SUFFIX` (`util.py:329`) but is unused by default. Bound: `unbounded`.
- **Harness dataset pin.** inspect_evals pins `openai/gdpval@a3848a2a` (`util.py:13`). That revision has no `rubric_json` on any of the 220 rows, and for 17 of our 102 tasks its reference-file list differs from the v2 release (Checks 5). Example: task `3a4c347c…` carried an Apple `.pages` file there and a `.docx` here. Bound: 17 of our Cases, plus whatever changed among the 118 we do not serve (not compared).
- **The automated grader's own coverage.** It marks 12 of 220 tasks as ungradable (`gdpval_paper.tex:762-765`), so even the harness path does not grade the full gold subset.
