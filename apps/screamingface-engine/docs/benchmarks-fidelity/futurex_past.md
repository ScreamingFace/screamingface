---
benchmark: futurex_past
origin: external
verdict: not-comparable
verdict_reason: "Two by-design differences, each unbounded. First, levels 3-4 are routed, matched and counted by openrouter/openai/gpt-5.4 with our own reworded prompts, where Futurex-Eval judges, routes and extracts with DeepSeek V4 Flash or GPT-4.1 (declared, benchmarks.py:7965-7967); spec §2.3 calls a judge other than the one behind the paper's number not-comparable. Second, the Candidate answers closed-book with one generate() on resolved events, while every published FutureX number comes from search agents on live weekly questions; none exists for this archive (frontier_score NotPublished, benchmarks.py:8009-8014). The one measured enumerable bound is 1/2036 (the [Yes] key). The 24 prompts that do not show the \\boxed{} syntax could cost up to 24/2036 against the Candidate (not measured). One undeclared finding (U8, a failed scoring-question judge call leaves the headline instead of counting 0) is run-dependent and does not move the verdict."
audited: 2026-11-18
audited_at: 2dcc38aaf   # HEAD of branch futurex-past-local-task (PR 1897), not main; reachable from that branch
fingerprint:
  benchmark: 200cf4f72481ffb0
  harness_url: https://github.com/Futurex-ai/Futurex-Eval/tree/2626f7a297cd87c73a45408e23af8d838f5b60e5
references:
  paper: https://arxiv.org/abs/2508.11987v3
  original_harness: https://github.com/Futurex-ai/Futurex-Eval/tree/2626f7a297cd87c73a45408e23af8d838f5b60e5
  inspect_evals: https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0
  inspect_ai: https://github.com/UKGovernmentBEIS/inspect_ai/tree/v0.3.263
parity_test: none
parity_test_reason: "Futurex-Eval publishes no licence, so it cannot be vendored or run in CI, and levels 3-4 are judge-graded. tests/unit/inspect/test_futurex_past_grading.py and tests/unit/inspect/test_local_task_futurex_past.py (160 passed at 2dcc38aaf) pin our re-implementation, not parity. This audit's answer sheets ran the pinned Futurex-Eval beside our scorer offline, with its LLM entry points either unreached (float predictions, scripted router completions) or stubbed (roll-up)."
---

# FutureX-Past — Fidelity Record

## Verdict

**`not-comparable`.** No published number exists for this exam, and two differences hold by design.

- **No reference number.** The FutureX paper and leaderboard score agents **with search** on
  **live** weekly questions (`paper:sections/experiments.tex:4-14`, earlier audit). The dataset
  card says the archive "should not be used to evaluate the live future prediction capabilities of
  LLMs" (`hub:README.md:73`). Our row records the frontier score as `NotPublished`
  (`inspect-pkg:benchmarks.py:8009-8014`).
- **D7, the judge.** Levels 3-4 are routed, matched and counted by `openrouter/openai/gpt-5.4` with
  our reworded prompts (`inspect-pkg:benchmarks.py:7965-7971`). Futurex-Eval uses the model its
  environment configures, DeepSeek V4 Flash by default (`fork:llm_config.py:14-28`,
  `fork:README.md:24`, `:32`).
- **D9, closed-book generation.** We call one `generate()` on resolved events
  (`task:futurex_past.py:299`).

Rule step 1 (spec §2.3) settles the verdict on D7 and D9 alone. The arithmetic for the rest:

- **Measured, enumerable:** D1 = 1/2036 = 0.0005 ≤ 0.005.
- **Enumerable ceiling, not measured:** D11 ≤ 24/2036 = 0.0118 of Cases (≤ 0.0261 of the
  tier-weighted headline), and it only counts against the Candidate.
- **Open, `unknown`:** D2, D3, D4, D8.
- **Run-dependent, 0 on a clean full run:** D5, D6, D10, U8.

No comparable verdict is possible, so the score must not be read beside any FutureX leaderboard
number.

What changed in the scorer since the last record:

- **A failed router call now falls back as Futurex-Eval's does** (match, measured: 7/7 router
  sheets).
- **A prose number keeps its thousands commas** on its way to the judge (still D2; it moves toward
  Futurex-Eval's "is a number" branch and is ≥ its "not a number" branch).
- **The answer-format sentence was checked against the code.** It is page prose, not prompt bytes,
  so it cannot change a mark.

## Dimensions

| dimension | status | severity | bound | evidence |
|---|---|---|---|---|
| dataset | deviation | score-changing | 1/2036 (Case 310, D1) | **Ran:** the real Task through `captured_case_records`. File sha256 `a385ef5e…36bb` equals `DATASET_SHA256` (`task:futurex_past.py:79`). 2,036 Cases, levels `{1: 659, 2: 713, 3: 338, 4: 326}`. The recomputed Case Digest `ea2bcb82…3c63` equals the declared one (`inspect-pkg:prepare.py:2311-2314`). Gold vs the harness parse (`fork:run_single_submission.py:30-39`) with tokens held equal: 13,720 level-1/2 sheets, 7 differ, all Case 310. **Theirs:** no Futurex-Past loader; it reads an `.xlsx` (`fork:run_weekly_leaderboard.py:47`). |
| prompt | match | — | — | **Ran:** every Case captured through the real Task chain. `input != prompt: []`, every input a `str` (no system message), sha256 of all inputs `4891c0e59df3e43a6eb6e1fa0e179a40d914225e58dfa806b73089ad99432855`, equal to every earlier audit's. **Read:** the dataset's `prompt` is "the full prompt that was provided to the LLM agent" (`hub:README.md:81`); the harness uses it as the question (`fork:run_weekly_leaderboard.py:60-63`). 24 of these prompts do not show the box syntax; that affects how the reply is read, so it is D11 under answer extraction. |
| answer extraction | deviation | possibly-score-changing | unknown (D2); ≤ 24/2036 against the Candidate (D11) | **Ours:** the last `\boxed{}` with one level of nesting (`task:grading.py:71`, `:75`). Then `reply_tokens` (`task:grading.py:120`): a whole-box `\text{}` and per-item `\text{}` removed, split on commas. Levels 1-2 at `task:futurex_past.py:225`, levels 3-4 at `task:grading.py:394`. Single-number keys: `{,}` → `,`, then `to_float` reads only a whole plain number (`task:grading.py:168`, `:173`). Otherwise the judge gets the first piece split at a comma that is not inside a number (`task:grading.py:453`, `:464`). **Theirs:** an LLM extractor rewrites the answer and says whether it is a number (`fork:eval.py:73`, `:119`). On "yes", `utils.to_float` runs on the whole rewrite (`fork:eval.py:143-144`, `fork:utils.py:3`); otherwise the answer is split on every comma (`fork:eval.py:145`), and the number judge gets `model_prediction[0]` (`fork:llm_judge_level_34.py:243`). The measured split table is in Checks run (ran). |
| metric | deviation | possibly-score-changing | unknown (D3, D4); run-dependent (U8) | **Ran, levels 1-2:** `label_score` (`task:grading.py:147`) vs `estimate_score_level_1_2` (`fork:eval.py:151`), tokens equal: 13,720 sheets, 7 differ, all Case 310 (D1). **Ran, number score:** `number_score` (`task:grading.py:222`) vs the real `estimate_score_level_3_4` worker (σ at `fork:eval.py:250`, `:252`; `judge_number_overall` at `fork:llm_judge_level_34.py:234`): 71/71 equal. The grid covers keys 0 / 1 / 249.41 / −634500 / 1e-9 / 1e12 / 1846 / −0.5, offsets 0, ±1%, 2.5%, −4.9%, 5.1%, 50%, −100%, the zero-key boundary (0.009, 0.01, −0.0099, 0.011, 0.005) and ±1e200. Upstream raises `OverflowError` on 1e200, and its worker scores 0.0 (`fork:eval.py:260-263`). **Carried from earlier audits:** ranking, set and text marking with one scripted judge differ only by D3 and D2 artefacts; this code (`task:grading.py:434-444`, `:476-507`) is unchanged since 6c0d21a64 (`git diff 6c0d21a64 2dcc38aaf` touches only `_route`, `Graded` and `_number`). |
| roll-up | deviation | score-changing | 0 at full coverage (measured); run-dependent otherwise (D5, D6, D10) | **Ran:** five full vectors through `tier_weighted_mean` (`task:futurex_past.py:261`) and the real `fork:run_weekly_leaderboard.py:main()` (weights `:15`, roll-up `:126-136`), its LLM entry points stubbed to return the vector: all-1 1.0 = 1.0; all-0 0.0 = 0.0; alternating 0.503151 = 0.503151; seeded random 0.488432 = 0.488432; levels-1-2-only 0.475 = 0.475. With level 4 absent, 1.0 vs 0.6 (D5). With 20 Cases absent, 1.0 vs 0.995162 (D6). With 20 bare no-level zeros, ours 1.0 vs upstream's 0.995162 for the same 20 Cases counted 0 (D10). `LEVEL_WEIGHTS` `task:futurex_past.py:87`. |
| judge | deviation | score-changing (by design) | unbounded (D7, D8) | **Ours:** `openrouter/openai/gpt-5.4`, temperature 0, max_tokens 4096, web_search false (`inspect-pkg:benchmarks.py:7968-7971`); three asks and the 4,096 cap declared (`:7951-7953`). **Theirs:** the env-configured model, temperature 0, 5,000 tokens (`fork:llm_judge_level_34.py:30`); 512 for the router and the set count (`fork:metric_router.py:110`, `fork:llm_judge_level_34.py:227`); 2 parse attempts on the router (`fork:metric_router.py:169`). **Ran, router:** `_route` (`task:grading.py:417-431`) vs `route_metric` (`fork:metric_router.py:133`, `except Exception` `:180`) on 7 replies (ConnectionError, TimeoutError, RuntimeError, unreadable, valid set, JSON then prose, fenced JSON) plus a contract conflict: the same route and fallback flag on all 8. Our Score also records why (`ConnectionError`, `JudgeReplyUnparseable`, `contract_conflict`). |
| sampling | deviation | score-changing (by design) | unbounded (D9) | Ours: `solver=generate()` (`task:futurex_past.py:299`); declaration `failure_policy='coverage_declare', interaction='single_shot', attempts=1`; no Candidate temperature or max_tokens on the row (ran, Checks run 2). Theirs: search agents, deep-research models and "Think&Search" LLMs predicting before resolution (`paper:sections/experiments.tex:4-14`, earlier audit); the paper fixes no decoding parameters. |

## Deviations

Ten declared deviations carry over (D1-D10), one declared deviation is new (D11) and one finding
is undeclared (U8).

### D1 — the key `[Yes]` is read as `["Yes"]` (Case 310)
- **Declared.** `inspect-pkg:benchmarks.py:7946`; `task:futurex_past.py:96-98`; README `task:README.md:86`.
- **Severity / bound.** `score-changing`, `1/2036 = 0.0005`, measured. Case 310, id
  `69c527154b6f01005cae131a|2026-04-03`, level 1. All 7 differing sheets are this Case
  (ours 1.0, theirs 0.0).

### D2 — the answer is read by rule, not by an LLM extractor
- **Declared.** `inspect-pkg:benchmarks.py:7944-7945` and `:7954-7955`; README `task:README.md:65`, `:80-85`, `:87-88`.
- **What differs.**
  - A boxless reply always scores 0 with us; their extractor can find an answer in it.
  - For a single-number key, our `to_float` (`task:grading.py:173-190`) accepts only a whole plain
    number. Upstream's `utils.to_float` (`fork:utils.py:3-27`) reads the first numeric run, but
    only after its extractor has said "is a number" (`fork:eval.py:143-144`). The 33-string
    `to_float` table and its 15 differences are unchanged since 6c0d21a64 (`to_float` and
    `_PLAIN_NUMBER` are byte-identical); carried from the earlier audit.
  - **The thousands-safe split, new since the last record** (`task:grading.py:453`, `:464`).
    Prose now reaches our number judge cut at the first comma that is not followed by exactly
    three digits. Measured on 16 strings (ran):

    | box text | ours now | ours at 6c0d21a64 | theirs, extractor says "number" (`to_float` on the text as written) | theirs, extractor says "not a number" (first comma piece) |
    |---|---|---|---|---|
    | `12,500 points` | judge `12,500 points` | judge `12` | `None` | judge `12` |
    | `3,000,000 units` | judge `3,000,000 units` | judge `3` | `None` | judge `3` |
    | `roughly 1,846 cases` | judge `roughly 1,846 cases` | judge `roughly 1` | `None` | judge `roughly 1` |
    | `-$634,500 loss` | judge `-$634,500 loss` | judge `-$634` | `None` | judge `-$634` |
    | `US$ 12,500` | judge `US$ 12,500` | judge `US$ 12` | `None` | judge `US$ 12` |
    | `1,846, maybe 1,900` | judge `1,846` | judge `1` | `None` | judge `1` |
    | `, 500` | judge `` (empty) | judge `500` | `None` | judge `` (empty) |
    | `about 249.41, or 498.82`, `1,2,3`, `2,49`, `1,23,456`, `2020,2021,2022`, `5,0000 units`, `between 4.0 and 4.6`, `12500 points` | unchanged from 6c0d21a64 | | | |
    | `12,500` | rule 12500 | rule 12500 | 12500 | judge `12` |

    **Verdict on this change: score-changing, inside D2, not cosmetic and not a match.**
    - **Against our old rule:** it can only raise the mark of a reply whose number carries
      thousands commas, unless the key happens to equal the leading digits.
    - **Against Futurex-Eval:** the extractor's job is to rewrite the answer (`$115` → `yes`,
      `fork:eval.py:73`). When it rewrites `12,500 points` to `12,500` and says "number", upstream
      reads 12500 and we agree. When it says "not a number", upstream judges `12` and scores 0; we
      score 1. When it keeps the prose and says "number", `to_float` returns `None` on the internal
      space (`fork:utils.py:38-39`); `None` then goes to the number judge as the string `None`.
    - **Direction:** toward the Candidate (ours ≥ upstream) on these replies.
    - **One reversal:** `, 500` now gives the judge an empty string where the old rule gave `500`,
      and that equals upstream's "not a number" branch.
- **Severity / bound.** `possibly-score-changing`, `unknown`; it needs the real extractor's
  rewrites (Recommended paid runs).

### D3 — the rank overlap count is capped at k
- **Declared.** `inspect-pkg:benchmarks.py:7949-7950`; README `task:README.md:96`; `task:grading.py:490-491`.
- **Severity / bound.** `possibly-score-changing`, `unknown`. Theirs is uncapped
  (`fork:llm_judge_level_34.py:197`).

### D4 — an unreadable judge reply fails the Case (it leaves the denominator)
- **Declared.** `inspect-pkg:benchmarks.py:7949-7950`; README `task:README.md:89-93`.
- **Severity / bound.** `possibly-score-changing`, `unknown`. Theirs scores it 0.0
  (`fork:eval.py:260-263`; for a set, `fork:llm_judge_level_34.py:228-230`). The router keeps the
  fallback (see judge row), so this now applies only to scoring questions.

### D5 — a level absent from a run renormalises the weights
- **Declared.** `inspect-pkg:benchmarks.py:7947-7948`; `task:futurex_past.py:264-267`; README `task:README.md:97-98`.
- **Severity / bound.** `score-changing`, `0` on a full run. Measured: 1.0 vs 0.6 with level 4 absent.

### D6 — `coverage_declare`: a failed Candidate call leaves the headline
- **Declared.** `inspect-pkg:benchmarks.py:7935-7938`; README `task:README.md:101-104`.
- **Severity / bound.** `score-changing`, `0` at full coverage; run-dependent otherwise. Measured:
  1.0 vs 0.995162 with 20 Cases absent. Theirs counts a miss as 0
  (`fork:run_weekly_leaderboard.py:126-136`).

### D7 — the judge model, its prompt wording, token caps and router asks
- **Declared.** `inspect-pkg:benchmarks.py:7965-7967`, `:7951-7953`; README `task:README.md:74-75`, `:79`, `:94-95`.
- **Severity / bound.** `score-changing` by design, `unbounded`.

### D8 — the route is not cached across runs
- **Declared.** README `task:README.md:99-100`.
- **What the audit added (ran).** Upstream caches a fallback route too (`fork:metric_router.py:186-187`).
  When the router call raised ConnectionError, then answered `unordered_set` on the next call for
  the same question, upstream returned the cached `legacy_type_b` fallback both times. Ours routes
  again on every run, so a transient router failure affects one run here and every later
  submission there.
- **Severity / bound.** `possibly-score-changing`, `unknown`.

### D9 — closed-book, one generation, resolved events
- **Declared.** README `task:README.md:17-21`; `inspect-pkg:benchmarks.py:7926-7928`; spec §5.
- **Severity / bound.** `score-changing` by design, `unbounded`.

### D10 — an abstained Case whose grading failed leaves the headline
- **Declared.** `inspect-pkg:benchmarks.py:7956-7957`; README `task:README.md:105-108`; `task:futurex_past.py:245-258`.
- **Severity / bound.** `score-changing`, run-dependent; 0 unless an abstained Case's grading
  fails. Measured: 1.0 vs 0.995162 with 20 such Cases.

### D11 — 24 prompts ask for a boxed value without showing `\boxed{}`
- **Declared.** README `task:README.md:38-43`.
- **What differs.**
  - **Ran:** 2,012 of 2,036 prompts at `8299bfa1` contain a literal `\boxed{`. The other 24 are
    10 at level 3 and 14 at level 4: Cases 1261, 1264, 1267, 1268, 1269, 1271, 1272, 1275, 1276,
    1280, 1283, 1285, 1286, 1288, 1296, 1297, 1303, 1308, 1309, 1314, 1325, 1326, 1327, 1328.
  - 21 of them say "MUST end with exactly one boxed numeric value".
  - Cases 1285 and 1327 say "boxed answer following the requested format", and Case 1288 says
    "boxed answer following the requested list format". The README's "say only … boxed numeric
    value" is therefore exact for 21 of the 24.
  - Our reader needs a literal `\boxed{` (`task:grading.py:71`). A reply that boxes another way
    (`\fbox{}`, `[1846]`, `**1846**`) scores 0. Futurex-Eval's LLM extractor reads the whole reply
    and can score it.
  - **Direction: against the Candidate only.**
  - This audit's count equals the maintainer's 2026-11-18 measurement (2,012 / 24 / 10 + 14).
- **Severity / bound.** `possibly-score-changing`. The bound is at most 24/2036 = 0.0118 of Cases,
  and at most 3/338 + 5.6/326 = 0.0261 of the tier-weighted headline. How much of that is realised
  depends on how a Candidate boxes, so it is unknown without replies.

### U8 (undeclared) — a failed scoring-question judge call fails the Case
- **Where.** A judge call for a match, rank, overlap, number or set question that still fails after
  `judge_until_parsed`'s two retries of a temporary fault (`inspect-pkg:judge_redraw.py:182-191`)
  propagates out of the scorer. The adapter names it `scorer_error`
  (`inspect-pkg:scorer_adapter.py:980`), and under `coverage_declare` the Case leaves the headline.
  Only a code comment says so (`task:grading.py:429-430`). The row (`:7949-7950`) and the README
  (`task:README.md:89-93`, `:101-104`) declare only an unreadable reply and a failed Candidate call.
- **Theirs.** `get_ai_response` swallows every error and returns `None` after 3 attempts
  (`fork:llm_judge_level_34.py:83-87`). The next `'yes' in ans.lower()` raises, and the worker
  scores 0.0 (`fork:eval.py:260-263`); a set question reads `response or ""` and scores 0.0
  (`fork:llm_judge_level_34.py:228-230`).
- **Severity / bound.** `score-changing`, run-dependent, 0 when every judge call answers. When it
  fires, ours ≥ upstream, because the Case is excluded instead of counted 0. Read, not run; earlier
  records filed this under D4. Fix options: declare it beside D4, or catch it and score 0.

### Resolved findings (kept for the trail)

The "resolved in" column gives the reachable commit where the code comment naming the fix first
appears (`git log -S`). The earlier record's hashes (`c8dadab6c`, `e463be2e9`, `abb05ea9b`,
`93d427296`, `55d7f087f`) are not reachable from this branch.

| finding | first seen | resolved in | evidence |
|---|---|---|---|
| U1: a whole-box `\text{}` at levels 1-2 | first audit | c7af5cdb8 | levels 1-2 vs upstream: Case 310 only (ran) |
| U2: a prose number judged on the whole box | first audit | 2bf89e618 | `task:grading.py:464` |
| U3: unsorted option letters reach the rank judge | first audit | 2bf89e618 | `task:grading.py:480-486` |
| U4: a lenient router parser | first audit | 2bf89e618 | `task:grading.py:327`; router sheets 7/7 (ran) |
| U5: token caps and the router's ask count | first audit | declared, 2bf89e618 | `inspect-pkg:benchmarks.py:7951-7953` |
| U6: a no-level Case dropped | second audit | declared, c7af5cdb8 | D10 |
| U7: per-option `\text{}` misread | second audit | c7af5cdb8 | `task:grading.py:120` |
| R1: a failed router call failed the Case | review on PR 1897 | 922548af9 | `task:grading.py:422-431`; router sheets (ran) |
| R2: `12,500 points` reached the judge as `12` | review on PR 1897 | 922548af9 | D2 table (ran) |

## Checks run

- [x] **Read-only on the checkout.** `git status --porcelain` was empty before the audit. At the
  end it showed ` M apps/screamingface-engine/docs/benchmarks-fidelity/futurex_past_study.md`,
  last modified 2026-11-18 16:32:51 (ICT), two minutes before the check. No command in this audit
  writes under the worktree: that edit is the maintainer's session saving the sibling record
  from its own re-audit (confirmed by the maintainer), and it was left untouched.
  The scratch folder (session scratchpad `…/fxaudit`) could not be removed, because the session's
  safety hook blocks `rm -rf`; it holds only downloads and scripts.
- [x] **No keys, no model.** `env -i PATH="$PATH" HOME="$SCRATCH" UV_CACHE_DIR="$SCRATCH/uv-cache" env | grep -iE 'key|token|secret'`
  printed nothing (`grep exit=1`). The calling shell holds key-named variables, so every command
  ran under `env -i`.
  - Futurex-Eval ran under the exact prefix with `python -I`.
  - Our Engine ran under `env -i PATH HOME=$SCRATCH UV_CACHE_DIR=~/.cache/uv UV_PYTHON_INSTALL_DIR=~/.local/share/uv/python HF_HOME=$SCRATCH/hf-home`.
    That reuses the uv cache instead of downloading again; no variable with a key reaches it.
  - No model, gateway or provider was called. The router sheets used scripted completions; the
    number grid used float predictions, which never reach the judge; the roll-up stubbed
    `extract_answers`, `prewarm_metric_routes` and `estimate_routed_scores`.
- [x] **Harness over paper.** See Upstream notes.
- [x] **Declared is not a finding.** D1-D11 are declared. U8 is undeclared.
- [x] **Every cell has evidence.** Each row says whether its evidence was ran, read, or carried
  from an earlier audit.
- [x] **Every `file:line` is copied from command output.** Ours: `grep -n` at 2dcc38aaf on
  `grading.py`, `futurex_past.py`, `README.md`, `benchmarks.py` (lines 7913-8016), `_judged.py`,
  `prepare.py`, `judge_redraw.py`, `scorer_adapter.py` and `test_benchmark_fingerprints.py`.
  `fork:` lines come from `cat -n` and `grep -n` on each file fetched at the pin with
  `gh api "repos/Futurex-ai/Futurex-Eval/contents/<file>?ref=2626f7a2…" --jq .content | base64 -d`.
  `hub:` lines come from `grep -n` on the card fetched at `8299bfa1`. `paper:` and `site:` lines
  are carried from the earlier audits and were not re-read.
- [x] **Every citation names its tree.** Each prefix below is defined once:
  - `task:` is `apps/screamingface-engine/src/screamingface_engine_inspect/local_tasks/futurex_past/` at 2dcc38aaf.
  - `inspect-pkg:` is `apps/screamingface-engine/src/screamingface_engine_inspect/` at 2dcc38aaf.
  - `fork:` is [Futurex-ai/Futurex-Eval@2626f7a2](https://github.com/Futurex-ai/Futurex-Eval/tree/2626f7a297cd87c73a45408e23af8d838f5b60e5).
  - `hub:` is [futurex-ai/Futurex-Past@8299bfa1](https://huggingface.co/datasets/futurex-ai/Futurex-Past/tree/8299bfa1609dec30f267891a74d76e62902c9d71).
  - `paper:` is the [arXiv 2508.11987v3](https://arxiv.org/abs/2508.11987v3) e-print source.
  - `site:` is [Futurex-ai/Futurex-ai.github.io@35e5bc2b](https://github.com/Futurex-ai/Futurex-ai.github.io/tree/35e5bc2bc2b9cee2255ccafba4e23d92c932d52b).
- [x] **A verdict never claims more than its evidence.** No dimension is `unchecked`. The verdict
  rests on D7 and D9 (rule step 1), and the open items are listed with their bounds.
- **Authors' recorded replies.** None, carried from the earlier audits. They searched the
  `futurex-ai` Hugging Face organisation, the `Futurex-ai` GitHub organisation and
  `site:src/data/leaderboard.json`, which holds aggregates only. Not re-searched here.

**What this audit ran**, in order:

1. **Checkout state.** `git rev-parse --short HEAD` gave `2dcc38aaf`; `git status --porcelain`
   printed nothing.
   - `git diff 6c0d21a64 2dcc38aaf -- task:grading.py task:futurex_past.py` touches only
     `Graded.route_fallback_why`, `_route` (`except JudgeReplyUnparseable` → `except Exception`),
     `_THOUSANDS_SAFE_COMMA` and `_number` in `grading.py`, plus one comment and the
     `route_fallback_why` metadata key in `futurex_past.py`.
2. **Tests and declaration.**
   - `uv run --isolated --extra inspect pytest tests/unit/inspect/test_futurex_past_grading.py tests/unit/inspect/test_local_task_futurex_past.py --no-cov -q -p no:cacheprovider`
     gave `160 passed`.
   - `imported_benchmark("futurex_past")` gave `fingerprint 5b47c8f485e6716f revision 5b47c8f485e6716f`.
     The fingerprint is computed. It equals the literal at
     `apps/screamingface-engine/tests/unit/inspect/test_benchmark_fingerprints.py:170`, and it
     also equals `published_revision` (`inspect-pkg:benchmarks.py:7915`), which the branch sets to
     match.
   - The same call gave `origin external`, `harness_url` byte-equal to the front matter,
     `BenchmarkDeclaration(failure_policy='coverage_declare', interaction='single_shot', difficulty='hard', attempts=1)`,
     and `JudgeSpec(model='openrouter/openai/gpt-5.4', params=(('temperature','0'),('max_tokens','4096'),('web_search','false')), …)`.
   - Installed versions: inspect_ai 0.3.263, inspect_evals 0.20.0.
3. **Harness setup.** Files fetched by `gh api` at the pin, then `uv venv --python 3.12` and
   `uv pip install openai tenacity diskcache pandas openpyxl pyarrow requests` under the `env -i`
   prefix. The earlier record's grading was taken with `git show 6c0d21a64:…/grading.py`.
4. **Dataset and prompt.** `captured_case_records(futurex_past(), TASK_REPLAY_CASES["futurex_past"])` gave:
   - `file sha256 a385ef5e…36bb`
   - `cases 2036 case_digest ea2bcb82…3c63 declared ea2bcb82…3c63`
   - `input != prompt: []`, `non-str inputs: []`
   - `levels {1: 659, 2: 713, 3: 338, 4: 326}`
   - `prompts with literal \boxed{: 2012 without: 24`, `without, by level {4: 14, 3: 10}`, and
     21 of the 24 with the exact "boxed numeric value" phrase
   - `inputs sha256 4891c0e5…2855`
5. **Answer sheets, levels 1-2.** 13,720 sheets, 10 per Case: plain, whole `\text{}`, per-item
   `\text{}`, lower-case, reversed, wrong, empty, first only, plus a wrong item, and a
   reasoned-then-final reply. Ours: `label_score(gold, reply_tokens(last_boxed(reply)))`. Theirs:
   `estimate_score_level_1_2` on `parse_ground_truth(raw)` with the same tokens. Result:
   `differ 7`, all Case 310. A first pass with a hand-written stand-in extractor showed 97 more
   differences on per-item `\text{}`. Its greedy `\text{(.*)}` strip was wrong, so the
   tokens-equal pass is the measurement.
6. **Number grid.** 71 points: `number_score` vs the real `estimate_score_level_3_4`, `differ 0`.
7. **Number prose.** 16 strings through the head and 6c0d21a64 `_number` split, and through
   `utils.to_float` and the comma split (the D2 table).
8. **Router.** 7 scripted replies plus one contract conflict through `_route` and `route_metric`.
   Routes and fallbacks are equal on all 8. Upstream reused a cached fallback after a later valid
   reply (D8).
9. **Roll-up.** The vectors and results in the roll-up row, through `tier_weighted_mean` and the
   real `run_weekly_leaderboard.main()`. Synthetic unique ids were used, because upstream keys by
   `id`, which recurs.
10. **Answer-format sentence** (`inspect-pkg:answer_formats/_judged.py:217-227`), checked against
    the code. Each claim matches:
    - "the last `\boxed{}`" (`task:grading.py:75`);
    - "within about 5% … within 0.01 when the true value is 0", since `number_score` is positive
      only when |ŷ − y| < σ, with σ = 0.05·y or 0.01 (`task:grading.py:229-233`);
    - "0.8 of its overlap" (`task:grading.py:491`, `:507`).

    The sentence is appended to the Benchmark page (`inspect-pkg:answer_formats/__init__.py`
    docstring, Stage 2). The captured prompt bytes equal the dataset's (step 4), so it never
    reaches the Candidate: cosmetic, bound 0.

**What this audit read but did not run.** U8's path (`judge_redraw.py`, `scorer_adapter.py`,
`fork:llm_judge_level_34.py:83-87`), and the extractor's retry and submission-zeroing path (Upstream
notes).

**Carried from earlier audits, not rerun.**
- The 33-string `to_float` table (`to_float` unchanged).
- The level-3/4 scripted-judge sheets for ranking, set and text (code unchanged).
- The judge-reply parsers for count, number and match (unchanged).
- The paper and site citations, and the recorded-replies search.

**Reported by the maintainer.** The 24-prompt count (2026-11-18), re-measured equal here.

**Fingerprint history.**
- `118a7a5a5df8e185`: first audits.
- `a4593e342d18b512`: `futurex_past_study.py` gained `study_headline`.
- `5b47c8f485e6716f`: this record, at 2dcc38aaf.

## Recommended paid runs

- **None can change the verdict.** D7 and D9 hold by design.
- **Optional, to size D2, D3, D4, D8, D11 and U8.**
  - Record one Candidate run on all 2,036 Cases.
  - Have a key-holding owner re-mark the same replies with Futurex-Eval@2626f7a2 under
    `DEEPSEEK_MODEL=deepseek-v4-flash`. That is about 2,036 extractor calls, 664 router calls and
    about 1,000 judge calls.
  - Compare per Case. The extractor's rewrites settle D2, including the thousands-comma branch.
  - Count boxless replies on the 24 D11 Cases, and judge-call failures for U8.
  - Repeat with `OPENAI_API_MODEL` set to gpt-5.4 to separate the judge-model effect.

## Upstream notes

- **σ.** The paper defines σ as the outcome's standard deviation over the past 7 days
  (`paper:sections/approach.tex:481`, earlier audit). The code uses 5% of the key (`fork:eval.py:250`,
  `:252`). The harness wins. README `task:README.md:112-114`.
- **Level 2.** The tier description halves and zeroes; the metric is F1 (`approach.tex:347`,
  `:463-466`, earlier audit), and so is the code (`fork:eval.py:151`). README `task:README.md:115-116`.
- **Missing predictions.** The paper allows misalignment across models (`approach.tex:426-442`,
  earlier audit; the row cites §3.4.2). The weekly script counts a miss as 0
  (`fork:run_weekly_leaderboard.py:126-136`).
- **Ranking.** The harness adds an order-free shortcut for option letters, an `unordered_set` route
  chosen by an LLM router, and no cap on the overlap count. None of these is in the paper
  (`approach.tex:468-476`, earlier audit).
- **"Yes" anywhere.** A match and the rank verdict count as yes if the word appears anywhere in the
  judge's reply (`fork:llm_judge_level_34.py:172`, `:191`). We copy it. README `task:README.md:117-120`.
- **Cached fallbacks (ran).** A router failure is cached as the fallback route in memory and on disk
  (`fork:metric_router.py:186-187`). One transient error therefore fixes that question's route for
  every later submission scored from the same cache.
- **Extractor failure zeroes a submission (read).** `extract_by_gpt` retries 4 times
  (`fork:eval.py:75`), then raises out of `extract_answers`. `main()` then records the whole
  submission at 0.0 (`fork:run_weekly_leaderboard.py:164-184`).
- **The number helpers.** `utils.is_number` refuses any string with an internal space
  (`fork:utils.py:38-39`), and `utils.to_float` reads the first numeric run (`fork:utils.py:3-27`).
  - A prediction the extractor marks as a number but keeps as prose (`12,500 points`) reaches the
    number judge as the string `None`.
  - On raw text, `1,2,3` reads as 123 and `2020,2021,2022` as 202020212022 (ran).
  - 1e200 overflows `judge_number_overall`, and the worker scores it 0.0 (ran).
- **Harness self-test.** `test_contract_conflict_skips_router` fails at the pin (earlier audit).
  README `task:README.md:121-123`.
- **Missing dependency.** The README's install line omits `requests` (`fork:README.md:16`), which
  is imported at `fork:llm_judge_level_34.py:1`.
- **Ids.** The harness keys predictions and the route cache by `id`, which recurs in Futurex-Past
  (21 ids over 119 rows, earlier audit; `task:futurex_past.py:125-127`).
- **Answer keys with markup.** 16 keys carry `\boxed{}`, two with an unclosed `\boxed{`
  (Cases 1230, 1234). Both scorers handle them alike (earlier audit). This is a data defect worth
  reporting upstream.
- **Prompts without the box syntax.** 24 prompts (D11) ask for a boxed value without showing
  `\boxed{}`. The authors' LLM extractor makes this harmless for them; it is a data quirk only for
  a rule-based reader.
- **inspect_evals.** FutureX is not in inspect_evals 0.20.0. Those references record installed
  versions only.

## Since the audit (2026-11-18, OME-1952)

The fingerprint moved from `5b47c8f485e6716f` to `200cf4f72481ffb0` after the audit at `2dcc38aaf`, because three
things the audit itself pointed out were fixed in the package the fingerprint covers. None
changes how a reply is read or marked, so the findings above stand:

- `grading.py` lost a stale header comment and its file-level pyright directive (it no longer
  imports the inspect extra's packages).
- The README names the three prompts that ask for a "boxed answer" rather than a "boxed numeric
  value" (Cases 1285, 1288, 1327).
- The row and the README now declare that a judge call on a marking question that still fails
  after its retries fails the Case as `scorer_error`, where Futurex-Eval scores it 0. That is the finding
  U8 above, which is therefore declared now (`benchmarks.py`, the row's `# NAMED DEVIATION` lines;
  `README.md`, beside the unreadable-reply rule).
