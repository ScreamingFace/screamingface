---
benchmark: bbh
origin: screamingface
verdict: not-comparable
verdict_reason: "Our headline is pooled accuracy over 6,508 Cases; the paper's 73.9 is the unweighted mean over 23 tasks (declared Named Deviation 3), and the two can differ by up to 0.1435 on the same marks. The Candidate is also asked a different prompt from the authors' (inspect_evals' rewritten worked examples, an ANSWER: instruction, no trailing 'A: Let's think step by step.'), which no bound covers, and replies are read from the ANSWER: line, where the paper reads after 'the answer is'."
audited: 2026-11-09
audited_at: 48fe0ec5b
fingerprint:
  benchmark: 467f06b54836a6f8
  harness_url: https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0/src/inspect_evals/bbh
references:
  paper: https://arxiv.org/abs/2210.09261v1
  original_harness: https://github.com/suzgunmirac/BIG-Bench-Hard/tree/9ee07bd481feebf959a6b59d61ea57bdcf30964d
  inspect_evals: https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0
  inspect_ai: https://github.com/UKGovernmentBEIS/inspect_ai/tree/v0.3.263
parity_test: tests/unit/inspect/test_local_task_bbh.py
parity_test_reason: ""
---

# BIG-Bench Hard (BBH) — Fidelity Record

## Verdict

**`not-comparable`.** Our number cannot sit beside the [paper's](https://arxiv.org/abs/2210.09261v1) "BBH all (23 tasks)" headline (Codex CoT 73.9, `arxiv-src:main.tex:385,398`). Three deviations rule it out, and each is enough alone:

- **Roll-up (D5, declared).** We publish pooled accuracy over Cases. The paper takes the unweighted mean of the 23 task accuracies, after averaging the 3 sizes of logical deduction and of tracking shuffled objects. The same marks give 0.2305 under ours and 0.0870 under the paper's rule, and the worst case over all mark vectors is 0.1435.
- **Prompt (D3).** The Candidate's bytes equal the authors' prompt on 0 of 6,508 Cases. Part of this is declared and part is not, and a paid run is the only way to bound it, so it stays `unbounded`.
- **Reply reader (D4, declared by description).** Multiple-choice and yes/no Cases are read only from an `ANSWER:` line. The paper reads the text after "the answer is". So the authors' own Codex replies score 0 under our reader on all 23 of those subsets.

The free-form side does match. Our exact-match rule reproduces the authors' Codex accuracy on all 4 free-form subsets, on every Codex reply. On the 4 sheet types where both examiners can read the reply (both labels present, empty, inspect_evals' holes), the marks are identical on every Case except one undeclared broken Case (D2).

Bound arithmetic against the original harness: D1 3 Cases (≤ 3/5750 = 0.0005 on the paper's roll-up) + D2 1/6508 = 0.0002 + D3 `unbounded` + D4 6508/6508 = 1.0000 + D6 5008/6508 = 0.7695 + D5 0.1435 → far above `COMPARABLE_TOLERANCE (0.005)`, and D3 has no bound at all → `not-comparable`. The open `possibly-score-changing` sampling deviation (D7) cannot rescue the verdict, because the bounded deviations already exceed tolerance.

## Dimensions

| dimension | status | severity | bound | evidence |
|---|---|---|---|---|
| dataset | deviation | score-changing | 4 Cases: D1 3/6511 (≤ 0.0005 on the paper's roll-up), D2 1/6508 (Case 2982) | Our 6,508 Cases rendered by `captured_case_records(bbh(), TASK_REPLAY_CASES["bbh"])`: `case_digest 2454ce86… == sealed True`, `case_set_digest == sealed True` (Checks 4). Compared row by row, in order, with the authors' `fork:bbh/*.json` (6,511 rows): `rows on our side only: 0`, `target differs: 0`, `matched rows whose id position != authors' index+1: 0`. Questions are byte-equal on 5,571 rows, and the other 937 are equal after undoing the casing rewrite (`Options:`→`OPTIONS:` in causal_judgement, formal_fallacies and navigate, and web_of_lies' `Question: ` prefix dropped; counted under prompt). MC options were rebuilt as `(A) text` and are equal. `rows on the authors' side only: 3`: movie_recommendation 163 and ruin_names 99 and 144 (D1, declared). The authors' own `fork:bbh/snarks.json` example 88 is cut to `(A) The NB`; the Codex run's prompt carried the full two options. Our Case 2982 inherits the cut question with a single option (D2, undeclared). |
| prompt | deviation | score-changing | unbounded | All 6,508 Candidate inputs (Checks 4) vs the authors' prompt for the same question (`cot-prompts/<task>.txt` + `"\n\nQ: " + input + "\nA: Let's think step by step."`, rebuilt and equal to the Codex-recorded `input` on 6,507/6,508; the exception is D2) (Checks 6): `Candidate input bytes == authors' prompt: 0`. After undoing, in order, the instruction line, the `ANSWER:` lines in the worked examples, the `Q:`/`Options:` casing, the `(A)` option letters, and the `A:` cue plus the missing final `A: Let's think step by step.`: `equal after undoing the rewrites: 4832`. Another 1,428 are equal once `(A)`→`A)` inside the worked reasoning, double spaces, and web_of_lies' `Question: ` are also undone. The last 248 (ruin_names) differ by one worked-example line the authors' `fork:cot-prompts/ruin_names.txt:31` carries and inspect_evals' prompt drops. See D3. |
| answer extraction | deviation | score-changing | 6508/6508 (every Case) | Ours: MC uses `parse_answers` on the last `ANSWER:` line (`inspect_ai:solver/_multiple_choice.py:98-121`, replayed at `apps/screamingface-engine/src/screamingface_engine_inspect/scorer_adapter.py:651`). Yes/no uses `answer(pattern="word")`, the word after `ANSWER:` (`inspect_ai:_util/pattern.py:6-7`). Free-form uses `final_answer`: last `ANSWER:`, else "the answer is", ignoring case (`apps/screamingface-engine/src/screamingface_engine_inspect/local_tasks/bbh/bbh.py:131-134,156-178`). Paper: text after "the answer is" (`arxiv-src:main.tex:435`). The reference reader was rebuilt from that sentence and reproduces all 27 of the authors' published Codex accuracies, `subsets reproduced (first): 27 / 27` (Checks 5). Answer sheets, 13 per Case (Checks 8-10). `ours_format_gold`: ours 6508 right, paper 0. `paper_format_gold`: ours 1000 right (free-form only), paper 6508. `codex_reply`: ours 0.0 on all 23 MC and yes/no subsets, equal to the paper's numbers on the 4 free-form subsets (56.8, 47.6, 93.2, 40.4). `worked_example_shape_gold` (MC `So the answer is B).\nANSWER: B)`, the shape inspect_evals' examples teach): ours 4071, paper 0. See D4. |
| metric | deviation | score-changing | 5008/6508 (D6, every MC Case + 937 yes/no Cases) | With both labels present, so both readers find the answer: `both_labels_gold` differ 0 and `both_labels_wrong` differ 0 over 6,508 Cases each. `empty` differ 0. `inspect_evals_hole` (`ANSWER: 1<key>`, `ANSWER: <key> )`, …) differ 0 over 1,000 free-form Cases: both mark them wrong (Checks 10). `both_labels_gold_lowercase` differs on 5,008 Cases. Ours ignores case on letters (`matched.upper()`, `inspect_ai:solver/_multiple_choice.py:121`) and on yes/no words (`ignore_case: bool = True`, `inspect_ai:scorer/_pattern.py:56`). The paper says "exact match" (`arxiv-src:main.tex:436`); the Codex replies cannot settle case either way (a case-folding reader also reproduces 27/27, Checks 11) (D6, undeclared). `both_labels_gold_bold` differs on the 1,000 free-form Cases: ours trims `**`/backticks (`bbh.py:138`), declared in README `:24`. The paper's rule as written keeps them (also unsettled by the replies). Free-form exact match: `test_the_rule_reproduces_the_papers_accuracy_on_the_authors_codex_replies` ×4 passed (Checks 7). |
| roll-up | deviation | score-changing | 0.1435 (worst case over all mark vectors) | Ours: `round(sum(values) / len(cases), 4)` (`apps/screamingface-engine/src/screamingface_engine_inspect/single_shot.py:1275,1303`). `whole_run_metric_factory None` (Checks 12). Paper: one accuracy per task, the 3 sizes averaged into Logical Deduction (avg) and Tracking Shuffled Objects (avg), then the mean over 23 tasks (`arxiv-src:figures-and-tables/codex_and_palm_on_bigbench_hard.tex:17,29,36`). Seven vectors through both (Checks 12-13): all-1 1.0000/1.0000; all-0 0.0000/0.0000; alternating 0.5000/0.5000; every-3rd 0.3333/0.3333; Codex paper-marks 0.7400/0.7397; only-3-size-tasks-right 0.2305/0.0870; only-3-size-tasks-wrong 0.7695/0.9130. The paper's roll-up on the authors' full 6,511 Codex marks gives 0.7393, which is Table 3's 73.9; pooled gives 0.7397. Declared, Named Deviation 3. See D5. |
| judge | not applicable | — | — | `imported_benchmark("bbh").judge` → `None` (Checks 2). The paper grades by exact match (`arxiv-src:main.tex:436`), no model. |
| sampling | deviation | possibly-score-changing | unknown | Paper: greedy decoding, τ = 0 (`arxiv-src:main.tex:434`). inspect_evals: `config=GenerateConfig(temperature=0)` (`inspect_evals:bbh/bbh.py:150`), which our Task copies (`bbh.py:244`). But the importer never reads `task.config` (`apps/screamingface-engine/src/screamingface_engine_inspect/benchmarks.py:4190`), and the row sets no params (`params None`, Checks 2; `grep -n -i "temperature\|max_tokens\|params"` over `benchmarks.py:6462-6560` → exit 1). Attempts 1 on both sides. Undeclared on the row. See D7. |

## Deviations

### D1 — three unanswerable questions left out

- **Declared.** `excluded_sample_ids=("movie_recommendation_164",)` (`apps/screamingface-engine/src/screamingface_engine_inspect/prepare.py:1889`) covers one question. inspect_evals' `RUIN_NAMES_BROKEN_SAMPLES` (`inspect_evals:bbh/bbh.py:55`) covers the other two, which our README names (`apps/screamingface-engine/src/screamingface_engine_inspect/local_tasks/bbh/README.md:54-57`).
- **Where.** The authors' `fork:bbh/movie_recommendation.json` example 163 (key `Monsters, Inc`, options `(A) Monsters`, `(B) Inc`) and `fork:bbh/ruin_names.json` examples 99 and 144 (keys `dearth, wind, & fire` and `rita, sue and bob poo`, split across options).
- **What differs.** The paper counts all 3, and Codex's replies (`(B)`, `(B)`, `(D)`) mark 0 under the paper's rule (Checks 11). We serve 6,508 of 6,511.
- **Severity and bound.** `score-changing`, 3 Cases. On the paper's roll-up that is ≤ 2/(23·250) + 1/(23·250) = 3/5750 = 0.0005. On pooled accuracy it is ≤ 3/6511 = 0.0005.

### D2 — Case 2982 (`snarks_089`) is a truncated question with one option

- **Undeclared.**
- **Where.** The authors' `fork:bbh/snarks.json` example 88 is the text `Which statement is sarcastic?\nOptions:\n(A) The NB`. The Codex run's recorded `input` for the same row carries the full question with options (A) and (B) (`fork:code-davinci-002-outputs/code-davinci-002-cot/snarks_few_shot_template_0-255000.json` outputs[88]). The Hub copy inherits the cut text. Our Case 2982 reads `… where LETTER is one of A. …` and `OPTIONS:\n\nA) The NB` (Checks 11).
- **What differs.** Any reply that answers `A` is marked right by us. The `ours_format_wrong` sheet (`ANSWER: A`, the only letter) scores 1. The paper's number was produced with the full two-option question.
- **Severity and bound.** `score-changing`, 1/6508 (Case 2982). On the paper's roll-up that is ≤ 1/(23·178) = 0.0002.

### D3 — the Candidate is asked inspect_evals' rewritten prompt, not the authors'

- **Partly declared.** Declared: the multiple-choice instruction, Named Deviation 1 (`bbh.py:34-41,195-196`; row `benchmarks.py:6508-6511`). Also declared: "It reuses inspect_evals' loader, its 3-shot chain-of-thought examples" (README `:10-11`), and the row's "the model reasons step by step and ends on an 'ANSWER:' line" (`benchmarks.py:6472`). Undeclared: that these examples are not the authors' bytes. The row presents them as "the setting of the paper's headline numbers".
- **Where.** Ours: `multiple_choice(cot=True)` (`bbh.py:196`) over inspect_evals' `f"{prompt}\n\nQUESTION: {sample.input}\nOPTIONS:"` (`inspect_evals:bbh/bbh.py:100`) and `f"{prompt}\n\nQUESTION: {sample.input}"` behind the `prompt_patch_extra` instruction (`inspect_evals:bbh/bbh.py:106,400,417`). The few-shot text comes from `Joschka/big_bench_hard` `few_shot_prompts` @ `76eaa8c2`. Theirs: `fork:cot-prompts/<task>.txt` + `Q: <input>\nA: Let's think step by step.` (e.g. `fork:cot-prompts/date_understanding.txt:13-14`).
- **What differs, on all 6,508 Cases** (Checks 6):
  - an instruction line that asks for `ANSWER: $LETTER` or `ANSWER: <one-word answer>`;
  - every worked example gains an `ANSWER:` line;
  - `Q:` becomes `QUESTION:` and `Options:` becomes `OPTIONS:` (also inside 937 binary questions);
  - `(A)` becomes `A)`, including "So the answer is B)." and `ANSWER: B)` in the examples;
  - `A: Let's think step by step.` becomes `Let's think step by step.`, and the cue after the test question is gone;
  - web_of_lies loses its `Question: ` prefix;
  - tracking-shuffled examples lose a double space;
  - ruin_names drops the duplicated line `fork:cot-prompts/ruin_names.txt:31`.
- **Severity and bound.** `score-changing`, `unbounded`: what a Candidate does with different bytes cannot be bounded without a paid run.

### D4 — replies are read from the `ANSWER:` line, not after "the answer is"

- **Declared by description, not as a difference from the paper.** README `:42-43` says the multiple-choice and yes/no subsets are graded "unchanged from inspect_evals". `final_answer` documents ANSWER-first (`bbh.py:156-168`). The row says the model "ends on an 'ANSWER:' line" (`benchmarks.py:6472`). None of these names the paper's "the answer is" rule as the one replaced.
- **Where.** Ours: `scorer_adapter.py:651` → `inspect_ai:solver/_multiple_choice.py:98-115`; `inspect_ai:_util/pattern.py:6-7`; `bbh.py:170-178`. Theirs: `arxiv-src:main.tex:435`, rebuilt as the reader that gives 27/27 Codex accuracies (Checks 5).
- **What differs** (Checks 10):
  - A reply in our format is right for us and wrong for the paper on all 6,508 Cases.
  - A reply in the paper's format is wrong for us on all 5,508 MC and yes/no Cases. The authors' Codex replies score 0.0 under our reader on those 23 subsets, against the paper's 54.0–97.6.
  - The worked-example shape `So the answer is B).\nANSWER: B)` is right for us and wrong for the paper on all 4,071 MC Cases.
- **Severity and bound.** `score-changing`, 6508/6508.

### D5 — pooled accuracy instead of the mean over 23 tasks

- **Declared.** Named Deviation 3 on the row (`benchmarks.py:6518-6520`), README `:47-49`, `bbh.py:69-73`.
- **Where.** Ours: `single_shot.py:1303`. Theirs: `arxiv-src:figures-and-tables/codex_and_palm_on_bigbench_hard.tex:17,29,36`.
- **What differs.** The 1,500 Cases of the two 3-size tasks weigh 1/6508 each under ours and 1/17250 each under the paper's rule. causal_judgement, penguins and snarks weigh less under ours.
- **Severity and bound.** `score-changing`, 0.1435. That is the larger of the summed positive and negative weight gaps, reached by marking only the 3-size tasks right (0.2305 vs 0.0870, Checks 12-13). On the authors' Codex marks the gap is 0.0004 (0.7397 vs 0.7393). The README's "under 0.1 point" is that one vector, not a bound.

### D6 — letters and yes/no words are compared ignoring case

- **Undeclared.**
- **Where.** `inspect_ai:solver/_multiple_choice.py:121` (`matched.upper()`) and `inspect_ai:scorer/_pattern.py:56` (`ignore_case: bool = True`), against the paper's "exact match (EM)" (`arxiv-src:main.tex:436`).
- **What differs.** `both_labels_gold_lowercase` differs on 5,008 Cases: all 4,071 MC Cases and the 937 yes/no Cases whose key is capitalised (Checks 10). The authors' Codex replies never write a lower-case key, so the paper's real case handling cannot be confirmed (Checks 11). This rests on the paper's text.
- **Severity and bound.** `score-changing`, 5008/6508.
- **Note.** The free-form markdown trim (`bbh.py:138`) differs on the 1,000 free-form Cases in the same way, but it is declared (README `:24`). It is counted inside D4/D6's Cases, not added separately.

### D7 — no temperature 0

- **Undeclared on the bbh row.** Other rows declare the same importer behaviour, e.g. `benchmarks.py:4189-4191`.
- **Where.** Paper `arxiv-src:main.tex:434` (greedy, τ = 0). inspect_evals `inspect_evals:bbh/bbh.py:150`. Ours: `task.config` is unread (`benchmarks.py:4190`) and the row has no params.
- **Severity and bound.** `possibly-score-changing`, `unknown`.

## Checks run

- [x] **Read-only on the checkout.** `git status --porcelain` showed only the calling session's untracked ledger, before (Checks 1) and after (Checks 14), as expected. Every file lived under `SCRATCH=…/scratchpad/audit-bbh-EkgA`, deleted at the end with `shutil.rmtree`.
- [x] **No keys, no model.** `env -i PATH="$PATH" HOME="$SCRATCH" UV_CACHE_DIR="$SCRATCH/uv-cache" env | grep -iE 'key|token|secret'` → empty (`grep exit=1`). Every command that ran inspect_ai or inspect_evals code ran under that prefix. Scripts that read the authors' files ran with `python3 -I`. No model, gateway or provider was called.
- [x] **Harness over paper.** The authors publish no grading code. Their reference is the data, the prompts and the Codex replies with per-subset accuracies at `9ee07bd`. The paper's rule was rebuilt and held to those 27 numbers. Where they disagree (snarks 88), the Codex run's prompt is the reference (Upstream notes).
- [x] **Declared is not a finding.** D1 and D5 are declared, and D3 and D4 partly or by description. D2, D6, D7 and the undeclared parts of D3 are findings.
- [x] **Every cell has evidence.** Each row names its command and output, or the two source locations.
- [x] **A verdict never claims more than its evidence.** No dimension is `unchecked`. D7 is open, but bounded deviations already exceed tolerance.
- No `ours` override was set.

1. `git status --porcelain` (checkout `fidelity-sweep-pr1`) → `?? docs/work/2026-11-09-fidelity-sweep.md` only. `git rev-parse --short HEAD` → `48fe0ec5b`.
2. `env -i … uv run --isolated --extra inspect python -c "imported_benchmark('bbh') …"` → `fingerprint 467f06b54836a6f8`, `origin screamingface`, `harness_url https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0/src/inspect_evals/bbh`, `paper_url https://arxiv.org/abs/2210.09261`, `params None`, `declaration BenchmarkDeclaration(failure_policy='withhold', interaction='single_shot', difficulty='medium', attempts=1)`, `judge None`, `inspect-evals 0.20.0 inspect-ai 0.3.263`.
3. `git clone https://github.com/suzgunmirac/BIG-Bench-Hard harness && git checkout 9ee07bd481feebf959a6b59d61ea57bdcf30964d` → `Sat Oct 22 00:35:24 2022 "Adding canary strings"`. The clone holds no `.py` file (`find -name '*.py'` empty): data, prompts and Codex outputs only. arXiv: the abs page lists `[v1]` only, and `e-print/2210.09261v1` was unpacked to read `main.tex` and the tables. inspect_evals' `bbh/` and inspect_ai were copied out of the run's venv to read source.
4. `env -i … uv run --isolated --extra inspect python scripts/ours_dump.py` (`captured_case_records(bbh(), TASK_REPLAY_CASES["bbh"])`) → `inspect_evals samples 6509`, `prepared cases 6508 spec.case_count 6508`, `case_digest 2454ce86e6fd87f9887f6c4849dd01d20e1ce7cb161d945ff141dabbf5c6a291 == sealed True`, `case_set_digest == sealed True`, `Counter({'MULTIPLE_CHOICE': 4071, 'BINARY_CHOICE': 1437, 'EXACT_MATCH': 750, 'DYCK': 250})`.
5. `python3 -I scripts/ref.py harness` → for every subset, `reported` (`*_eval_metrics.jsonl` accuracy) equals the rebuilt paper rule. For example `dyck_languages reported=56.8 first=56.8`, `penguins_in_a_table n=146 reported=79.5 first=79.5`, `snarks n=178 reported=59.6`. Totals: `total questions 6511`, `subsets reproduced (first): 27 / 27 (last): 27`, `prompt/target reconstruction mismatches [('snarks', 88)] 1`.
6. `python3 -I scripts/dataset_cmp.py ours.json harness` → `rows on the authors' side only: 3` (movie_recommendation 163, ruin_names 99, 144), `rows on our side only: 0`, `target differs: 0`, `matched only after normalising OPTIONS:->Options:, QUESTION:->Question:, leading Question: dropped: 937 ['causal_judgement', 'formal_fallacies', 'navigate', 'web_of_lies']`, `exactly equal questions: 5571`. `python3 -I scripts/prompt_cmp.py ours.json harness` → `authors' rebuilt prompt == Codex-recorded input on 6507`, `Candidate input bytes == authors' prompt: 0`, `equal after undoing the rewrites: 4832`, `residuals equal after the loose pass: 1428 still different: … 248` (all ruin_names; `difflib` → `-Above the above, the only humorous edit is C).`, the authors' `cot-prompts/ruin_names.txt:31`).
7. `env -i … uv run --isolated --extra inspect pytest tests/unit/inspect/test_local_task_bbh.py -q -p no:cacheprovider` → `37 passed, 1 warning in 42.04s`.
8. `python3 -I scripts/make_sheets.py` → `cases 6508 sheets 79096`. There are 12 sheets per Case, plus `inspect_evals_hole` on the 1,000 free-form Cases: `ours_format_gold`, `paper_format_gold`, `worked_example_shape_gold`, `both_labels_gold`, `ours_format_wrong`, `paper_format_wrong`, `both_labels_wrong`, `empty`, `bare_gold`, `both_labels_gold_lowercase`, `both_labels_gold_bold`, and `codex_reply`, the authors' real Codex reply for that question.
9. Reference marks: `python3 -I scripts/grade_ref.py` → `ref marks 79096`. Our marks come through the production hook `imported_benchmark("bbh").aggregation().grade_case` with a `GradeRequest` per sheet: `env -i … uv run --isolated --extra inspect python scripts/grade_ours.py` → `ours marks 79096 failed grades 0`.
10. `python3 -I scripts/compare_marks.py` → `ours_format_gold differ 6508`; `paper_format_gold differ 5508` (EXACT_MATCH/DYCK differ=0); `worked_example_shape_gold differ 4071` (MC only); `both_labels_gold differ 0`; `ours_format_wrong differ 1` and `paper_format_wrong differ 1` (both Case 2982); `both_labels_wrong differ 0`; `empty differ 0`; `bare_gold differ 5508`; `both_labels_gold_lowercase differ 5008` (MC 4071, BINARY 937); `both_labels_gold_bold differ 1000` (free-form); `codex_reply differ 4221` (MC 3039, BINARY 1182, free-form 0); `inspect_evals_hole differ 0`. Codex accuracy ours vs paper rule: 0.0 vs 54.0–97.6 on the 23 MC and yes/no subsets; 56.8/47.6/93.2/40.4 equal on the 4 free-form subsets.
11. `python3 -I` diagnostics: the two single-Case differences are `snarks_089` (`gm A ['The NB']`), whose Case 2982 input reads `where LETTER is one of A` … `A) The NB`, while the Codex input carries both options. `case-insensitive variant reproduces 27 / 27 ; markdown-trim variant reproduces 27 / 27`. The excluded rows' Codex replies are `'(B)'`, `'(B)'` and `'(D)'`, each with `paper mark 0`.
12. `env -i … uv run --isolated --extra inspect python scripts/rollup_ours.py` (real `single_shot._accuracy`) → `whole_run_metric_factory None whole_run_headline None`; all-1 1.0000, all-0 0.0000, alternating 0.5000, every-3rd 0.3333, codex-paper-marks 0.7400, only-3-size-tasks-right 0.2305, only-3-size-tasks-wrong 0.7695.
13. `python3 -I scripts/rollup_ref.py` → paper23 on the same vectors: 1.0000, 0.0000, 0.5000, 0.3333, 0.7397, 0.0870, 0.9130. `worst-case |pooled - paper23| over all 0/1 mark vectors: 0.1435`; `authors' 6511 Codex replies: paper23 0.7393 (Table 3: 0.739) pooled 0.7397`.
14. `grep -n` runs for every citation: `grep -n "NAMED DEVIATION\|multiple_choice(cot=True)\|config=source.config\|def final_answer\|^_TRIMMED\|…" bbh.py`; `grep -n "" README.md`; `grep -n 'key="bbh"\|NAMED DEVIATIONS…\|ends on an .ANSWER:. line' benchmarks.py`; `grep -n '"bbh": TaskReplayCasesSpec\|excluded_sample_ids=…' prepare.py`; `grep -n "def _accuracy\|score=round" single_shot.py`; `grep -n "set_choices_based_on_generated_response" scorer_adapter.py`; `grep -rn "task\.config" src/`; `grep -n 'RUIN_NAMES…\|config=GenerateConfig…\|QUESTION: {sample.input}\|prompt_patch_extra = …' inspect_evals/bbh/bbh.py`; `grep -n "MULTIPLE_CHOICE_TEMPLATE_COT\|ignore_case: bool = True\|matched.upper()\|ANSWER_PATTERN_WORD" inspect_ai/…`; `grep -n "greedy decoding\|the answer is\|exact match (EM)\|73.9\|(23 tasks)" main.tex`; `grep -n "Logical Deduction\|Tracking Shuffled\|All Tasks" codex_and_palm_on_bigbench_hard.tex`; `grep -n "only humorous edit is" cot-prompts/ruin_names.txt`. Then `git status --porcelain` → the same single untracked ledger, and `shutil.rmtree("$SCRATCH")`.

## Recommended paid runs

None can change the verdict. D5 (bound 0.1435) and D4/D6 already exceed tolerance with no model. Optional, to size D3 and D7 for the owner: one model, all 6,508 Cases, asked twice. First our way (current prompt, no temperature). Then the authors' way: the Codex-recorded prompt bytes at temperature 0, graded by the paper rule from Checks 5. Report both pooled and 23-task headlines. No judge is involved.

## Upstream notes

- **Paper vs the authors' outputs: they agree.** Table 3's Codex CoT per-task numbers equal the per-subset `*_eval_metrics.jsonl` accuracies. The 23-task mean of those marks is 0.7393, Table 3's 73.9 (Checks 5, 13). Bound 0.
- **The authors' data file vs their own run: one row disagrees.** `bbh/snarks.json` example 88 is cut to `(A) The NB`. The Codex run asked the full two-option question. The run is the reference, and our Case follows the file (D2). The other 6,510 rebuilt prompts equal the Codex-recorded inputs byte for byte. Bound 1/6511 for anyone serving the data file.
- **The authors' "harness" holds no grader.** `9ee07bd` contains no code. The reader rebuilt from the paper's sentence (§3) reproduces all 27 accuracies. Its handling of case and markdown cannot be pinned, because Codex never writes either. D6 and the markdown note rest on the paper's "exact match" wording.
- **[inspect_evals' `bbh` (v0.20.0)](https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0/src/inspect_evals/bbh) differs from the authors' harness beyond tolerance.** It uses the same rewritten prompts as D3 (`inspect_evals:bbh/bbh.py:100,106,400,417`), plus an answer-only multiple-choice instruction (`:178`, the default `multiple_choice()`). Its free-form scorer is `match(location="end")` (`:197`), which our README shows passes wrong answers on all 1,000 free-form Cases. It also reads from the `ANSWER:` line and reports grouped accuracy. Prompt bound `unbounded`. This is recorded for context only: the row's origin is `screamingface`, so `comparable-to-inspect` does not apply.
