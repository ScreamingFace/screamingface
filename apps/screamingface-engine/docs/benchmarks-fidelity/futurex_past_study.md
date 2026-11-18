---
benchmark: futurex_past_study
origin: external
verdict: unverified
verdict_reason: "the reference, the crowd-wisdom study's own package, is private and was not read by this audit: every comparison below is against two fixtures the contributor generated from it, so the study-side values are contributor-attested, not audited. Against those fixtures, the 27 stored models reproduce through the production reading (max gap 5.55e-17, tolerance 1e-12), and one declared score-changing deviation was measured (D4: the stored fused-medoids committee scores 0.3061 here against the study's 0.3020, +0.0041 in the Candidate's favour, because an empty answer leaves the score whoever wrote it); 0.0041 <= 0.005. One declared possibly-score-changing sampling deviation stays open (D3: the study called at temperature 0 and called again on a truncated reply; the row leaves sampling to the Candidate, and the notebook's replication cell omits temperature for gpt-5.5)"
audited: 2026-11-18
audited_at: 2dcc38aaf
fingerprint:
  benchmark: 3c66e638e04516ed
  harness_url: https://huggingface.co/datasets/futurex-ai/Futurex-Past/tree/3c2e39690de35eb1fcc621251f56343c72bae8c4
references:
  paper: https://arxiv.org/abs/2508.11987v3
  original_harness: https://huggingface.co/datasets/futurex-ai/Futurex-Past/tree/3c2e39690de35eb1fcc621251f56343c72bae8c4
  inspect_evals: https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0
  inspect_ai: https://github.com/UKGovernmentBEIS/inspect_ai/tree/v0.3.263
parity_test: tests/unit/inspect/test_local_task_futurex_past_study.py
parity_test_reason: ""
---

# FutureX-Past (study scoring) — Fidelity Record

## Verdict

**`unverified`.** This Benchmark exists to replicate the FutureX-Past numbers of a crowd-wisdom
study ("behavior-aware LLM crowds for future prediction"). Its reference is that study's own
code, not the FutureX authors' scorer. **That code is private, and this audit could not read
it.** What the repository holds instead:

- two vendored files whose code sha256s are pinned by tests;
- two fixtures the contributor generated from the study package
  (`apps/screamingface-engine/tests/fixtures/futurex_past_study/replication.json` and
  `replication_all_models.json`);
- the generator script beside them.

So this record can show only that **ours reproduces the fixtures**. It cannot show that the
fixtures, or the vendored files, are the study's. Every such claim is tagged **[attested]**
below. No marking rule is "comparable by default" because the Benchmark has no judge. The
auditor could not read the reference, so the verdict cannot be comparable.

What was measured against the fixtures (**[ran]**, Python 3.12.9):

- **The 27 single models.** Each model's stored answers go through the production reading
  (`study_reading` → `study_item_score` → `study_tier_weighted`). Each lands within `1e-12` of
  the study kit's `rank.score_entry` value as stored in the fixture: 18 of 27 are bit-equal, and
  the largest gap is `5.551115123125783e-17`. Tolerance 1e-12 because the fixture's values were
  computed under Python 3.11 **[attested]**.
- **The one committee in the fixtures, `fused-medoids`.** Through the production `study_headline`
  it gives `{'study_score': 0.3060836169346808, 'answered': 98, 'excluded': 2}`. The study
  reports `0.3019627378138016` (its Table III's 0.302). That number comes back bit-exact only
  when the 2 Cases the committee abstained on (empty answers, both level 1) are kept as 0. This
  is **D4**: declared, score-changing, `+0.004120879120879162`, in the Candidate's favour.
- **Stored replies.** All 2,697 stored cells are **rebuilt**, not raw: the fixtures hold parsed
  tokens, and the test builds `"(stored answer)\n\boxed{" + ", ".join(tokens) + "}"`. On those,
  the usability gate agrees with the study's exclusion flag on 2,697 of 2,697. That is 38
  excluded: 23 empty, 15 rejected by `interpret_answer`.

Bound arithmetic against the original harness, as the fixtures represent it:

- A single-model run: `0/100 = 0.0000 ≤ COMPARABLE_TOLERANCE (0.005)`.
- The stored fused-medoids run: `D4 = +0.0041 ≤ 0.005`.
- Open, bound `unknown`: D3 (sampling), and the fixtures' provenance (**[attested]**).

`unverified` follows rule 2 of "Which verdict wins". The measured bounds fit within tolerance,
and the open items could still push them over.

## Dimensions

Tags: **[ran]** = a command this audit ran, output quoted; **[read]** = source this audit read at
`2dcc38aaf`; **[attested]** = the contributor's (or the earlier audit's, made on the contributor's
copy of the study package) claim about the private study package, not re-verifiable here.

| dimension | status | severity | bound | evidence |
|---|---|---|---|---|
| dataset | match | — | — | **[ran]** `load_futurex_past(revision=STUDY_REVISION, sha256=STUDY_SHA256, name="s")` downloaded the parquet fresh into a scratch HF cache. The loader's sha256 check passed (`55ecf4f11909d412d515eeeab5b5891012adde4ff4353d35204179728704ad50`, pinned at `apps/screamingface-engine/src/screamingface_engine_inspect/local_tasks/futurex_past/futurex_past_study.py:71-72`). Results: `dataset samples 1118`. `prepared_case` over every Sample then `case_digest` gives `f59af6364123f213bc57f51e5b505023c72e81e48c8a45eb75ce768939fa072f`, equal to the declared value (`apps/screamingface-engine/src/screamingface_engine_inspect/prepare.py:2331`). `fixture positions == loader positions: True`; `STUDY_CASES == sorted positions: True` (`futurex_past_study.py:76-83`). Fixture gold and level after `normalise`, against the loader's at those positions: `gold/level differ vs fixture gold: []`. **[attested]** That the fixture's `gold` is the study's `data/futurex_gold.csv`, and that the study downloaded this commit on 2026-08-08 (README `:150-152`). The other 1,018 Cases are outside the study by design: the README says to pass `cases=[...]`. |
| prompt | match | — | — | **[ran]** The 100 fixture prompts against the Case inputs at their positions: `fixture prompts != Case input: []`. Through the vendored `futurex_render(arm="original")` (`apps/screamingface-engine/src/screamingface_engine_inspect/local_tasks/futurex_past/vendor/study_formats.py:23-27`, a pass-through): `!= fixture prompt: []`. Also `non-string (multi-message) inputs: 0` and `Case input == Sample.input on all: True` (1,118). Input sha256: `d9b5e4e3…` in fixture item order, `efc1dbca…` in `STUDY_CASES` order. The earlier record's `3a103519…` does not reproduce in either order, and its concatenation rule was not recorded, so it is dropped. **[read]** One user message, no system message (`apps/screamingface-engine/src/screamingface_engine_inspect/local_tasks/futurex_past/futurex_past.py:128`, `input=row["prompt"]`). The spec does not set `keep_sample_input` (`prepare.py:2328-2338`; default `False` at `prepare.py:166`), so the grading `TaskState.input` is the Case input (`apps/screamingface-engine/src/screamingface_engine_inspect/scorer_adapter.py:625-634`). The gate therefore sees the prompt the Candidate saw. **[attested]** That the fixture's `prompts` (from the study's `fused_committee.load_questions`) are the prompts the study's model runs sent. |
| answer extraction | match | — | 0/100 against the fixtures | **[ran]** `test_the_vendored_reader_is_the_studys_bench_formats_below_our_header` passes. That shows the vendored `study_formats.py` below our header still has code sha256 `a74cbe880ffb0af9690361d87272427233950b8db98663777e486298e74eec1f`. Our comma split, `answer_tokens` (`apps/screamingface-engine/src/screamingface_engine_inspect/local_tasks/futurex_past/grading.py:113-117`), against the vendored `futurex_parse`'s own `answer` split (`vendor/study_formats.py:48-56`), over 800 synthetic sheets plus the 2,697 rebuilt replies: `3497/3497` equal. The gate on the 2,697 rebuilt replies: `gate agrees 2697`, `study-excluded 38`, ours unusable `empty 23 interpret 15`. The fixture has no reason column; the 23/15 split is our gate's reason, which equals the study's count **[attested]**. **The study's raw replies were not exercised**: the fixtures store parsed tokens only. **[read]** `study_reading` (`futurex_past_study.py:111-125`) runs `futurex_parse` → `answer_tokens` → `interpret_answer` (`vendor/study_formats.py:204`) on the raw box against the prompt. **[attested]** That `a74cbe88…` is the code of the study's `1_forecasting_prompts/bench_formats.py` (whole file `746eb79e…`). That `answer_tokens` equals the study's `build_data.py:89` split. That the study gated the raw box this way (`run_openrouter.py:997`, `umbc_verdict.py:69`). The earlier audit's 3,100 synthetic sheets were marked on the study side by the study package; they were not rerun here. |
| metric | match | — | 0/100 against the fixtures | **[ran]** `test_the_vendored_file_is_the_studys_code_below_our_header` passes: the vendored `study_metrics.py` code below our header has sha256 `b9a81867c34e6b76f581456809afc2b99024e18358e08a64bb18f23303676176`. `test_each_case_is_scored_by_the_studys_item_score_after_normalisation` passes (8 cases). The per-Case marks are the vendored `item_score` (`vendor/study_metrics.py:87-96`) over `normalise` (`futurex_past_study.py:86-93`). Their agreement with the study shows up as the 27-model reproduction (roll-up row). **[attested]** That `b9a81867…` is the study's `committee_kit/metrics.py` (whole file `2c94cb74…`). That `normalise` is the study's `committee_kit/corpus.py:27`. |
| roll-up | deviation | score-changing | +0.0041 on the stored fused-medoids answers (2/100 Cases, both level 1); 0 on every stored single-model run (D4) | **[ran]** Fixed vectors over the 100 study levels (28/47/16/9): `study_tier_weighted` against the vendored `tier_weighted` (`vendor/study_metrics.py:99-110`). Exact on all five: all-1 `1.0`; all-0 `0.0`; alternating `0.4555787740628166`; every-3rd-0.8 `0.2763019250253293`; every-5th-unusable `0.44908424908424904` (`tier_weighted` over the usable subset). Models: `models 27 exact== 18 max\|diff\| 5.551115123125783e-17`. That includes `nemotron-3-super-120b-a12b` with 97 cells: its 3 failed calls are absent, as `coverage_declare` leaves them (`apps/screamingface-engine/src/screamingface_engine_inspect/benchmarks.py:8046`). Committee: `fused-medoids production study_headline {'study_score': 0.3060836169346808, 'answered': 98, 'excluded': 2}`. Abstained cells: `['69d3aab8e53ae80066abf5cd\|2026-05-07', '6a26b60a9b0b8587160de150\|2026-06-21']`, levels `[1, 1]`, tokens `[[], []]`. Kept as 0 through the vendored `tier_weighted`: `0.3019627378138016`, equal to the fixture's expected value. `delta production - study 0.004120879120879162`. Pinned by `test_every_entry_in_the_study_reproduces_its_reported_score_exactly` (`apps/screamingface-engine/tests/unit/inspect/test_local_task_futurex_past_study.py:298`), `test_the_fused_committees_answers_score_0_306_here_with_two_cases_excluded` (`:316`) and `test_the_studys_own_committee_rule_gives_its_0_302` (`:159`). The last one marks every cell usable on the test side; it does not go through the production reading. **[read]** The Task's metric `study_tier_weighted` (`futurex_past_study.py:157-166`) and the row's whole-run metric `study_headline` (`:180-199`; `benchmarks.py:8059-8063`) both call `_study_score` over the same `_usable` Cases (`:149-154`, `:169-177`). **[attested]** That the fixture's `expected` values are the study kit's `rank.score_entry` (27 models) and `fused_committee.replay` (fused-medoids). That the kit under 3.12 gives our values bit-exact. |
| judge | not applicable | — | — | **[ran]** `imported_benchmark("futurex_past_study")`: `judge None`. **[read]** No judge on the row (`benchmarks.py:8017-8105`). The study marks by `item_score`, with no model. |
| sampling | deviation | possibly-score-changing | unknown (D3; 0 on a run with temperature 0 and no truncated reply) | **[read]** The row sets no `params` (`benchmarks.py:8017-8105`), and `solver=generate()` makes one call (`futurex_past_study.py:210`). The README asks for temperature 0 "where the provider accepts it" (`apps/screamingface-engine/src/screamingface_engine_inspect/local_tasks/futurex_past/README.md:190-193`). The notebook's replication cell **omits** temperature for gpt-5.5 because OpenRouter rejects it, and passes `params={"max_tokens": 8192}` (`packages/screamingface/examples/22_futurex_past.ipynb:202-204`, raw JSON lines). The earlier record said that cell passed `temperature: 0.0`; it no longer does. **[attested]** The study used `temperature=0.0` (`study:1_forecasting_prompts/llm_api.py:341`), called again with a larger cap on truncation (`study:1_forecasting_prompts/run_openrouter.py:340`), and kept the complete, interpretable record of a cell (`study:3_results_report/data/PROVENANCE.md:8`). |

## Deviations

### D4 — roll-up: an empty answer leaves the score, a committee's abstain included

- **Declared.** In four places:
  - the row: `apps/screamingface-engine/src/screamingface_engine_inspect/benchmarks.py:8044-8045`
    (`# NAMED DEVIATION`), and the description at `:8034-8036`;
  - the module docstring:
    `apps/screamingface-engine/src/screamingface_engine_inspect/local_tasks/futurex_past/futurex_past_study.py:11-14`;
  - the README: `README.md:164-169` and the "A committee tie" section, `README.md:195-206`
    (`NAMED DEVIATION` at `:202`);
  - the test docstring: `test_local_task_futurex_past_study.py:319`, and spec
    `docs/spec/2026-11-16-futurex-past-local-task.md` "Amendment after the second review
    (2026-11-18, OME-1952)".
- **What differs.** The study scores a committee with no majority 0 and keeps it in the score.
  The vendored kit says so for an abstention: `item_score` "An abstention (got is None) scores
  0" (`vendor/study_metrics.py:88`), and `futurex_score` says "an abstention contributes 0, not a
  gap" (`:114`). That `rank.decide` applies this to a committee is **[attested]**
  (`apps/screamingface-engine/tests/fixtures/futurex_past_study/make_replication_fixture.py:94`).
  Our scorer sees one reply per Case and cannot tell a committee from a model. `study_reading`
  marks any empty answer unusable (`futurex_past_study.py:122-123`), and `_usable` drops it from
  the headline (`:149-154`). For a single model the study drops an empty cell too (its 23
  `no_answer` exclusions), so the two rules agree there.
- **Size and direction [ran].** On the stored fused-medoids answers: 0.3061 here against 0.3020
  in the study, `+0.004120879120879162`, in the Candidate's favour. The 2 dropped Cases are
  level-1 zeros, so the level-1 mean rises. In any run the Report's `excluded` metric counts the
  dropped Cases, and the Case Results list them. A Candidate that never returns an empty box
  (a single model, or a fusion that answers on a tie) moves 0.
- **Severity / bound.** `score-changing`; `+0.0041` (2/100 Cases) on the only committee the
  fixtures hold. Note: an earlier record also named `fused-dissimilar2 0.2715224304851964`. No
  committed fixture holds that committee (`contains 'dissimilar': False` in both files), so it
  is the contributor's report and cannot be reproduced from the repository.

### D3 — sampling: the study fixed temperature 0 and called again on a truncated reply

- **Declared.** `README.md:190-193`, and the comment in the notebook's replication cell
  (`packages/screamingface/examples/22_futurex_past.ipynb:202-203`).
- **Where.** Theirs **[attested]**: `study:1_forecasting_prompts/llm_api.py:341`,
  `study:1_forecasting_prompts/run_openrouter.py:340`, `study:3_results_report/data/PROVENANCE.md:8`.
  Ours **[read]**: the row (`benchmarks.py:8017-8105`) sets no `params`, and `generate()`
  (`futurex_past_study.py:210`) makes one call.
- **What differs.** Only what the Candidate writes; any given reply is marked the same. A
  truncated reply with no usable box is dropped on both sides, but the study had another draw
  at a usable one.
- **Severity / bound.** `possibly-score-changing`, `unknown`. It is 0 for a run whose Report
  shows `temperature: 0` in the Candidate's params and no Case with a truncated finish reason.
  The notebook's own replication run (gpt-5.5, no temperature) cannot meet the first condition.

### D1, D2 — lifted earlier on this branch; still lifted at 2dcc38aaf

- **What they were.** A reply with no usable box (D1), or with an uninterpretable box (D2), was
  scored and kept by us but dropped by the study.
- **The fix [read].** `vendor/study_formats.py` is vendored. Such a Case is marked
  `study_usable: False` (`futurex_past_study.py:111-125,141`), and the headline leaves it out
  (`:149-154,163-166,191-197`). Declared at `README.md:136-142`.
- **This audit [ran].** The gate agrees with the study's exclusion flag on 2,697 of 2,697
  rebuilt replies. The 27 models reproduce within 1e-12.

## Checks run

- [x] **Read-only on the checkout.** In the worktree
  `/Users/khoaguin/Desktop/projects/OpenMined/screamingface-stack/screamingface/.claude/worktrees/futurex-past-local-task`,
  `git status --porcelain | wc -l` gave `0` before and after, and HEAD is
  `2dcc38aafa910e8afe5e720ed3e3cf1cee7354b8` (PR
  [#1897](https://github.com/ScreamingFace/screamingface/pull/1897), not on main). The earlier
  record's `audited_at: 55d7f087f`: `git cat-file -t 55d7f087f` → `fatal: Not a valid object
  name`; no such commit exists in this repository. All artefacts went to one scratch folder with
  its own uv cache and HF cache. The audit scripts lived in a sibling folder, and both were
  deleted at the end.
- [x] **No keys, no model.** `env -i PATH="$PATH" HOME="$SCRATCH" UV_CACHE_DIR="$SCRATCH/uv-cache" env | grep -iE 'key|token|secret'`
  gave empty output (grep exit 1). Every command that ran third-party code (pytest, inspect_ai,
  huggingface_hub, pyarrow) ran under that prefix, plus `HF_HOME="$SCRATCH/hf"`. No model,
  gateway or provider was called.
- [x] **Harness over paper.** The study's harness is unreadable here; no paper-vs-harness
  disagreement was examined. The earlier audit reported that the study's code and paper agree
  on the denominator (`study:5_paper/main.tex:630-642`) **[attested]**.
- [x] **Declared is not a finding.** D3 and D4 are declared on the row, in the module docstring,
  and in the README. D1 and D2 are lifted. Nothing undeclared changes a mark against the
  fixtures.
- [x] **Every cell has evidence.** Each cell is tagged [ran] / [read] / [attested]. Every
  `match` is scoped "against the fixtures", because the study package was not read.
- [x] **Every `file:line` is copied from command output.** The greps are listed under Greps
  below.
- [x] **Every citation names its tree.** Ours uses repo-relative paths; short forms
  (`futurex_past_study.py`, `README.md`, `vendor/…`, `grading.py`, `futurex_past.py`) sit under
  `apps/screamingface-engine/src/screamingface_engine_inspect/local_tasks/futurex_past/`, and
  `benchmarks.py`, `prepare.py`, `scorer_adapter.py` under
  `apps/screamingface-engine/src/screamingface_engine_inspect/`. **`study:`** is the
  crowd-wisdom study package. It is **private, has no public URL, is not a git repository, and
  was not available to this audit.** Every `study:` citation and hash is **[attested]**: the
  contributor's, or the earlier audit's, made on a copy this audit cannot reach. The file
  hashes the earlier audit recorded for files we do not vendor (`corpus.py` `b8cb2dcf…`,
  `rank.py` `15c648f3…`, `fused_committee.py` `2dcd0239…`, `questions/futurex_100.json`
  `f1105b29…`, `data/futurex_results.csv` `a86781d1…`, `data/futurex_gold.csv` `08810463…`)
  cannot be recomputed here. The same holds for its `FORMATS IDENTICAL` / `METRICS IDENTICAL`
  diffs. What is verified is that our copies still carry the code hashes the vendor header
  records (both pinning tests pass). `references.original_harness` and
  `fingerprint.harness_url` carry the row's declared `harness_url` (`benchmarks.py:8091-8093`):
  the dataset tree at `3c2e3969`, the questions the study froze.
- [x] **A verdict never claims more than its evidence.** No core dimension is `unchecked`
  against the fixtures. The reference itself was not read, and D3 is open, so the verdict is
  `unverified`.
- No `ours` override was set.

**What this audit ran** (Python 3.12.9, `inspect_ai 0.3.263`, `inspect_evals 0.20.0` installed in the isolated env):

1. **Tests.** From `apps/screamingface-engine`:
   `uv run --isolated --extra inspect pytest tests/unit/inspect/test_local_task_futurex_past_study.py --no-cov -q -p no:cacheprovider`
   under the `env -i` prefix → `41 passed, 1 warning in 2.37s`. This includes
   `test_every_entry_in_the_study_reproduces_its_reported_score_exactly` (`:298`),
   `test_the_fused_committees_answers_score_0_306_here_with_two_cases_excluded` (`:316`),
   `test_the_studys_own_committee_rule_gives_its_0_302` (`:159`),
   `test_the_gate_reproduces_every_exclusion_in_the_studys_stored_replies` (`:260`), both
   vendored-hash tests (`:57`, `:208`), and the two end-to-end Engine tests (`:352`, `:434`).
2. **Identity.** `imported_benchmark("futurex_past_study").fingerprint` → `5f0592a339ea841d`.
   That equals the literal at `apps/screamingface-engine/tests/unit/inspect/test_benchmark_fingerprints.py:171`
   and `published_revision` at `benchmarks.py:8019`. Also `judge None`, `origin external`.
3. **Fixture inventory.** `replication_all_models.json`: 28 answer entries (27 models +
   `fused-medoids`). Each cell holds only `excluded` and `tokens` (plus `abstained` on
   fused-medoids), so no raw reply and no exclusion reason is stored. `replication.json`: 3
   models + `fused-medoids`, expected
   `{'claude-haiku-4.5': 0.273607528208592, 'claude-opus-4.6': 0.3329812563323202, 'claude-sonnet-4.6': 0.2608527524484971, 'fused-medoids': 0.3019627378138016}`.
   Neither file contains `dissimilar`.
4. **Dataset, prompts, gold, digest.** See the dataset and prompt rows. Also
   `prompts containing literal \boxed{: 1118 of 1118`, matching the maintainer's measurement of
   2026-11-18 on the pinned file.
5. **Reading, gate, split, roll-up, committee.** See the answer-extraction and roll-up rows.

**What this audit read but did not run:** the row (`benchmarks.py:8017-8105`), the module, the
vendored files and their header (`vendor/__init__.py:1-29`), the README, the spec amendment of
2026-11-18, the fixture generator, and the notebook's replication cell.

**What the contributor reported, not re-verifiable here:** everything tagged [attested]. In
particular:

- that the vendored files are the study's files;
- that the fixtures' `expected`, `gold`, `prompts` and `tokens` come from the study package
  (`source: crowd-wisdom-package 3_results_report/data + 4_fused_committee replay`);
- the study's download record for `3c2e3969`;
- the study kit's bit-exact agreement under 3.12;
- `rank.decide`'s committee rule;
- the study's sampling settings;
- the earlier audit's 3,100 synthetic sheets;
- the `fused-dissimilar2` score;
- the claim that the one non-literal key at this pin (`[Yes]`) is not among the 100.

**Greps** (`grep -n` / `sed -n` on the files at `2dcc38aaf`):

- `grep -n 'futurex_past_study' benchmarks.py prepare.py test_benchmark_fingerprints.py`
- `sed -n '8010,8110p' benchmarks.py`; `sed -n '2320,2345p' prepare.py`
- `grep -n 'def answer_tokens\|def leveled\|def case_key\|def record_to_sample\|input=row\|def load_futurex_past' grading.py futurex_past.py`
- `grep -n '^def ' vendor/study_formats.py vendor/study_metrics.py`
- `grep -n 'An abstention\|def item_score\|def tier_weighted\|Every item counts' vendor/study_metrics.py`
- `sed -n '605,640p' scorer_adapter.py`; `grep -n 'keep_sample_input' prepare.py`
- `grep -n 'NAMED DEVIATION' futurex_past_study.py README.md test_local_task_futurex_past_study.py`; `sed -n '8040,8046p' benchmarks.py`
- `grep -n 'A committee tie\|To replicate a run\|A reply with no usable answer leaves\|0.306\|+0.0071' README.md`
- `grep -n 'def test_' test_local_task_futurex_past_study.py`
- `grep -n 'solver=generate\|metrics=\[study' futurex_past_study.py`
- `grep -n 'abstained\|rank.decide' make_replication_fixture.py`
- `grep -n 'temperature\|max_tokens' 22_futurex_past.ipynb`; `sed -n '196,206p' 22_futurex_past.ipynb`
- `grep -n '^## \|^### ' docs/spec/2026-11-16-futurex-past-local-task.md`; `sed -n '277,300p'` of the same file

## Recommended paid runs

None: there is no judge. Two things remain open. Neither is paid.

- **A Report read on a replication run.** Use a Candidate that accepts temperature 0, over the
  100 study positions. Confirm `temperature: 0` in the Candidate's params, and count the Cases
  with a truncated finish reason. If there are none, D3 is 0 for that run. The notebook's
  gpt-5.5 cell cannot close D3, because it sends no temperature.
- **A re-audit against the study package itself**, if its owner shares it, under the same
  `env -i` rules: re-hash the non-vendored files, re-diff the two vendored files, re-run the
  synthetic sheets on the study side, and run the study's raw replies (not rebuilt boxes)
  through both readers. Only that can lift the [attested] items. Together with a run that
  closes D3, it could support `comparable-to-paper`, with D4's +0.0041 declared for committee
  replays.

## Upstream notes

- **The study's own kit keeps an abstention as 0** (`vendor/study_metrics.py:88,114`, **[read]**).
  That is the source of D4. For a single model, the study's reporting path instead drops an
  empty cell (its 23 `no_answer` exclusions, **[attested]**). The study therefore has two rules
  for an empty answer, and our scorer applies the single-model one to every Candidate.
- **The study is not consistent with itself on a fused tie** **[attested]**. Its
  `run_benchmark` writes a tie as `excluded=True, "no fused answer"`
  (`study:4_fused_committee/fused_committee.py:174-175`), which the kit would drop. Its
  `replay`, which produced the published 0.302, keeps the tie as 0. Our 0.306 equals the
  `run_benchmark` reading; the study's published 0.302 equals the `replay` reading.
- **A ScreamingFace fusion is not the study's committee.** It answers on a tie (the
  contributor's fusions keep the first member's answer, README `:195-200`, **[attested]**), so
  D4 does not fire. On the two tie Cases it is marked on a real answer instead of the study's 0.
  That can move a fusion's headline from the study committee's by between 0 and +0.0071 (2/28
  level-1 Cases × weight 10/100). This is a Candidate-side difference, not counted here and not
  verified.
- **The study's `no_answer` label came from its completeness reviewer, not from a parse**
  **[attested]**. Our gate (no tokens means unusable) reproduces all 23 such cells because every
  one has empty tokens. A corpus where the reviewer flagged a boxed reply would need a re-check.
- **An unusable Case still shows a per-Case value.** That value is the study's `item_score` of
  its tokens, so the scorer's per-Case `mean()`/`stderr()` (`futurex_past_study.py:128`)
  include it; only the `study_score` headline leaves it out. Declared at `README.md:139-141`.
  Cosmetic, bound 0.
- **[inspect_evals](https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0) has no
  FutureX eval**, so it is not a reference. This was reported by the earlier audit and not
  re-checked. [Futurex-Eval@2626f7a2](https://github.com/Futurex-ai/Futurex-Eval/tree/2626f7a297cd87c73a45408e23af8d838f5b60e5)
  is the reference for `futurex_past`, not for this Benchmark.

## Since the audit (2026-11-18, OME-1952)

The fingerprint moved from `5f0592a339ea841d` to `3c66e638e04516ed` after the audit at `2dcc38aaf`, because three
things the audit itself pointed out were fixed in the package the fingerprint covers. None
changes how a reply is read or marked, so the findings above stand:

- `grading.py` lost a stale header comment and its file-level pyright directive (it no longer
  imports the inspect extra's packages).
- The README names the three prompts that ask for a "boxed answer" rather than a "boxed numeric
  value" (Cases 1285, 1288, 1327).
- The row and the README now declare that a judge call on a marking question that still fails
  after its retries fails the Case as `scorer_error`, where Futurex-Eval scores it 0. That rule
  belongs to `futurex_past`; this Benchmark calls no judge and shares only the package.
