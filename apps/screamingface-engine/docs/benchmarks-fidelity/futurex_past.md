---
benchmark: futurex_past
origin: screamingface
verdict: not-comparable
verdict_reason: "Two by-design differences. First, levels 3-4 are routed, matched and counted by openrouter/openai/gpt-5.4 with our own reworded prompts. Futurex-Eval judges, routes and extracts answers with DeepSeek V4 Flash or GPT-4.1 (declared Named Deviation, benchmarks.py:7997-8000), and spec §2.3 calls a different judge model not-comparable. Second, the Candidate answers closed-book with one generate() on resolved events. Every published FutureX number comes from search agents on live weekly questions, and none exists for this archive (frontier_score NotPublished, benchmarks.py:8038). Both are unbounded. Of the enumerable bounds, only the [Yes] key is measured: 1/2036. No undeclared deviation remains."
audited: 2026-11-16
audited_at: 55d7f087f   # local head of branch futurex-past-local-task, NOT main (unmerged; rebased onto origin/main cc5cfd36d)
fingerprint:
  benchmark: a4593e342d18b512
  harness_url: https://github.com/Futurex-ai/Futurex-Eval/tree/2626f7a297cd87c73a45408e23af8d838f5b60e5
references:
  paper: https://arxiv.org/abs/2508.11987v3
  original_harness: https://github.com/Futurex-ai/Futurex-Eval/tree/2626f7a297cd87c73a45408e23af8d838f5b60e5
  inspect_evals: https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0
  inspect_ai: https://github.com/UKGovernmentBEIS/inspect_ai/tree/v0.3.263
parity_test: none
parity_test_reason: "Futurex-Eval publishes no licence, so it cannot be vendored or run in CI, and levels 3-4 are judge-graded. tests/unit/inspect/test_futurex_past_grading.py and test_local_task_futurex_past.py (151 passed) pin our re-implementation, not parity. This audit's answer sheets ran the pinned Futurex-Eval beside our scorer offline with a scripted judge."
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

The authors' LLM answer extractor is replaced by a rule (D2, declared). Since 55d7f087f that rule
reads only a whole plain number and sends anything else to the judge. Only a paid run can bound D2.

Everything else was checked against the pinned Futurex-Eval and matches or is declared:

- **Prompt.** All 2,036 prompts reach the Candidate byte for byte.
- **Metric, levels 1-2.** The label rule and set F1 match on every sheet except Case 310, the
  declared `[Yes]` key.
- **Number score.** `max(0, 1 − ((ŷ−y)/σ)²)` with σ = 5% of the key matches upstream on 76 grid
  points, extremes included.
- **Levels 3-4 otherwise.** Ranking, set and text marking match with one scripted judge, apart
  from the declared overlap cap and extraction.
- **Judge replies and roll-up.** The router parser and the 10/20/30/40 roll-up equal upstream's.

All earlier findings U1-U7 are fixed or declared. The one measured enumerable bound is
`1/2036 = 0.0005 ≤ 0.005`. The verdict rests on D7 and D9.

## Dimensions

| dimension | status | severity | bound | evidence |
|---|---|---|---|---|
| dataset | deviation | score-changing | 1/2036 (Case 310, D1) | **Ours:** `futurex-ai/Futurex-Past@8299bfa1`, file `data/train-00000-of-00001.parquet`. Downloaded sha256 `a385ef5e…36bb` equals `DATASET_SHA256` (`futurex_past.py:79`). 2,036 Samples; levels {1: 659, 2: 713, 3: 338, 4: 326}; id mismatches `[]`; `case_count` 2036 (Checks 6). Gold differs from the harness parse (`fork:run_single_submission.py:30-39`) only on Case 310 (earlier audits; the loader and `prepare.py` are unchanged since). **Theirs:** no Futurex-Past loader; it reads an `.xlsx` (`fork:run_weekly_leaderboard.py:47-67`). |
| prompt | match | — | — | Every Case through `load_futurex_past()` + `prepared_case(…, TASK_REPLAY_CASES["futurex_past"])`: `input != prompt: []`, a `str` input with no system message, sha256 `4891c0e59df3e43a6eb6e1fa0e179a40d914225e58dfa806b73089ad99432855`, the same in all four audits (Checks 6). Theirs: the dataset `prompt` is "the full prompt that was provided to the LLM agent" (`hub:README.md:81`); the harness uses it as the question (`fork:run_weekly_leaderboard.py:60-63`). |
| answer extraction | deviation | possibly-score-changing | unknown (D2 declared) | Ours: the last `\boxed{}` with one level of nesting; `reply_tokens` (`grading.py:119`) removes a brace-balanced whole-box and per-item `\text{}` (`unwrap_text`, `:85`) and splits on commas; levels 1-2 at `futurex_past.py:224`, levels 3-4 at `grading.py:397`. Single-number keys: `{,}` → `,` (`grading.py:438`), then `to_float` accepts only a whole plain number (`_PLAIN_NUMBER` `:167`, `to_float` `:172-189`). Otherwise the first comma piece goes to the judge (`:444`). Theirs: the LLM extractor (`fork:eval.py:64-149`, prompt `:73`), then `utils.to_float` (first numeric run, `fork:utils.py:3-27`) only when the extractor says the answer is a number (`fork:eval.py:143-144`). The `to_float` table and the simulated-extractor sheets are in Checks 4-5. Every difference depends on what the LLM extractor would write. |
| metric | deviation | possibly-score-changing | unknown (D3, D4 declared) | **Levels 1-2**, tokens equal: 16,464 sheets, 7 differ, all Case 310. **Number score:** ours `number_score` (`grading.py:221-232`) vs upstream's σ derivation (`fork:eval.py:247-252`) plus `judge_number_overall` (`fork:llm_judge_level_34.py:234-235`, called through `estimate_score_level_3_4`): 76/76 equal, including keys 0 / 1 / 249.41 / −634500 / 1e-9 / 1e12, offsets 0, ±1-5.1%, +50%, the zero-key boundary (0.009 → 0.19, 0.01 → 0, −0.0099 → 0.0199, 0.011 → 0), and ±1e200 / ±inf / nan → 0 on both sides (upstream raises `OverflowError` on 1e200 and its worker scores 0.0; `fork:eval.py:260-263`). **Levels 3-4** with one scripted judge: differences vs upstream are the D3 cap (323 sheets) and D2 extraction artefacts (Checks 4). Judge-reply parsing is unchanged since e463be2e9 (router 14/14, count 7/7, number 8/8, match 6/6, option-letter rank 4/4). |
| roll-up | deviation | score-changing | 0 at full coverage (measured); run-dependent otherwise (D5, D6, D10 declared) | `futurex_past.py` is unchanged since 93d427296 (`git diff --stat 93d427296 55d7f087f -- …/futurex_past.py` empty), so the e463be2e9 measurements stand: five vectors over all 2,036 Cases equal to six decimals against the real `fork:run_weekly_leaderboard.py:main()` (1.0, 0.0, 0.496849, 0.964903, 0.500645); level 4 absent gives 1.0 vs 0.6 (D5); 20 absent gives 1.0 vs 0.995291 (D6); 20 bare no-level zeros give 1.0 vs 0.995291 (D10). `LEVEL_WEIGHTS` `futurex_past.py:87`, `leveled` `:243`. |
| judge | deviation | score-changing (by design) | unbounded (D7, D8 declared) | Ours: `openrouter/openai/gpt-5.4`, temperature 0, max_tokens 4096, web_search false (`benchmarks.py:8000-8003`); 3 router asks and the 4,096 cap declared (`benchmarks.py:7986-7987`, README `:87-90`). Theirs: the env-configured model, temperature 0, 5000 tokens (`fork:llm_judge_level_34.py:30`), 512 for the router and set count (`fork:metric_router.py:110`, `fork:llm_judge_level_34.py:227`), 2 router attempts (`fork:metric_router.py:169`). Prompts make the same decisions in our words (README `:53-55`). `parse_route` mirrors `_parse_route` (`grading.py:326`). |
| sampling | deviation | score-changing (by design) | unbounded (D9 declared) | Ours: `solver=generate()` (`futurex_past.py:297`), `attempts=1`, `single_shot`, no temperature or max_tokens on the row (Checks 1). Theirs: search agents, deep-research models and "Think&Search" LLMs predicting before resolution (`paper:sections/experiments.tex:4-14`); the paper sets no decoding parameters. |

## Deviations

All declared. None is undeclared.

### D1 — the key `[Yes]` is read as `["Yes"]` (Case 310)
- **Declared.** `benchmarks.py:7981`; README `:82`.
- **Severity / bound.** `score-changing`, `1/2036 = 0.0005`. The Case is position 310, id
  `69c527154b6f01005cae131a|2026-04-03`, level 1.

### D2 — the answer is read by rule, not by an LLM extractor
- **Declared.** `benchmarks.py:7979-7980`; README `:76-81`, the table row `:61`, the `\textbf`
  limit `:83-84`, and one level of box nesting `:43`.
- **What differs.**
  - A boxless reply always scores 0 with us; their extractor can find an answer in it.
  - For a single-number key, our `to_float` (`grading.py:172-189`) reads only a whole plain
    number: optional sign and `$`, digits with optional comma thousands groups, decimals, an
    exponent, `%`. Everything else goes to the judge as its first comma piece (`grading.py:444`).
  - That rule is **stricter** than upstream's `utils.to_float` (`fork:utils.py:3-27`), which takes
    the first numeric run. Upstream calls it only after its LLM extractor has said the answer is a
    number and rewritten it (`fork:eval.py:143-144`).
  - Measured on 33 strings, the two agree on plain numbers and differ on 15 (Checks 5). In those
    15, ours is correct where upstream's helper half-reads (`1e3` is 1000 for us and 1 for them;
    `-$5` is −5 for us and +5 for them), or ours defers to the judge (`1/2`, `10^3`, `1_000`, `5.`,
    `1,23,456`).
  - On a raw-text basis two cases go the other way: `1,23,456` and `2,49` reach our judge as `1`
    and `2` (the first comma piece), while upstream's helper would read 123456 and 249. Which side
    is closer to Futurex-Eval depends on its extractor's rewrite.
  - Number sheets on single-number keys (Checks 4): 1,845 of 9,331 differ from upstream with a
    stand-in extractor (`utils.is_number` + `utils.to_float`). All are explained by the cases
    above, plus `{,}` (89).
- **Severity / bound.** `possibly-score-changing`, `unknown`; it needs the real extractor.

### D3 — the rank overlap count is capped at k
- **Declared.** `benchmarks.py:7984-7985`; README `:91`; `grading.py:471`.
- **Severity / bound.** `possibly-score-changing`, `unknown`. Theirs is uncapped
  (`fork:llm_judge_level_34.py:194-197`).

### D4 — an unreadable judge reply fails the Case (it leaves the denominator)
- **Declared.** `benchmarks.py:7984`; README `:85-88`.
- **Severity / bound.** `possibly-score-changing`, `unknown`. Theirs scores it 0.0
  (`fork:eval.py:260-263`).

### D5 — a level absent from a run renormalises the weights
- **Declared.** `benchmarks.py:7982-7983`; README `:92-93`.
- **Severity / bound.** `score-changing`, `0` on a full run.

### D6 — `coverage_declare`: a failed Candidate call leaves the headline
- **Declared.** README `:96-99`; `benchmarks.py:7970-7973`.
- **Severity / bound.** `score-changing`, `0` at full coverage; run-dependent otherwise. Theirs
  counts it 0 (`fork:run_weekly_leaderboard.py:126-136`).

### D7 — the judge model, its prompt wording, token caps and router asks
- **Declared.** `benchmarks.py:7997-8000`, `:7986-7987`; README `:70`, `:53-55`, `:87-90`.
- **Severity / bound.** `score-changing` by design, `unbounded`.

### D8 — the route is not cached across runs
- **Declared.** README `:94-95`.
- **Severity / bound.** `possibly-score-changing`, `unknown`.

### D9 — closed-book, one generation, resolved events
- **Declared.** README `:17-21`; `benchmarks.py:7961-7963`; spec §5.
- **Severity / bound.** `score-changing` by design, `unbounded`.

### D10 — an abstained Case whose grading failed leaves the headline
- **Declared.** `benchmarks.py:7988-7989`; README `:100-103`; `futurex_past.py:243`.
- **Severity / bound.** `score-changing`, run-dependent; 0 unless an abstained Case's grading
  fails. Measured: 1.0 vs 0.995291 with 20 such Cases.

### Resolved findings (kept for the trail)

| finding | first seen | resolved at (old hash → rebased hash) | evidence |
|---|---|---|---|
| U1: a whole-box `\text{}` at levels 1-2 | c8dadab6c | e463be2e9 → 4a13cc636 | levels 1-2 vs upstream: Case 310 only |
| U2: a prose number judged on the whole box | c8dadab6c | e463be2e9 → 4a13cc636 | `grading.py:444` |
| U3: unsorted option letters reach the rank judge | c8dadab6c | e463be2e9 → 4a13cc636 | `grading.py:463`; 4/4 |
| U4: a lenient router parser | c8dadab6c | e463be2e9 → 4a13cc636 | `grading.py:326`; 14/14 |
| U5: token caps and the router's ask count | c8dadab6c | declared e463be2e9 → 4a13cc636 | `benchmarks.py:7986-7987` |
| U6: a no-level Case dropped | e463be2e9 | declared abb05ea9b → 93d427296 | D10 |
| U7: per-option `\text{}` misread | e463be2e9 | abb05ea9b → 93d427296 | `reply_tokens` (`grading.py:119`) |

## Checks run

- [x] **Read-only on the checkout.** `git status --porcelain` was empty before and after. The
  scratch folder was deleted with `rm -rf`.
- [x] **No keys, no model.** `env -i PATH="$PATH" HOME="$SCRATCH" UV_CACHE_DIR="$SCRATCH/uv-cache" env | grep -iE 'key|token|secret'`
  printed nothing (`grep exit=1`). Futurex-Eval ran under `env -i … python -I` with its LLM entry
  points scripted. No model, gateway or provider was called.
- [x] **Harness over paper.** See Upstream notes.
- [x] **Declared is not a finding.** D1-D10 are all declared; there are no undeclared findings.
- [x] **Every cell has evidence.**
- [x] **Every `file:line` is copied from command output** (`grep -n` at 55d7f087f, Checks 7;
  `fork:` lines from `cat -n`/`grep -n` at the pin in the first audit).
- [x] **Every citation names its tree.**
  - `fork:` is [Futurex-ai/Futurex-Eval@2626f7a2](https://github.com/Futurex-ai/Futurex-Eval/tree/2626f7a297cd87c73a45408e23af8d838f5b60e5).
  - `paper:` is the arXiv 2508.11987v3 e-print source.
  - `hub:` is [futurex-ai/Futurex-Past@8299bfa1](https://huggingface.co/datasets/futurex-ai/Futurex-Past/tree/8299bfa1609dec30f267891a74d76e62902c9d71).
  - `site:` is [Futurex-ai/Futurex-ai.github.io@35e5bc2b](https://github.com/Futurex-ai/Futurex-ai.github.io/tree/35e5bc2bc2b9cee2255ccafba4e23d92c932d52b).
  - Ours are repo paths; a bare `grading.py` or `futurex_past.py` means
    `apps/screamingface-engine/src/screamingface_engine_inspect/local_tasks/futurex_past/`.
- [x] **A verdict never claims more than its evidence.** No dimension is `unchecked`; the verdict
  rests on D7 and D9.
- **Authors' recorded replies.** None. Searched the `futurex-ai` organisation on the Hugging Face
  Hub, the `Futurex-ai` GitHub organisation, and `site:src/data/leaderboard.json`, which holds
  aggregates only.

1. `git rev-parse --short HEAD` gave `55d7f087f`; `git status --porcelain` printed nothing;
   `git merge-base HEAD origin/main` gave `cc5cfd36d`.
   - `git diff abb05ea9b 93d427296 -- apps/screamingface-engine/src` is empty, so the rebase moved
     no code.
   - `git diff 93d427296 55d7f087f -- apps/screamingface-engine/src` touches only `grading.py`
     (`to_float`, `_PLAIN_NUMBER`, `number_score`), the README, and `published_revision`.
     `futurex_past.py` and `prepare.py` are unchanged.
   - `imported_benchmark("futurex_past")` gave `fingerprint 118a7a5a5df8e185 revision 118a7a5a5df8e185`,
     `BenchmarkDeclaration(failure_policy='coverage_declare', interaction='single_shot', difficulty='hard', attempts=1)`,
     and `JudgeSpec(model='openrouter/openai/gpt-5.4', params=(('temperature','0'),('max_tokens','4096'),('web_search','false')), …)`.
   - `uv run --extra inspect pytest tests/unit/inspect/test_futurex_past_grading.py tests/unit/inspect/test_local_task_futurex_past.py -q -p no:cacheprovider`
     gave `151 passed`.
   - `grep -rn "to_float\|number_score"` shows both used only in `_number` (`grading.py:439`,
     `:447`).
2. Harness setup: `git clone` at `2626f7a`; `uv venv --python 3.12`;
   `uv pip install openai tenacity diskcache pandas openpyxl pyarrow requests`. The parquet's
   sha256 was `a385ef5e…36bb`. The previous head's `grading.py` was taken with
   `git show 93d427296:…/grading.py` into scratch.
3. **Answer sheets.** 33,763 sheets: the earlier set plus 31 number variants per single-number
   key (exact, ±%, commas, `{,}`, `$`, `-$`, `%`, negative, `+`, prose, unit, two numbers, prose
   with two numbers, `\text{}`, `e`, `E`, a fraction, `10^3`, a range, `_`, bad groups, `.5`,
   `1e200`, `-1e200`, `inf`, `nan`, `e3`, a trailing dot, spaces). `ours.py` ran the 55d7f087f and
   93d427296 scorers side by side; `theirs.py` (`env -i`, `-I`) ran Futurex-Eval with the same
   scripted judge.
4. `compare.py` results:
   - `L12 new vs 93d427296: 16464, differ 0`; `L12 vs theirs (tokens equal): differ 7` (Case 310).
   - `L34 legacy_type_a` and `L34 unordered_set`, new vs 93d427296: 0 differ (num and other).
   - `L34 legacy_type_b other new vs 93d427296: 0`. `L34 legacy_type_b num_* new vs 93d427296:
     9331, differ 1756`, every one explained: `num_neg_dollar` 294 (1 → 0, sign kept),
     `num_sci`/`num_sci_E` 222 each (0 → 1), `num_frac` 294 and `num_bad_groups` 294 and
     `num_trailing_dot` 294 and `num_underscore` 89 (now judged), `num_bare_e` 13, `num_pow` 2,
     `num_huge` 6 (1 → 0), and `$-x` / `+-x` on negative keys 13 each (now judged).
   - vs theirs with the stand-in extractor: `legacy_type_b num_*` 1,845 (the 1,756 above plus
     `{,}` 89), `legacy_type_a num_*` 1,850 (float-label artefacts of the stand-in),
     `unordered_set num_*` 454 (comma numbers), `legacy_type_b other` 477 (D3 cap 323 + empty box
     154), `unordered_set other` 664 (empty box). No scorer raised.
5. `to_float` table, ours (after the `{,}` rewrite) vs `fork:utils.to_float` on 33 strings: the 15
   differences are `-$5`, `$-5`, `1,23,456`, `2,49`, `1e3`, `1E3`, `2.5e-3`, `5.`, `1/2`, `10^3`,
   `1-2`, `1_000`, `e3`, `1e200`/`1e400`, `1{,}234`; all others are equal. The `number_score` grid
   (`grid_ours.py` vs `grid_theirs.py` through `estimate_score_level_3_4`) gave
   `76 points, differ 0`.
6. `HF_HOME=$SCRATCH/hf-home uv run --extra inspect python prompt_bytes.py` gave
   `samples 2036 | input != prompt: [] | id mismatches: [] | levels {1: 659, 2: 713, 3: 338, 4: 326} | case_count 2036`
   and `sha256 of all inputs 4891c0e5…2855`.
7. Citation greps: `grading.py:85,119,167,172,189,221,232,326,397,438,439,444,463,471`;
   `futurex_past.py:79,87,224,243,297`;
   `benchmarks.py:7950,7973,7979,7981,7982,7984,7986,7988,7997,8000,8003,8038`; README
   `:19,43,45,53,61,70,73,76,77,80,82,83,88,89,91,92,94,96,100,105,107,110,112,116`. Final
   `git status --porcelain` printed nothing; the scratch folder was removed.

Not rerun, because the code is unchanged since 93d427296 or e463be2e9: the judge-reply sheets and
the roll-up vectors. Results are as in the Dimensions table.

## Recommended paid runs

- **None can change the verdict** (D7 and D9 hold by design).
- **Optional, to size D2, D3, D4 and D8.** Record one Candidate run on all 2,036 Cases. Have a
  key-holding owner re-mark the same replies with Futurex-Eval@2626f7a2 under
  `DEEPSEEK_MODEL=deepseek-v4-flash` (about 2,036 extractor calls, 664 router calls and about
  1,000 judge calls), and compare per Case. The extractor's rewrites of non-plain numbers (`1/2`,
  `1,23,456`, `5.`) settle D2's number half. Repeating it with `OPENAI_API_MODEL` set to gpt-5.4
  separates the judge-model effect.

## Upstream notes

- **σ.** The paper's "standard deviation of the outcome over the past 7 days"
  (`paper:sections/approach.tex:481`) vs 5% of the key in the code (`fork:eval.py:248-252`). The
  harness wins. README `:107-109`.
- **Level 2.** The paper describes halving and zeroing (`approach.tex:347`), but its metric is F1
  (`approach.tex:463-466`), and so is the code. README `:110-111`.
- **Missing predictions.** The paper allows misalignment across models (`approach.tex:426-442`);
  the weekly script counts a miss as 0 (`fork:run_weekly_leaderboard.py:126-136`).
- **Ranking.** The harness adds an order-free shortcut for option letters, an `unordered_set`
  route chosen by an LLM router, and no cap on the overlap count. None of these is in the paper
  (`approach.tex:468-476`).
- **"Yes" anywhere.** A match and the rank verdict count as yes if the word appears anywhere in
  the judge's reply (`fork:llm_judge_level_34.py:172`, `:191`). We copy it. README `:112-115`.
- **Harness self-test.** `test_contract_conflict_skips_router` fails at the pin
  (`fork:test_harness.py:38-46`). README `:116-118`.
- **Missing dependency.** The README's install line omits `requests` (imported at
  `fork:llm_judge_level_34.py:1`).
- **Ids.** The harness keys predictions and the route cache by `id`, which recurs in Futurex-Past
  (21 ids over 119 rows).
- **The number helpers.** `utils.is_number` is "starts or ends with a number" and `utils.to_float`
  reads the first numeric run (`fork:utils.py:3-50`). On raw text that turns `1e3` into 1, `-$5`
  into +5, `RvPLegend10` into 10 and `C3.4` into 3.4. An extreme prediction such as 1e200
  overflows `judge_number_overall`, which the worker scores 0.0. These bite only if the extractor
  passes such text through.
- **Answer keys with markup.** 16 keys carry `\boxed{}`: Cases 1216, 1219, 1222, 1225, 1228,
  1230, 1232, 1234, 1237, 1241, 1244, 1247, 1250, 1253, 1255, 1257. In Cases 1230 and 1234 the
  first item has an unclosed `\boxed{`. Both scorers handle them alike. It is a data defect worth
  reporting upstream.
- **inspect_evals.** FutureX is not in inspect_evals 0.20.0; those references record installed
  versions only.

## Since the audit (2026-11-17, OME-1952)

The fingerprint moved from `118a7a5a5df8e185` to `a4593e342d18b512` because the package's
sibling module `futurex_past_study.py` gained the `study_headline` metric (the maintainer's
review), and the fingerprint hashes every `.py` file of the package. No file this Benchmark
grades with changed: `futurex_past.py` and `grading.py` are byte-identical to the audited ones.
