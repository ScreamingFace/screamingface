---
benchmark: futurex_past
origin: screamingface
verdict: not-comparable
verdict_reason: "Two by-design differences. First, levels 3-4 are routed, matched and counted by openrouter/openai/gpt-5.4 with our own reworded prompts. Futurex-Eval judges, routes and extracts answers with DeepSeek V4 Flash or GPT-4.1 (declared Named Deviation, benchmarks.py:7997-8000), and spec §2.3 calls a different judge model not-comparable. Second, the Candidate answers closed-book with one generate() on resolved events. Every published FutureX number comes from search agents on live weekly questions, and none exists for this archive (frontier_score NotPublished, benchmarks.py:8038). Both are unbounded. Of the enumerable bounds, only the [Yes] key is measured: 1/2036. No undeclared deviation remains."
audited: 2026-11-16
audited_at: abb05ea9b   # head of branch futurex-past-local-task, NOT main (branch unmerged; base origin/main 66962a178)
fingerprint:
  benchmark: 25b22985d2393685
  harness_url: https://github.com/Futurex-ai/Futurex-Eval/tree/2626f7a297cd87c73a45408e23af8d838f5b60e5
references:
  paper: https://arxiv.org/abs/2508.11987v3
  original_harness: https://github.com/Futurex-ai/Futurex-Eval/tree/2626f7a297cd87c73a45408e23af8d838f5b60e5
  inspect_evals: https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0
  inspect_ai: https://github.com/UKGovernmentBEIS/inspect_ai/tree/v0.3.263
parity_test: none
parity_test_reason: "Futurex-Eval publishes no licence, so it cannot be vendored or run in CI, and levels 3-4 are judge-graded. tests/unit/inspect/test_futurex_past_grading.py and test_local_task_futurex_past.py (125 passed) pin our re-implementation, not parity. This audit's answer sheets ran the pinned Futurex-Eval beside our scorer offline with a scripted judge."
---

# FutureX-Past — Fidelity Record

## Verdict

**`not-comparable`.** No published number exists for this exam:

- The FutureX paper and leaderboard score agents **with search** on **live** weekly questions.
  Paper v3: `paper:sections/experiments.tex:4-14` lists the systems and `:18` gives the
  10/20/30/40 weighting. The leaderboard (`site:src/data/leaderboard.json`) holds aggregates only.
- Our row records the frontier score as `NotPublished`
  (`apps/screamingface-engine/src/screamingface_engine_inspect/benchmarks.py:8038`).

Two differences hold by design, and spec §2.3 names both as `not-comparable`:

- **D7, the judge.** Levels 3-4 are judged by `openrouter/openai/gpt-5.4` with our reworded
  prompts (`benchmarks.py:7997-8003`). Futurex-Eval uses whatever model its environment configures
  (`fork:README.md:21-35`, `fork:llm_config.py:14-28`).
- **D9, closed-book generation.** We call one `generate()` on resolved events
  (`apps/screamingface-engine/src/screamingface_engine_inspect/local_tasks/futurex_past/futurex_past.py:297`).

The authors' LLM answer extractor is replaced by a rule (D2, declared), which only a paid run can
bound.

Everything else was checked against the pinned Futurex-Eval and matches or is declared:

- **Prompt.** All 2,036 prompts reach the Candidate byte for byte.
- **Metric, levels 1-2.** The label rule and set F1 match on 19,200 of 19,208 sheets; the other 8
  are Case 310, the declared `[Yes]` key.
- **Metric, levels 3-4.** Number, text, ranking and set marking match with one scripted judge,
  apart from the declared overlap cap and extraction.
- **Judge replies.** The router reply parser agrees with upstream on 14/14 replies.
- **Roll-up.** It equals `fork:run_weekly_leaderboard.py`'s `main()` to six decimals.

Every earlier finding is fixed or declared: U1-U4 and U7 are fixed, U5 and U6 are declared. The
one measured enumerable bound is `1/2036 = 0.0005 ≤ 0.005`. The verdict rests on D7 and D9.

## Dimensions

| dimension | status | severity | bound | evidence |
|---|---|---|---|---|
| dataset | deviation | score-changing | 1/2036 (Case 310, D1) | **Ours:** `futurex-ai/Futurex-Past@8299bfa1`, file `data/train-00000-of-00001.parquet`. Downloaded sha256 `a385ef5e…36bb` equals `DATASET_SHA256` (`futurex_past.py:79`). 2,036 Samples, id mismatches `[]` (Checks 5); gold differs from the harness parse (`fork:run_single_submission.py:30-39`) only on Case 310 (first and second audits; the loader and `prepare.py` are unchanged since, per `git diff --stat e463be2e9..abb05ea9b`). **Theirs:** no Futurex-Past loader; it reads an `.xlsx` (`fork:run_weekly_leaderboard.py:47-67`). |
| prompt | match | — | — | Every Case through `load_futurex_past()` + `prepared_case(…, TASK_REPLAY_CASES["futurex_past"])`: `input != prompt: []`, a `str` input with no system message, sha256 `4891c0e59df3e43a6eb6e1fa0e179a40d914225e58dfa806b73089ad99432855`, the same in all three audits (Checks 5). Theirs: the dataset `prompt` is "the full prompt that was provided to the LLM agent" (`hub:README.md:81`); the harness uses it as the question (`fork:run_weekly_leaderboard.py:60-63`). |
| answer extraction | deviation | possibly-score-changing | unknown (D2 declared) | Ours: the last `\boxed{}` with one level of nesting (`grading.py:69`). `reply_tokens` (`grading.py:118-122`) removes a brace-balanced whole-box `\text{}` (`unwrap_text`, `:84-97`; `_closing_brace`, `:100-108`), splits on commas, and unwraps each item. It is used at levels 1-2 (`futurex_past.py:224`) and 3-4 (`grading.py:386`). `{,}` is read as a comma on the number path (`grading.py:427`). Theirs: the LLM extractor (`fork:eval.py:64-149`, prompt `:73`). With a simulated extractor (box content, brace-balanced `\text{}` removed whole and per item, "is a number" iff `utils.is_number`): levels 1-2 differ only on Case 310 (8/19,208), including all `text_items`, `text_items_spaced` and `text_whole` sheets. The level-3/4 differences are all extraction-dependent (D2): see the metric row. |
| metric | deviation | possibly-score-changing | unknown (D3, D4 declared) | **Levels 1-2**, tokens equal: 19,208 sheets, 8 differ, all Case 310. **Levels 3-4**, through `fork:eval.py:estimate_routed_scores` (real router and judge functions, one scripted judge on both sides), all differences are explained: (a) `legacy_type_a` 748: `$`, `%` and comma numbers, and keys like `RvPLegend10`, `C3.4`, `0.9%` that upstream's `is_number` stand-in turns into floats (D2); (b) `legacy_type_b` 568: the D3 cap 323, the empty box 154, `num_latex_commas` 89 (D2); (c) `unordered_set` 842: the empty box 664 and comma numbers 178 (D2). The number-judge input differs only on the empty box; the rank-judge lists differ only on the empty box. Judge-reply parsing, rerun at e463be2e9 and with no parser touched since (`git diff e463be2e9..abb05ea9b`): router 14/14, count 7/7, number 8/8, match 6/6, option-letter rank 4/4; set and rank differ only on D3 and D4. |
| roll-up | deviation | score-changing | 0 at full coverage (measured); run-dependent otherwise (D5, D6, D10 declared) | Measured at e463be2e9 on five fixed vectors over all 2,036 Cases, ours vs the real `fork:run_weekly_leaderboard.py:main()`: all-1 1.0/1.0, all-0 0.0/0.0, alternating 0.496849/0.496849, gold-sheet marks 0.964903/0.964903, random 0.500645/0.500645. Absent level 4: 1.0 vs 0.6 (D5). 20 absent: 1.0 vs 0.995291 (D6). 20 bare no-level zeros: 1.0 vs 0.995291 (D10). `tier_weighted_mean`, `leveled` (`futurex_past.py:243`) and `LEVEL_WEIGHTS` (`:87`) are untouched by abb05ea9b, whose only change to `futurex_past.py` is the level-1/2 reader at `:224`. |
| judge | deviation | score-changing (by design) | unbounded (D7, D8 declared) | Ours: `openrouter/openai/gpt-5.4`, temperature 0, max_tokens 4096, web_search false (`benchmarks.py:8000-8003`); 3 router asks and the 4,096 cap declared (`benchmarks.py:7986-7987`, README `:84-87`). Theirs: the env-configured model, temperature 0, 5000 tokens (`fork:llm_judge_level_34.py:30`), 512 for the router and set count (`fork:metric_router.py:110`, `fork:llm_judge_level_34.py:227`), 2 router attempts (`fork:metric_router.py:169`). Prompts make the same decisions in our words (README `:53-55`). `parse_route` mirrors `_parse_route` (`grading.py:315`). The paper names no scoring judge. |
| sampling | deviation | score-changing (by design) | unbounded (D9 declared) | Ours: `solver=generate()` (`futurex_past.py:297`), `attempts=1`, `single_shot`, no temperature or max_tokens on the row (Checks 2). Theirs: search agents, deep-research models and "Think&Search" LLMs predicting before resolution (`paper:sections/experiments.tex:4-14`); the paper sets no decoding parameters. |

## Deviations

All declared. None is undeclared.

### D1 — the key `[Yes]` is read as `["Yes"]` (Case 310)
- **Declared.** `benchmarks.py:7981`; README `:79`.
- **Where.** Theirs: `fork:run_single_submission.py:35-38` keeps the label `[Yes]`, which nothing
  can match.
- **Severity / bound.** `score-changing`, `1/2036 = 0.0005`. The Case is position 310, id
  `69c527154b6f01005cae131a|2026-04-03`, level 1.

### D2 — the answer is read by rule, not by an LLM extractor
- **Declared.** `benchmarks.py:7979-7980`; README `:76-78`, the `\textbf` limit at `:80-81`, the
  `{,}` rule at `:61`, and one level of box nesting at `:44`.
- **What differs.**
  - A boxless reply always scores 0 with us; their extractor can find an answer in it.
  - Their extractor can turn `$115`, `5%` or `1,234` into floats.
  - A raw `1{,}234` is 1234 with us and 1 under upstream's `to_float` unless the extractor
    rewrites it.
  - A box nested two levels deep is unreadable with us.
- **Severity / bound.** `possibly-score-changing`, `unknown`.

### D3 — the rank overlap count is capped at k
- **Declared.** `benchmarks.py:7984-7985`; README `:88`; `grading.py:460`.
- **Where.** Theirs: no cap (`fork:llm_judge_level_34.py:194-197`); 1.12 measured.
- **Severity / bound.** `possibly-score-changing`, `unknown`.

### D4 — an unreadable judge reply fails the Case (it leaves the denominator)
- **Declared.** `benchmarks.py:7984`; README `:82-85`.
- **Where.** Theirs scores it 0.0 (`fork:eval.py:260-263`, `fork:llm_judge_level_34.py:228-230`).
- **Severity / bound.** `possibly-score-changing`, `unknown`.

### D5 — a level absent from a run renormalises the weights
- **Declared.** `benchmarks.py:7982-7983`; README `:89-90`.
- **Severity / bound.** `score-changing`, `0` on a full run.

### D6 — `coverage_declare`: a failed Candidate call leaves the headline
- **Declared.** README `:93-96`; row `benchmarks.py:7970-7973`.
- **Where.** Theirs counts it 0 (`fork:run_weekly_leaderboard.py:126-136`).
- **Severity / bound.** `score-changing`, `0` at full coverage; otherwise it depends on the run.

### D7 — the judge model, its prompt wording, token caps and router asks
- **Declared.** `benchmarks.py:7997-8000` and `:7986-7987`; README `:70`, `:53-55`, `:84-87`.
- **Severity / bound.** `score-changing` by design, `unbounded`.

### D8 — the route is not cached across runs
- **Declared.** README `:91-92`.
- **Severity / bound.** `possibly-score-changing`, `unknown`.

### D9 — closed-book, one generation, resolved events
- **Declared.** README `:17-21`; row description `benchmarks.py:7961-7963`; spec §5.
- **Severity / bound.** `score-changing` by design, `unbounded`.

### D10 — an abstained Case whose grading failed leaves the headline (formerly U6)
- **Declared.** `benchmarks.py:7988-7989`; README `:97-100`; `futurex_past.py:243-256`.
- **Where.** Ours: a bare no-level 0.0 from `single_shot.py:1626-1627` is left out of the
  per-level means. Theirs counts a scoring failure as 0.0 (`fork:eval.py:260-263`).
- **Measured** (at e463be2e9; this code is unchanged since): 20 such zeros give 1.0 with us and
  0.995291 with them.
- **Severity / bound.** `score-changing`, run-dependent; 0 unless an abstained Case's grading fails.

### Resolved findings (kept for the trail)

| finding | first seen | resolved at | evidence |
|---|---|---|---|
| U1: a whole-box `\text{}` at levels 1-2 | c8dadab6c | e463be2e9 | levels 1-2 vs simulated extractor 199 → 7 differing sheets; still holds at abb05ea9b (`text_whole` equals theirs) |
| U2: a prose number judged on the whole box | c8dadab6c | e463be2e9 | `grading.py:427-433`; `number_text` differs only on the empty box |
| U3: unsorted option letters reach the rank judge | c8dadab6c | e463be2e9 | `grading.py:452`; 4/4 sheets |
| U4: a lenient router parser | c8dadab6c | e463be2e9 | `grading.py:315`; 14/14 replies |
| U5: token caps and the router's ask count | c8dadab6c | declared e463be2e9 | `benchmarks.py:7986-7987` |
| U6: a no-level Case dropped | e463be2e9 | declared abb05ea9b | D10 |
| U7: per-option `\text{}` misread | e463be2e9 | abb05ea9b | `reply_tokens` (`grading.py:118-122`); new vs e463be2e9 changed only the 192 per-option sheets at levels 1-2 (96 Cases) and per-option sheets on Cases 68, 814, 815, 956 at levels 3-4 (0.8 → 1.0); levels 1-2 vs theirs now Case 310 only |

## Checks run

- [x] **Read-only on the checkout.** `git status --porcelain` was empty before and after. The
  scratch folder was deleted with `rm -rf`.
- [x] **No keys, no model.** `env -i PATH="$PATH" HOME="$SCRATCH" UV_CACHE_DIR="$SCRATCH/uv-cache" env | grep -iE 'key|token|secret'`
  printed nothing (`grep exit=1`). Futurex-Eval ran under `env -i … python -I` with its LLM entry
  points scripted. No model, gateway or provider was called.
- [x] **Harness over paper.** See Upstream notes.
- [x] **Declared is not a finding.** D1-D10 are all declared; there are no undeclared findings.
- [x] **Every cell has evidence.**
- [x] **Every `file:line` is copied from command output** (`grep -n` at abb05ea9b in Checks 6;
  `fork:` lines from `cat -n`/`grep -n` at the pinned commit in the first audit).
- [x] **Every citation names its tree.**
  - `fork:` is [Futurex-ai/Futurex-Eval@2626f7a2](https://github.com/Futurex-ai/Futurex-Eval/tree/2626f7a297cd87c73a45408e23af8d838f5b60e5).
  - `paper:` is the arXiv 2508.11987v3 e-print source.
  - `hub:` is [futurex-ai/Futurex-Past@8299bfa1](https://huggingface.co/datasets/futurex-ai/Futurex-Past/tree/8299bfa1609dec30f267891a74d76e62902c9d71).
  - `site:` is [Futurex-ai/Futurex-ai.github.io@35e5bc2b](https://github.com/Futurex-ai/Futurex-ai.github.io/tree/35e5bc2bc2b9cee2255ccafba4e23d92c932d52b).
  - Ours are repo paths; a bare `grading.py` or `futurex_past.py` means
    `apps/screamingface-engine/src/screamingface_engine_inspect/local_tasks/futurex_past/`.
- [x] **A verdict never claims more than its evidence.** No dimension is `unchecked`; the verdict
  rests on D7 and D9.
- **Authors' recorded replies.** None. Searched: the `futurex-ai` organisation on the Hugging Face
  Hub (questions only), the `Futurex-ai` GitHub organisation, and `site:src/data/leaderboard.json`,
  which holds aggregates only.

1. `git rev-parse --short HEAD` gave `abb05ea9b`; `git status --porcelain` printed nothing.
   `git diff --stat e463be2e9..abb05ea9b` touches `benchmarks.py` (revision and one NAMED
   DEVIATION), the README, `futurex_past.py` (the level-1/2 reader only), `grading.py`
   (`unwrap_text`, `_closing_brace`, `reply_tokens`, `grade_level_34` tokens), and tests and docs.
   `prepare.py` does not appear.
2. `uv run --extra inspect python -c '…imported_benchmark("futurex_past")'` gave
   `fingerprint 25b22985d2393685 revision 25b22985d2393685`,
   `BenchmarkDeclaration(failure_policy='coverage_declare', interaction='single_shot', difficulty='hard', attempts=1)`,
   and `JudgeSpec(model='openrouter/openai/gpt-5.4', params=(('temperature','0'),('max_tokens','4096'),('web_search','false')), …)`.
   Then `uv run --extra inspect pytest tests/unit/inspect/test_futurex_past_grading.py tests/unit/inspect/test_local_task_futurex_past.py -q -p no:cacheprovider`
   gave `125 passed, 3 warnings`.
3. Harness setup: `git clone` at `2626f7a`; `uv venv --python 3.12`;
   `uv pip install openai tenacity diskcache pandas openpyxl pyarrow requests`. The parquet's
   sha256 was `a385ef5e…36bb`. The previous head's `grading.py` was taken with
   `git show e463be2e9:…/grading.py` into scratch (read-only on the checkout).
4. **Answer sheets.** 32,718 sheets: the earlier set plus `text_items_spaced` (`\text {A}`),
   `text_whole_of_items` and `num_text`. `ours.py` ran the abb05ea9b scorer (levels 1-2 through
   `reply_tokens`, mirroring `futurex_past.py:224`; levels 3-4 through `grade_level_34`) and the
   e463be2e9 scorer side by side. `theirs.py` (`env -i`, `-I`) ran Futurex-Eval with the same
   scripted judge. `compare.py` gave:
   - `L12 vs theirs score_tokens_equal: 19208, differ 8` and `score_sim_extract: 19208, differ 8`
     (all Case 310).
   - `L12 new vs e463be2e9: 19208, differ 192` (`text_items` 96, `text_items_spaced` 96).
     Level-1/2 Cases where a per-item or whole-box `\text{}` sheet differs from the plain gold: 0.
   - `L34 legacy_type_a vs theirs: 12858, differ 748`; `legacy_type_b: differ 568`;
     `unordered_set: differ 842` (breakdowns in the metric row). Level-3/4 number-judge input
     differs only on `empty` (303); rank-judge lists differ only on `empty` (154).
   - `L34 new vs e463be2e9`: `legacy_type_a` 304 (per-option sheets), `legacy_type_b` 6 (Cases
     814, 815, 956 at 0.8 → 1.0), `unordered_set` 2 (Case 68 at 0.8 → 1.0).
   - Level-3/4 route-sheets where per-item `\text{}` differs from the plain gold: 16 at abb05ea9b,
     against 328 at e463be2e9. All 16 are on the malformed-markup keys 1228, 1230, 1232 and 1234,
     and on each ours equals theirs.
   - 652 level-3/4 sheets with two nested levels (`text_whole_of_items`) are unreadable on our
     side by design (D2) and were skipped.
5. `HF_HOME=$SCRATCH/hf-home uv run --extra inspect python prompt_bytes.py` gave
   `samples 2036 | input != prompt: [] | id mismatches: []` and
   `sha256 of all inputs 4891c0e5…2855`.
6. Citation greps: `futurex_past.py:79,87,224,243,297`;
   `grading.py:70,84,100,118,122,315,386,427,433,452,460`;
   `benchmarks.py:7950,7973,7979,7981,7982,7984,7986,7988,7997,8000,8003,8038`; README
   `:19,44-45,53,61,70,73,76,79,80,85,86,88,89,91,93,97,102,104,107,109,113`.
7. Final: `git status --porcelain` printed nothing; HEAD is `abb05ea9b`; the scratch folder was
   removed.

Not rerun at abb05ea9b, because the code is unchanged since e463be2e9: the judge-reply sheets (14
router, 7 count, 8 number, 6 match, 4 option-letter) and the roll-up vectors. Results are as
quoted in the Dimensions table.

## Recommended paid runs

- **None can change the verdict** (D7 and D9 hold by design).
- **Optional, to size D2, D3, D4 and D8.** Record one Candidate run on all 2,036 Cases. Have a
  key-holding owner re-mark the same replies with Futurex-Eval@2626f7a2 under
  `DEEPSEEK_MODEL=deepseek-v4-flash` (about 2,036 extractor calls, 664 router calls and about
  1,000 judge calls), and compare per Case. Repeating it with `OPENAI_API_MODEL` set to gpt-5.4
  separates the judge-model effect from the extraction and parsing effects.

## Upstream notes

- **σ.** The paper's "standard deviation of the outcome over the past 7 days"
  (`paper:sections/approach.tex:481`) vs 5% of the key in the code (`fork:eval.py:248-252`). The
  harness wins. README `:104-106`.
- **Level 2.** The paper describes halving and zeroing (`approach.tex:347`), but its metric is F1
  (`approach.tex:463-466`), and so is the code (`fork:eval.py:168-202`). README `:107-108`.
- **Missing predictions.** The paper allows misalignment across models (`approach.tex:426-442`);
  the weekly script counts a miss as 0 (`fork:run_weekly_leaderboard.py:126-136`).
- **Ranking.** The harness adds an order-free shortcut for option letters, an `unordered_set`
  route chosen by an LLM router, and no cap on the overlap count. None of these is in the paper
  (`approach.tex:468-476`).
- **"Yes" anywhere.** A match and the rank verdict count as yes if the word appears anywhere in
  the judge's reply (`fork:llm_judge_level_34.py:172`, `:191`). We copy it. README `:109-112`.
- **Harness self-test.** `test_contract_conflict_skips_router` fails at the pin
  (`fork:test_harness.py:38-46`). README `:113-115`.
- **Missing dependency.** The README's install line omits `requests` (imported at
  `fork:llm_judge_level_34.py:1`).
- **Ids.** The harness keys predictions and the route cache by `id`, which recurs in
  Futurex-Past (21 ids over 119 rows).
- **The `is_number` rule.** "Starts or ends with a number" (`fork:utils.py:29-50`) counts
  `RvPLegend10`, `C3.4` and `0.9%` as numbers. If the extractor flags them as numbers, the label
  comparison on the `legacy_type_a` route then fails (seen with the simulated extractor on Cases
  1079, 1496, 1125, 1128, 1146, 1330; a float key on Cases 396, 517, 636).
- **Answer keys with markup.** At 8299bfa1, 16 keys carry `\boxed{}`: Cases 1216, 1219, 1222,
  1225, 1228, 1230, 1232, 1234, 1237, 1241, 1244, 1247, 1250, 1253, 1255, 1257. In Cases 1230 and
  1234 the first item has an unclosed `\boxed{` (for example `['\boxed{block/buzz', …]`). Both
  scorers unwrap a closed `\boxed{}` and leave the unclosed ones as written, and their marks agree
  on these Cases. It is a data defect worth reporting upstream.
- **inspect_evals.** FutureX is not in inspect_evals 0.20.0; those references record installed
  versions only.
