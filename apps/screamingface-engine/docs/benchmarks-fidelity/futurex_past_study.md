---
benchmark: futurex_past_study
origin: screamingface
verdict: unverified
verdict_reason: "grading is the study's to the last bit (prompt, reply reading, usability gate, per-Case mark and roll-up all match; 0/100 Cases differ; all 27 stored models and both fused committees reproduce rank.score_entry exactly under Python 3.12); one declared possibly-score-changing sampling deviation stays open (D3: the study called at temperature 0 and called again with a larger token cap when a reply was cut off; the row leaves sampling to the Candidate, README.md:184-187), settled per run by a Report showing temperature 0 and no truncated reply. audited_at 55d7f087f is the local unmerged head of branch futurex-past-local-task (base origin/main cc5cfd36d)"
audited: 2026-11-16
audited_at: 55d7f087f
fingerprint:
  benchmark: 0d516b151df8c19e
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

**`unverified`.** The reference is the crowd-wisdom study's own code ("behavior-aware LLM crowds
for future prediction"), not the FutureX authors' scorer: this Benchmark exists to replicate that
study's FutureX-Past numbers.

On the exam itself, the two examiners are one examiner:

- **Prompt.** All 100 study prompts are byte-identical to our Candidate inputs (sha256
  `3a103519…` on both sides).
- **Code.** The reply reader and usability gate are the study's `bench_formats.py` (vendored as
  `vendor/study_formats.py`), and the scorer is its `committee_kit/metrics.py` (vendored as
  `vendor/study_metrics.py`). Both match byte for byte.
- **Synthetic sheets.** 3,100 answer sheets over the 100 items: 1,398 are scored identically,
  1,702 are dropped by both sides as unusable, and 0 differ.
- **Stored replies.** All 2,697 of the study's stored replies: 2,659 are identical, 38 are
  dropped by both (the study's 23 `no_answer` and 15 `uninterpretable` exclusions), and 0 differ.
- **Headlines.** Through the real `study_tier_weighted`, all 27 models and both fused committees
  equal the study kit's `rank.score_entry` exactly under Python 3.12. This includes the published
  fused-medoids **0.302** (`0.3019627378138016`). Under 3.11 the largest gap is `5.6e-17`, from
  `statistics.fmean` rounding.

`sum of bounds against the original harness = 0/100 = 0.0000 ≤ COMPARABLE_TOLERANCE (0.005)`.

**What stays open is D3, which is declared.** It concerns what the Candidate writes, not how a
reply is marked. The study called every model at temperature 0, and called again with a larger
token cap when a reply was cut off. Our row leaves sampling to the Candidate; the README
(`:184-187`) and the notebook's replication cell say to pass temperature 0. A run whose Report
shows `temperature: 0` in the Candidate's params and no truncated reply is comparable to the
study's numbers.

## Dimensions

| dimension | status | severity | bound | evidence |
|---|---|---|---|---|
| dataset | match | — | — | Our loader (`apps/screamingface-engine/src/screamingface_engine_inspect/local_tasks/futurex_past/futurex_past.py`, `record_to_sample` with `input=row["prompt"]` at `:128`) is pinned at `futurex_past_study.py:66-67`. It downloads snapshot `3c2e39690de35eb1fcc621251f56343c72bae8c4`, parquet sha256 `55ecf4f11909d412d515eeeab5b5891012adde4ff4353d35204179728704ad50`. That gives 1,118 Cases with Case Digest `f59af636…`, equal to the declared one (`prepare.py` `TASK_REPLAY_CASES['futurex_past_study']`) (Checks 3). The study's 100 `item_id`s (`study:1_forecasting_prompts/questions/futurex_100.json`) sit at Case positions equal to `STUDY_CASES` (`futurex_past_study.py:71-78`): `True`. Against `study:3_results_report/data/futurex_gold.csv` after `normalise`, gold and level differ on `[]` (Checks 4-5). The one non-literal key at this pin (`69c527154b6f01005cae131a`, `[Yes]`) is not among the 100. The other 1,018 Cases are outside the study by design: the row and README say to pass `cases=[…]`. |
| prompt | match | — | — | The study's arm "original" passes the prompt through (`study:1_forecasting_prompts/bench_formats.py:35-39`). Ours goes through the importer's `captured_case_records`: `Sample.input == Case input on all: True`. `input != futurex_render: []`, and the sha256 of the 100 inputs is `3a103519e7a0678dfb066bdf27169243cb68054e115894bd83d12443cf5718e4` on both sides (Checks 3-4). There is one user message and no system message. At grading, `state.input_text` is the Case input (`scorer_adapter.py:608-633`; `keep_sample_input=False` on this row), so the usability gate sees the same prompt the study's `interpret_answer` saw. |
| answer extraction | match | — | 0/100 | `vendor/study_formats.py` below its header, diffed against `study:1_forecasting_prompts/bench_formats.py` from line 23, gives `FORMATS IDENTICAL`. Its code sha256 `a74cbe88…` is pinned in `tests/unit/inspect/test_local_task_futurex_past_study.py`. Ours (`futurex_past_study.py:106-120`) runs `futurex_parse` (`vendor/study_formats.py:48`), then the comma split `grading.py:112` (byte-identical to `abb05ea9b`; equal to `study:3_results_report/build_data.py:89`), then `interpret_answer` (`vendor/study_formats.py:204`) on the raw box against the prompt. That is how the study ran it (`study:1_forecasting_prompts/run_openrouter.py:997`, `umbc_verdict.py:69`). Answer sheets: 31 per study item × 100 = 3,100, marked on the study side by `futurex_parse` + `build_data` split + `interpret_answer` + `item_score`, giving `both score, identical 1398`, `both drop 1702` (the study's 1,102 `uninterpretable` and 600 `no answer`), and 0 `DIFFER`. All 2,697 stored replies, rebuilt as `\boxed{…}` the way the study's replay rebuilds them (`study:4_fused_committee/fused_committee.py:198`): `both score, identical 2659`, `both drop 38` (`no_answer` 23, `uninterpretable` 15), 0 `DIFFER` (Checks 6). |
| metric | match | — | 0/100 | `vendor/study_metrics.py` lines 11-135, diffed against `study:3_results_report/committee_kit/metrics.py` lines 11 onward, gives `METRICS IDENTICAL` (whole file `2c94cb74…`). `normalise` (`futurex_past_study.py:81-88`) equals `study:3_results_report/committee_kit/corpus.py:27-33`. Per-Case marks are identical on every reply the study scores (row above). |
| roll-up | match | — | 0/100 | Fixed vectors through the study's `tier_weighted` and our `study_tier_weighted` (`futurex_past_study.py:152-167`, `_usable` `:144-149`, `leveled` `futurex_past.py:243`): all-1, all-0, alternating and every-3rd-0.8 are each `exact True`. A vector with every 5th Case unusable gives `0.44908424908424904`, the same as `tier_weighted` over the usable subset. The first 10 Cases sent through the Engine's `zero_sample_score` (`candidate_abstained`) give `0.4501860712387028`, as expected (Checks 7). The study kit's `rank.score_entry` (`study:3_results_report/committee_kit/rank.py:159-175`) under 3.12, against ours over our scorer's marks and metadata: `ours == kit 3.12: 27 of 27`, `max \|ours - kit 3.11\| 5.55e-17`. Fused-medoids: replay `0.3019627378138016`, ours `0.3019627378138016`. Fused-dissimilar2: `0.2715224304851964` on both sides (committee ties kept as 0, as the study's `rank.decide` does). A failed call leaves the denominator on both sides (`coverage_declare`, `benchmarks.py:8070`; nemotron-3-super's 97 cells reproduce exactly). |
| judge | not applicable | — | — | `judge None` on the row (Checks 3); the study marks by `item_score`, with no model. |
| sampling | deviation | possibly-score-changing | unknown (D3; 0 on a run with temperature 0 and no truncated reply) | The study used `temperature=0.0` (`study:1_forecasting_prompts/llm_api.py:341`) and called again with a larger cap on truncation (`study:1_forecasting_prompts/run_openrouter.py:340`). Where a cell had more than one record, it kept the complete, interpretable one (`study:3_results_report/data/PROVENANCE.md:8`). Ours: `params None` on the row, one call. Declared in `README.md:184-187` and in the notebook's replication cell (`packages/screamingface/examples/22_futurex_past.ipynb`, `params={"max_tokens": 8192, "temperature": 0.0}`). |

## Deviations

### D3 — sampling: the study fixed temperature 0 and called again on a truncated reply

- **Declared.** `apps/screamingface-engine/src/screamingface_engine_inspect/local_tasks/futurex_past/README.md:184-187`,
  and the notebook's replication cell. Numbering follows the first audit at `c8dadab6c`, where D1
  and D2 were the denominator deviations.
- **Where.** Theirs: `study:1_forecasting_prompts/llm_api.py:341`,
  `study:1_forecasting_prompts/run_openrouter.py:340`, `study:3_results_report/data/PROVENANCE.md:8`.
  Ours: the row `apps/screamingface-engine/src/screamingface_engine_inspect/benchmarks.py:8046-8121`
  sets no `params`, and `solver=generate()` (`futurex_past_study.py:178`) makes one call.
- **What differs.** Only what the Candidate writes. Any given reply is marked identically. A
  truncated reply with no usable box is dropped on both sides; the study simply had another draw
  at a usable one.
- **Severity / bound.** `possibly-score-changing`, bound `unknown`. It is 0 for a run whose Report
  shows `temperature: 0` in the Candidate's params and no Case with a truncated finish reason.

### D1, D2 — lifted earlier on this branch, unchanged at 55d7f087f

- **What they were.** A reply with no usable box (D1) or an uninterpretable box (D2) was scored
  and kept by us but dropped by the study. They moved 21 of 27 model headlines, by up to 0.0383.
- **The fix.** The study's `bench_formats.py` is vendored, such a Case is marked
  `study_usable: False` (`futurex_past_study.py:106-120,136-138`), and `study_tier_weighted` leaves
  it out (`:144-149,159`).
- **Where it is declared.** `README.md:131-137` and spec
  `docs/spec/2026-11-16-futurex-past-local-task.md` §11.
- **This audit.** 0 differing marks, 0 differing drops, 27/27 models exact.

## Checks run

- [x] **Read-only on the checkout.** `git status --porcelain | wc -l` gave `0` before and after;
  HEAD is `55d7f087f` (local unmerged branch head; base origin/main `cc5cfd36d`). Every artefact went to
  a scratch folder with its own HF cache, deleted at the end. The study package was imported only
  with `python -I -B`; its `.pyc`/`__pycache__` count was `0` before and after.
- [x] **No keys, no model.** `env -i PATH="$PATH" HOME="$SCRATCH" UV_CACHE_DIR="$SCRATCH/uv-cache" env | grep -iE 'key|token|secret'`
  gave empty output. Study code ran under `env -i … python3 -I -B` (3.11.7) and `python3.12 -I -B`
  (3.12.1). The kit uses the standard library only. No model, gateway or provider was called; the
  fused committees replay stored cells.
- [x] **Harness over paper.** The study's code and its paper agree on the denominator
  (`study:5_paper/main.tex:630-642`).
- [x] **Declared is not a finding.** D3 is declared in the README and the notebook. D1 and D2 are
  lifted. Nothing undeclared changes a mark.
- [x] **Every cell has evidence.** See Dimensions and the numbered checks below.
- [x] **Every `file:line` is copied from command output** (`grep -n`, `cat -n`, `sed -n`); listed
  in Checks 9.
- [x] **Every citation names its tree.** Ours uses repo-relative paths. The package is
  `apps/screamingface-engine/src/screamingface_engine_inspect/local_tasks/futurex_past/`;
  `benchmarks.py`, `prepare.py`, `scorer_adapter.py` and `scorer_metrics.py` sit under
  `apps/screamingface-engine/src/screamingface_engine_inspect/`. **`study:`** is the crowd-wisdom
  study package, local to the contributor. It has **no public URL and is not a git repository**,
  so it is pinned by the sha256 of each file read:

  | file | sha256 |
  |---|---|
  | `bench_formats.py` | `746eb79e…` (code after docstring `a74cbe88…`) |
  | `committee_kit/metrics.py` | `2c94cb74…` |
  | `committee_kit/corpus.py` | `b8cb2dcf…` |
  | `committee_kit/rank.py` | `15c648f3…` |
  | `fused_committee.py` | `2dcd0239…` |
  | `questions/futurex_100.json` | `f1105b29…` |
  | `data/futurex_results.csv` | `a86781d1…` |
  | `data/futurex_gold.csv` | `08810463…` |

  The two CSVs match the package's `SHA256SUMS.json`. Because the study has no public URL,
  `references.original_harness` and `fingerprint.harness_url` carry the row's declared
  `harness_url` (`benchmarks.py:8108`): the dataset tree at `3c2e3969`, the questions the study
  froze.
- [x] **A verdict never claims more than its evidence.** No core dimension is `unchecked`. The
  measured grading bound is 0. One `possibly-score-changing` sampling deviation is open, so the
  verdict is `unverified`.
- No `ours` override was set.

1. **History.** `55d7f087f fix(screamingface-engine): read only whole plain numbers in FutureX-Past`,
   `659d251c7` (the Fidelity Records), `93d427296` (the rebased `abb05ea9b`), `4a13cc636`,
   `b0a7d3127`, on top of `cc5cfd36d`. `git diff --quiet 93d427296..HEAD -- futurex_past_study.py vendor/`
   reports both unchanged. Against `abb05ea9b` the package diff touches only `README.md` (the
   `futurex_past` number-reading text) and `grading.py` (`to_float`, `number_score`);
   `answer_tokens` is byte-identical and `_BOXED` is not in the diff. `futurex_past_study.py`
   imports only `answer_tokens` from `grading.py` (`:55`). In `benchmarks.py` only
   `published_revision` changed (`:8048`).
2. **Tests.** `uv run --extra inspect pytest tests/unit/inspect/test_local_task_futurex_past_study.py tests/unit/inspect/test_local_task_futurex_past.py tests/unit/inspect/test_futurex_past_grading.py -q -p no:cacheprovider`
   gave `189 passed`.
3. **Our side.** `fingerprint 0d516b151df8c19e judge None params None`;
   `samples 1118 case_digest f59af636… declared f59af636…`; `Sample.input == Case input on all: True`.
   The parquet is `snapshots/3c2e39690de35eb1fcc621251f56343c72bae8c4`, sha256 `55ecf4f1…`.
4. **Prompts and gold**, under 3.11.7 and 3.12.1: `input != futurex_render: []`; both prompt
   sha256 `3a103519…`; `gold/level differ: []`; `fused-medoids 0.3019627378138016`,
   `fused-dissimilar2 0.2715224304851964`.
5. `STUDY_CASES == positions: True`.
6. **Answer sheets**, 31 per item: variants of the gold (gold; upper; lower; spaced; `\text{}`
   wrapper; per-token `\text{}`; worked box then gold; gold then a wrong box; reversed; first token
   only; gold plus an extra; gold with a period; semicolons; ` and `; `\boxed {`; trailing comma),
   wrong or invalid answers (`ZZZ`; `Z`; every option; first option; `Yes`; `No`), hedges and
   fragments (`maybe`; `Unknown`; `x`), and no usable box (empty reply; empty box; comma-only box;
   boxless prose; two-level nesting; unclosed). Results:
   `synthetic 3100 {'both score, identical': 1398, 'both drop': 1702}` (study drops:
   uninterpretable 1,102, no answer 600); `stored 2697 {'both score, identical': 2659, 'both drop': 38}`
   (no_answer 23, uninterpretable 15).
7. **Vectors.** all-1, all-0, alternating (`0.4555787740628166`), every-3rd-0.8
   (`0.2763019250253293`) exact on both sides; mixed-unusable `0.44908424908424904` on both;
   first-10-abstained `0.4501860712387028` as expected.
8. **Models.** 27 of 27 equal to the kit under 3.12; largest gap to the kit under 3.11
   `5.551115123125783e-17`. fused-medoids `0.3019627378138016` and fused-dissimilar2
   `0.2715224304851964`, equal on both sides.
9. **Greps** (`grep -n` / `cat -n` / `sed -n`). Ours: `grading.py` `70,112`; `futurex_past.py`
   `128,243`; `benchmarks.py` `8047,8048,8070,8108,8121`; `README.md` `120,131,135,184,189,193`;
   `futurex_past_study.py` `66-67,71-78,81-88,106-120,136-138,144-149,152-167,178`;
   `vendor/study_formats.py` `48,204`; `scorer_adapter.py` `608-633`. Study (unchanged, hashes
   equal): `bench_formats.py` `35-39`; `run_openrouter.py` `340,997`; `umbc_verdict.py:69`;
   `llm_api.py:341`; `corpus.py` `27-33`; `rank.py` `84-87,159-175`; `build_data.py:89`;
   `PROVENANCE.md:8`; `main.tex` `630-642`; `fused_committee.py` `174-175,198`.
10. **After.** `git status --porcelain | wc -l` gave `0`; no `.pyc` in the study package; scratch
    deleted.

## Recommended paid runs

None: there is no judge. What is pending is a **Report read** on any replication run over the 100
study positions. Confirm `temperature: 0` in the Candidate's params, and count the Cases with a
truncated finish reason. If there are none, that run's headline is the study examiner's to the
last bit, and the record can be re-issued as `comparable-to-paper` on that evidence. Cases marked
`study_usable: false` in the Report need no action: the study dropped those too.

## Upstream notes

- **The study and its paper agree on the denominator** (`study:5_paper/main.tex:630-642`;
  `study:3_results_report/committee_kit/rank.py:159-167`).
- **A committee tie is a Candidate-side difference, now declared** (`README.md:189-193`). The
  study scored a committee tie 0 and kept it (`rank.py:84-87`); each fused committee tied on 2
  questions. A ScreamingFace fusion answers on a tie, which can move the headline by between 0 and
  +0.0071 (2 level-1 Cases). Grading is the study's either way. This record does not verify the
  fusion's tie rule.
- **The study is not consistent with itself on a fused tie.** Its `run_benchmark` writes a tie as
  `excluded=True, "no fused answer"` (`fused_committee.py:174-175`), which the kit would drop. Its
  `replay`, which produced the published 0.302, keeps the tie as 0. This record follows `replay`.
- **The study's `no_answer` label came from its completeness reviewer, not from a parse.** Our
  gate (no tokens means unusable) reproduces all 23 such cells, because every one has an empty
  answer. A future corpus where the reviewer flags a boxed reply would need a re-check.
- **The gate saw rebuilt boxes, not the originals.** The 2,697 stored replies were rebuilt from
  stored tokens (`", ".join`), so `interpret_answer` judged the rebuilt box rather than the
  original raw box. All 38 exclusions and all 2,659 inclusions still agree.
- **An unusable Case still shows a per-Case value.** Its value is the study's `item_score` of its
  tokens, so the scorer's per-Case `mean()`/`stderr()` (`futurex_past_study.py:123`) include it;
  only the `study_tier_weighted` headline leaves it out. Declared in `README.md:135-136`.
  Cosmetic, bound 0.
- **[inspect_evals](https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0) has no FutureX
  eval** and is not a reference. Futurex-Eval@2626f7a2 is `futurex_past`'s reference, not this
  Benchmark's.
