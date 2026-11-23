---
benchmark: btf3
origin: screamingface
verdict: not-comparable
verdict_reason: "The paper's BTF-3 numbers (Diverse by Reasoning, arXiv 2608.24001v2) are over its 100-question sample; this Benchmark runs all 1,515 binary questions at the same commit, a declared Named Deviation whose bound, 1,415/1,515, is far above tolerance. Against the paper's own harness (the contributor's study code) everything deterministic matches except one declared change, the reworded answer line (D5): above that line the prompt is the study's byte for byte on 100 of 100 study Cases; the reply reader byte for byte, the per-Case accuracy and Brier on all 2,700 recorded study answers, and the per-model headlines to 0. One undeclared deviation: a single reply with no readable probability is scored as a miss with Brier 0.25, where the study drops such a cell from both sides of the fraction. Temperature 0 and re-asking a cut-off reply are declared and not applied by the Engine."
audited: 2026-11-17
audited_at: d5c8007b3
fingerprint:
  benchmark: 1c1d7973a6094bf4
  harness_url: https://huggingface.co/datasets/futuresearch-ai/BTF-3/tree/ad5a2165eea26a8a43592ba36ff15765199ddc71
references:
  paper: https://arxiv.org/abs/2608.24001v2
  original_harness: https://huggingface.co/datasets/futuresearch-ai/BTF-3/tree/ad5a2165eea26a8a43592ba36ff15765199ddc71
  inspect_evals: https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0
  inspect_ai: https://github.com/UKGovernmentBEIS/inspect_ai/tree/v0.3.263
parity_test: none
parity_test_reason: "The paper's harness is the contributor's study code, which is local and unversioned (no URL to pin; references.original_harness therefore stays the dataset at the pin, as the row's harness_url). tests/unit/inspect/test_local_task_btf3.py (33 passed) pins our side: the template's sha256, and that putting the study's answer line back gives btf_render(forecast_prompts.BTF, 'tight'), the vendored reader's sha256, and the mark and headline. The cross-check against the study code (100 prompts, 15,150 answer sheets, 2,700 recorded answers, roll-up vectors) is in this record's Checks run."
---

# BTF-3 (yes/no forecasting) — Fidelity Record

> Audited against the **uncommitted working tree** of branch `btf3-local-task` at HEAD `d5c8007b3`
> (base `origin/main` `ce6b73839`), after the redesign to ScreamingFace/screamingface#1868
> (OME-1938). The reference is now the paper the issue names, *Diverse by Reasoning*
> (arXiv 2608.24001), and the code that produced its BTF-3 numbers. The FutureSearch leaderboard is
> a secondary note only. This record replaces the earlier one, which audited against Bench to the
> Future's native setup.

## Verdict

**`not-comparable`.** The paper reports BTF-3 accuracy at 0.5 over a 100-question sample
(`arxiv:v2/main.tex:577`, `:613`, `:623-624`). This Benchmark serves all 1,515 binary questions at
the paper's commit. That is declared (README `:99-100`, row `benchmarks.py:7935-7936`), but no
published number exists over these 1,515 Cases.

`bound vs the paper's runs = D1 1,415/1,515 = 0.934 > 0.005 → not-comparable`

Open items, which cannot change the verdict: D2 temperature (declared, `unknown`), D3 no re-ask on
a cut-off reply (declared, `unknown`), D4 no-forecast handling (**undeclared**, bound per run =
`no_forecast`/1,515), D5 the reworded answer line (declared 2026-11-18, `unknown`).

**What matches, with evidence:**
- **The prompt, above the answer line.** With the study's answer line put back,
  `PROMPT_TEMPLATE` equals `btf_render(forecast_prompts.BTF, "tight")`: 3,325 bytes, sha256
  `1b539749…`. For all 100 study Cases, that input equals what the study runner sent
  (`study:1_forecasting_prompts/run_openrouter.py:807`). As served, the template is 3,386 bytes,
  sha256 `62f19370…`, and differs only in its answer line (D5).
- **The reader.** `vendor/study_btf_parse.py` is byte-identical to
  `study:1_forecasting_prompts/bench_formats.py:121-158`.
- **The mark.** Accuracy `f >= 0.5` and Brier `(f - y)^2` match the study on every sheet where the
  study yields a forecast: 10,605 of 10,605. They also match on all 2,700 recorded study answers
  (27 models × 100).
- **The headline.** Per-model accuracy and Brier over the recorded answers equal
  `rank.score_entry`'s to `0.00e+00`.
- **The dataset.** The pin is the study's commit. All 100 study questions are in it, and their
  gold is equal.

## Dimensions

| dimension | status | severity | bound | evidence |
|---|---|---|---|---|
| dataset | deviation | score-changing | 1,415/1,515 vs the paper's sample (D1, declared); `0` vs the paper's commit | Pinned parquet at `ad5a2165`: sha256 `50f01603…` = `DATASET_SHA256` (`local_tasks/btf3/btf3.py:70`). 1,515 rows, `{0.0: 1014, 1.0: 501}`, 1,515 unique ids. Case Digest and Case Set digest recomputed from the file through `prepared_case`: both equal `prepare.py:2314-2315` at the audit (`2110d3d3…`, `07269005…`; after D5 the importer recomputed `3381b20d…`, `06ad754d…`, since every Case's input changed). The study's 100 (`study:1_forecasting_prompts/questions/btf3_100.json`, `item_id = "btf3-" + question_id`): 100/100 in the pin, 0 missing, gold 100/100 equal, 72 No / 28 Yes (Checks 3, 4). |
| prompt | deviation | possibly-score-changing | `unknown` (D5, declared) | Amended 2026-11-18: the answer line is reworded (D5); the evidence below holds with the study's line put back (`test_swapping_the_study_line_back_gives_the_studys_prompt_as_sent`). `PROMPT_TEMPLATE` (`btf3.py:79-138`) vs `study:bench_formats.btf_render(forecast_prompts.BTF, "tight")` (`study:1_forecasting_prompts/bench_formats.py:104-117`, `BTF_TIGHT` `:100-101`): `EQUAL`, both 3,325 bytes, sha256 `1b5397496e04fb7aa35c00c6214d127da6c827ef042b081a8c40c14aa0ac9d9e`, the value pinned at `tests/unit/inspect/test_local_task_btf3.py:126`. Our input for each of the 100 study Cases == `btf_render(stored prompt, "tight")`, which is what the runner sent (`run_openrouter.py:807`): 100/100. Each stored prompt == `forecast_prompts.BTF` filled with the row and `present_date[:10]`: 100/100 (Checks 3). The only braces in the template are the four placeholders. One user message, no system message, `generate()` (`btf3.py:343`). |
| answer extraction | match | — | 0 | `local_tasks/btf3/vendor/study_btf_parse.py:17-54` vs `study:1_forecasting_prompts/bench_formats.py:121-158`: `diff` → identical, sha256 `0e263b1c…` (= `test_local_task_btf3.py:216`). The study reads each reply with it at `run_openrouter.py:885` (and `study:1_forecasting_prompts/README.md:21`). Not traceable: the export kept only settled answers, not raw replies (`study:3_results_report/build_data.py:8`). The study also holds an LLM answer recoverer for non-compliant replies (`study:1_forecasting_prompts/answer_extractor.py:1-17`). Whether any of the 2,700 settled answers came from it cannot be checked from the package. |
| metric | match | — | 0 | Ours: `btf3.py:262-267` (`(f >= 0.5) == outcome`, Brier `(f - y)^2`), constants `:249-250`. Theirs: `study:3_results_report/committee_kit/metrics.py:40-41, 49-51`, and the paper, `arxiv:v2/main.tex:623-624` ("$p \geq 0.5$ yes"). Answer sheets: 0 differing marks on the 10,605 sheets where the study yields a forecast. On the 4,545 where it yields none, the mark differs by roll-up (D4). Recorded study answers: 2,700/2,700 per-Case marks equal (Checks 6). |
| roll-up | deviation | score-changing | `no_forecast`/1,515 per run (D4, **undeclared**); 0 on the study's corpus | Ours: `btf3_headline` (`btf3.py:314-323`), with every Case in both means. Theirs: `rank.score_entry` (`study:3_results_report/committee_kit/rank.py:159-173`), which drops a no-response item from both sides (`:167`), then `metrics.btf3_scores` (`metrics.py:122-135`). Vectors (ours / study, acc and Brier): all 0.5 `0.3307/0.3307`, `0.2500/0.2500`; always 0.1 `0.6693/0.6693`; perfect `1/1`; all wrong `0/0`; random `0.4977/0.4977`, `0.3375/0.3375`. **random with 146 no-forecast replies: acc `0.4455` vs `0.4931`, Brier `0.3294` vs `0.3378`** (D4). The 27 models' recorded answers: max \|Δacc\| = max \|Δbrier\| = `0.00e+00` (Checks 6). A failed call (no reply) leaves the denominator in both: `coverage_declare` (`benchmarks.py:7926`) and `NO_RESPONSE` (`rank.py:80-81`). |
| judge | not applicable | — | — | `imported_benchmark("btf3").judge` → `None` (Checks 2). |
| sampling | deviation | possibly-score-changing | `unknown` (D2, D3, declared) | One call per Case, `generate()` with the Candidate's settings (`btf3.py:336-343`). The study: temperature 0 (`study:1_forecasting_prompts/llm_api.py:341`, `run_umbc.py:83`), with the token cap doubled until a reply is not cut off (`run_openrouter.py:341`). The paper itself leaves sampling as a TODO (`arxiv:v2/main.tex:535-536`). One settled answer per (model, question) (`study:3_results_report/data/PROVENANCE.md:8`) matches one run per Case. |

## Deviations

### D1 — all 1,515 questions, not the paper's 100-question sample

- **Declared.** README `:99-100`, row `benchmarks.py:7935-7936`, spec `:163-164`.
- **What differs.** The paper's 100 were drawn in two stages, balanced by outcome (72 No / 28 Yes against
  1,014 / 501 in the pin). The first draw's seed `20260808` is at
  `study:1_forecasting_prompts/manifest.py:35`. The second seed, `20260815`, appears only in the
  contributor's reply, not in the code.
- **Severity and bound.** Score-changing, 1,415/1,515. This sets the verdict.
- **Note.** The 100 are a subset of our Cases with byte-identical prompts. A run's per-Case Scores on those
  ids are directly comparable with the study's per-model answers.

### D2 — temperature 0 not applied

- **Declared.** README `:101-103`, row `:7936-7937` and `:7916-7917`, `btf3.py:336-339`, spec `:161-162`.
- **What differs.** The study sends `temperature=0.0` on every path. The Engine applies no Task config, so the
  Candidate's own setting stands, and the README tells users to set 0.
- **Severity and bound.** Possibly-score-changing, `unknown`.

### D3 — a cut-off reply is not re-asked

- **Declared.** README `:104-106`, spec `:164`. **Not** listed in the row's `# NAMED DEVIATIONS`
  (`benchmarks.py:7935-7938`), which names only the other three.
- **What differs.** The study doubled the token cap until the reply was complete
  (`run_openrouter.py:341`). Where a cell had several records, it kept the complete, interpretable
  one (`PROVENANCE.md:8`). Here a cut-off reply is read as it stands.
- **Severity and bound.** Possibly-score-changing, `unknown`. It feeds D4: a cut-off reply often has no
  forecast.

### D4 — a reply with no readable probability: a miss here, dropped in the study (undeclared)

- **Where.** Ours: `btf3.py:262-264` (0, Brier 0.25) and `:315-319` (kept in both means). Theirs:
  - A single model's unreadable cell is dropped at the PARSE stage (`study:3_results_report/committee_kit/corpus.py:13, 109-111`).
  - The cell then becomes `NO_RESPONSE`, which covers "an API failure, a refusal, an unparseable reply" (`rank.py:80-81`).
  - `NO_RESPONSE` is dropped from both sides (`rank.py:167`).
  - The paper says the same: a cell "when a model returned nothing interpretable … is dropped from both sides of the score rather than counted as wrong" (`arxiv:v2/main.tex:631-633`).
  - The study's miss with Brier 0.25 (`metrics.py:41, 127-129`) applies to a *crowd* that answered but reached no decision (`arxiv:v2/main.tex:634-637`, `rank.py:84-87`).
- **Why undeclared.** Our prose presents the miss as the study's rule for any reply:
  - README `:85-86`
  - `btf3.py:27`, `:256-257`, `:308-309`
  - spec `:154-157`
  - the row `benchmarks.py:7910, 7914-7916`, under "Scored as the paper scored it"

  Issue #1868's F1 does ask for "Case scores 0 under the abstain rule". The issue chose it, but no
  file names it as a difference from the paper. README `:91-92` is right only for a failed call.
- **Severity and bound.** Score-changing. Per run the bound is `no_forecast`/1,515: the run metric
  `no_forecast` counts exactly these Cases, so the size of the effect can be read off any run. On the
  study's own corpus it is `0`: the PARSE stage dropped 0 of 2,700 cells, and the paper says
  "BTF-v3 has none" (`arxiv:v2/main.tex:642`). Synthetic: 146 no-forecast Cases moved accuracy
  0.4931 → 0.4455.
- **For a Fusion Candidate**, a committee that reaches no decision is the paper's miss, and ours
  matches. The deviation applies to a single model's unreadable reply.

### D5 — the answer line is reworded to name a probability (declared, 2026-11-18)

- **Declared.** Contributor's decision, 2026-11-18. README, spec §12, the row's
  `# NAMED DEVIATIONS`, `btf3.py` (comment on `PROMPT_TEMPLATE`).
- **What differs.** The study's closing line: ``End your response with exactly one line in this
  format: `Final answer: <number between 0 and 1>`. Do not write anything after that line.`` Ours:
  ``The last thing you write is your final answer as a probability between 0 and 1, on its own
  line in this format: `Final answer: <probability between 0 and 1>`. Do not write anything after
  that line.`` It keeps A.1's own wording ("final answer as a probability between 0 and 1") and the
  study's exact output format, so the reader and the mark are unchanged. Everything above the
  line is the study's, byte for byte (pinned).
- **Severity and bound.** Possibly-score-changing, `unknown`: the study's 18/18 readability check
  (`study:1_forecasting_prompts/bench_formats.py:93-95`) and its 2,700 replies were under its own
  line, and no run under ours exists yet. A paid run of a few small models on the study's 100
  Cases under both lines would measure it.

## Checks run

- [x] **Read-only on the checkout.** `git status --porcelain | wc -l` → `13` before: the coordinator's
  uncommitted btf3 edits. `14` after: the only addition is this record, which is tracked at
  `d5c8007b3` and now modified. Scratch:
  `SCRATCH=/private/tmp/claude-501/-Users-yimingliao-Projects-streamingface/d54939ed-e1b5-4f61-9053-310c5cb51e5e/scratchpad/btf3audit3`,
  deleted at the end. The study files were copied into scratch and imported from there.
- [x] **No keys, no model.** `env -i PATH="$PATH" HOME="$SCRATCH" UV_CACHE_DIR="$SCRATCH/uv-cache" env | grep -iE 'key|token|secret'` → empty, `rc=1`. Every script, ours and the study's, ran as `env -i PATH="$PATH" HOME="$SCRATCH" HF_HUB_OFFLINE=1 <engine>/.venv/bin/python -I -B …`. No model, gateway or provider was called.
- [x] **Harness over paper.** The harness is the study code that produced the paper's numbers. Paper and harness disagree on the prompt (Upstream notes), and the harness wins.
- [x] **Declared is not a finding.** D1–D3 are declared (README `:97-106`; the row's `# NAMED DEVIATIONS` `benchmarks.py:7935-7938` for D1 and D2). D4 is undeclared.
- [x] **Every cell has evidence.**
- [x] **Every `file:line` is copied from command output.** Our lines come from `cat -n` / `awk 'NR>=…'` / `grep -n` on the working tree. The study's lines come from `grep -n` / `sed -n` on the study package. The paper's lines come from `grep -n` / `sed -n` on the extracted e-print.
- [x] **Every citation names its tree.** Unprefixed `btf3.py`, `prepare.py`, `benchmarks.py` and `local_tasks/…` are under `apps/screamingface-engine/src/screamingface_engine_inspect/`. README is `local_tasks/btf3/README.md`, and spec is `docs/spec/2026-11-17-btf3-local-task.md`. Prefixes:
  - `study:` = `/Users/yimingliao/Projects/streamingface/crowd-wisdom-package` (local, unversioned; sha256 `bench_formats.py` `746eb79e…`, `forecast_prompts.py` `757508c0…`, `questions/btf3_100.json` `c08dd4bf…`, `committee_kit/metrics.py` `2c94cb74…`, `rank.py` `15c648f3…`, `corpus.py` `b8cb2dcf…`). Bare `run_openrouter.py`, `llm_api.py`, `run_umbc.py` and `manifest.py` are under `study:1_forecasting_prompts/`. Bare `metrics.py`, `rank.py` and `corpus.py` are under `study:3_results_report/committee_kit/`, and `PROVENANCE.md` is under `study:3_results_report/data/`.
  - `arxiv:v2/` = `https://arxiv.org/e-print/2608.24001v2`, tarball sha256 `bab87ad3a9e93b1e2994330db46f4fc4f61759b9114427a9f5332671850013c0` (v1: `2c9694b2…`)
- [x] **A verdict never claims more than its evidence.** No dimension is `unchecked`. D2 and D3 stay open at `unknown`, and D1's measured bound already settles `not-comparable`.
- No `ours` override was set.

1. `git rev-parse HEAD` → `d5c8007b3a880ee0a75f7fc821e3fa07f2b9f477`; `origin/main` → `ce6b73839…`; `git status --porcelain | wc -l` → `13`.
2. `scripts/check1.py <SCRATCH> <pinned parquet>` → `fingerprint 1c1d7973a6094bf4`, `judge None`, `case_digest 2110d3d33f2ee522fb82282bed2a3854a9483c0338bc65b8bd19ef42d5aae282`, `case_set_digest 07269005463712e6c2c5de87e763c9dc8f5afc19c11ed8d92e4dcc8e60c58baa`, `case_count 1515`. The fingerprint equals `published_revision` (`benchmarks.py:7899`), `test_benchmark_fingerprints.py:167` and `test_published_revisions.py:133`.
3. The same script →
   - `PROMPT_TEMPLATE 3325 1b5397…`; `study tight 3325 1b5397… EQUAL`; `forecast_prompts.BTF 3268 1494ebd2…`
   - braces `['{background}', '{question}', '{resolution_criteria}', '{today}']`
   - `parquet sha256 50f01603… == pin`; `rows 1515 {0.0: 1014, 1.0: 501} unique ids 1515`
   - `study items 100 missing from pin []`
   - `our input == btf_render(stored prompt,'tight'): 100 / 100`
   - `stored prompt == forecast_prompts.BTF filled with row + present_date[:10]: 100 / 100`
   - `gold equal: 100 / 100 {'0': 72, '1': 28}`
4. `scripts/digest.py` (`load_btf3()` from the HF cache snapshot `ad5a2165…`, `prepared_case(s, i+1, s.input, TASK_REPLAY_CASES["btf3"])`) → `1515 True True 2110d3d3`.
5. `sed -n '121,158p' study:…/bench_formats.py` vs `vendor/study_btf_parse.py` from its `_ASTERISK` line → `diff` `IDENTICAL`, sha256 `0e263b1c…`.
6. `scripts/sheets.py <SCRATCH> <pinned parquet>`. It uses the real `btf3_accuracy` and `btf3_headline` against the study's `btf_parse` → `is_correct`/`brier` → `score_entry` pipeline.
   - Sheets, giving differing Cases and the Cases the study drops:
     - `gold_final_line`, `gold_bare`, `exact_half`, `bold`, `wrong`, `trailing_prose`, `percent_stray_1`: `(0, 0)` each.
     - `percent_only`, `midreply_period`, `empty`: `(1515, 1515)` each.
     - `total 15150 agree 10605`.
   - Roll-up vectors as in the table.
   - Recorded answers (`study:3_results_report/data/btf3_results.csv`, each wrapped as `Final answer: <answer>`) → `models 27 cells 2700 per-cell marks equal 2700 | max |acc diff| 0.00e+00 max |brier diff| 0.00e+00`; study stages `PARSE kept 2700 dropped 0`.
7. Paper: `curl https://arxiv.org/abs/2608.24001` → v1 and v2, submitted 25 Aug 2026. `curl -L https://arxiv.org/e-print/2608.24001v{1,2}` → sha256 above, then `tar -xzf`. `grep -n` on both versions gives the accuracy rule (v2 `:623-624`), 100 sampled (`:577`, `:613`), unusable vs abstain (`:630-642`), "BTF-v3 has none" (`:642`), the sampling TODO (`:535-536`), the original authors' prompts (`:580`) and the dataset footnote (`:558`). The same lines appear in v1, and neither version mentions Brier or temperature. The local `study:5_paper/arXiv.tex` is a later draft than v2 (967 diff lines) and was not used as the reference.
8. Study `grep -n`:
   - `temperature=0.0` at `llm_api.py:341`; `TEMPERATURE = 0.0` at `run_umbc.py:83`
   - render at `run_openrouter.py:807`, parse at `:885`, escalation at `:341`
   - `DRAW_SEED = 20260808` at `manifest.py:35`; `20260815` is in no study code
   - `PROVENANCE.md:8, 64`
9. Prose: `grep -n "miss\|study's rule\|abstain rule\|NO_RESPONSE"` over README, `btf3.py`, the spec and `_exact.py`, plus a JSON scan of `packages/screamingface/examples/23_btf3.ipynb`. Every no-forecast sentence says "miss, Brier 0.25" (D4). The notebook says so too, without attributing it to the paper.
10. `uv run --extra inspect pytest tests/unit/inspect/test_local_task_btf3.py -q` → `33 passed, 1 warning`.
11. `uv run --extra inspect python scripts/fidelity_check.py` → `btf3 fresh not-comparable 2026-11-17`. `rm -rf "$SCRATCH"`.

## Recommended paid runs

None for the verdict, which D1 settles. One run would bound D2 to D4 together: one of the study's
27 models, at temperature 0, on the 100 study Cases, about 100 calls. Compare its per-Case accuracy
and Brier with that model's rows in `study:3_results_report/data/btf3_results.csv`, and record
`no_forecast`. No judge is involved.

## Upstream notes

- **Paper vs harness, prompt.** The paper says it adopts "the question prompts specified by the
  original benchmark authors without introducing additional prompt engineering"
  (`arxiv:v2/main.tex:580`). The harness sent a shortened copy of Bench to the Future's A.1 with a
  replaced answer line (`bench_formats.py:100-117`). The harness wins, and ours follows it.
  `study:1_forecasting_prompts/README.md:10` calls `forecast_prompts.py` "Not used for the paper's
  answers", yet all 100 stored prompts equal `forecast_prompts.BTF` filled (Checks 3).
- **Paper vs harness, Brier and temperature.** The published v2 reports neither. Both come from the
  harness (`metrics.py`, `llm_api.py:341`). Brier is ours as a side metric only, and cannot move the
  headline.
- **Dataset footnote.** `arxiv:v2/main.tex:558` names `huggingface.co/datasets/BTF-2/BTF-3`. The
  contributor says it redirects to `futuresearch-ai/BTF-3`. That was not re-checked here, but the
  100/100 match settles the commit.
- **Issue vs paper commit.** Issue #1868 quotes 1,471 questions (the 2026-09-15 audit release) and
  also asks for the paper's commit, which holds 1,515. The pin follows the commit (README `:21-27`,
  spec `:158-160`), and the conflict is flagged for the maintainer.
- **FutureSearch leaderboard (secondary).** It scores research agents over a frozen web corpus,
  Binary `n=2,015`. Its numbers are not comparable with this closed-book Benchmark. This is
  carried from the previous audit's fetch of 2026-11-17 and was not re-fetched. The row's
  `frontier_score` reason says so (`benchmarks.py:7974-7979`).
- **Row metadata.** `paper_url` is Diverse by Reasoning (`benchmarks.py:7950`), while `authors` and
  `citation` are FutureSearch's dataset (`:7951-7959`). The comment at `:7947-7949` explains the
  choice. This is cosmetic.
- **inspect_evals** v0.20.0 has no BTF task, so `comparable-to-inspect` cannot apply.
