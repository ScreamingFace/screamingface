# Spec — FutureX-Past as a local inspect Task

- **Unit:** `futurex-past-local-task` (ledger `docs/work/2026-11-16-futurex-past-local-task.md`)
- **Stack:** `screamingface-engine` (+ one example notebook in `packages/screamingface`, see §9)
- **Ticket:** unfiled. The contributor chose to skip Linear, and the ScreamingFace team agreed.
  No epic, issue or `Refs: OME-N`.
- **Status:** draft for the contributor's approval (2026-11-16)

## 1. What and why

FutureX ([Zeng et al., arXiv 2508.11987](https://arxiv.org/abs/2508.11987)) is a live benchmark
of real-world future-prediction questions. **FutureX-Past**
([`futurex-ai/Futurex-Past`](https://huggingface.co/datasets/futurex-ai/Futurex-Past),
Apache-2.0) is its archive of resolved questions. It is not among the Engine's hosted
Benchmarks, so a fused LLM committee cannot be scored on it today. This unit adds it as a
**local Task** under `screamingface_engine_inspect/local_tasks/futurex_past/`. It is written
in inspect's shape and fed to the existing importer, like MuSiQue
(`docs/adding-an-imported-benchmark.md`, "Importing a local Task").

Two catalogue keys come from one package, both with `origin="screamingface"`:

| Key | Data pin | Grading | For |
|---|---|---|---|
| `futurex_past` | `8299bfa1`, 2,036 questions | the FutureX authors' current rules, with an LLM judge on levels 3–4 (§2–§7) | a score comparable with FutureX's own |
| `futurex_past_study` | `3c2e3969`, 1,118 questions | the contributor's study rules, with no judge (§10) | replicating the study's published numbers |

The study scores differently from the FutureX default, so it gets its own Benchmark (§10). One
Benchmark cannot hold both scorings: the importer drops a judged scorer from any row that has
more than one scorer (`importer.py:_kept_scorers`).

## 2. Case set (decision: all rows)

- Source: `futurex-ai/Futurex-Past`, commit `8299bfa1609dec30f267891a74d76e62902c9d71`, file
  `data/train-00000-of-00001.parquet`, sha256
  `a385ef5e6d9f120afcf495450db702ef1e7575e2c21c77b293fc7cba933336bb`. The loader refuses a
  mismatch. The pin matters because the dataset is re-published weekly.
- **All 2,036 rows**, in file order: level 1 = 659, level 2 = 713, level 3 = 338, level 4 = 326.
  The contributor's 100-question study subset stays a sample one can run; it is not the Case set.
- **Case id.** The dataset `id` is **not unique**: 21 ids cover 119 rows, because a question
  that recurs on different dates keeps its id. Each Case id is `<id>|<end_time>`, with `end_time`
  kept as the raw string. That is the study's own `item_id` format, so a study result and an Engine
  Case line up with no mapping. A test proves all 2,036 ids are distinct.
- `input` = the row's `prompt`, **byte for byte**. FutureX ships a complete prompt that ends in
  its own answer-format block (`\boxed{...}`), so we add nothing: no system prompt, no
  reasoning instruction, no date.
- `target` = the parsed `ground_truth` list.
- `metadata` = `level` (int), `title`, `end_time` (raw), `ground_truth` (parsed list), and `std`
  (kept for the record; see §4.3).
- **Data defect.** One row's `ground_truth` is the string `[Yes]`, which is not a Python
  literal. The official harness turns it into the label `[Yes]`, which nothing can match.
  We read it as `["Yes"]`. This is a **named deviation**, declared on the row and in the README.

## 3. Reading the reply (decision: last `\boxed{}`)

The answer is the content of the **last** `\boxed{...}` in the reply, with one level of nested
braces allowed (`\boxed{\text{...}}`). This is the study's `futurex_parse`. A presentational
`\text{...}` wrapper is removed. The content is split on commas into a list. A reply with no
box has no answer and scores 0, as a missing prediction does in the official harness.

The official harness instead asks an LLM to extract the answer from the reply
(`eval.py:extract_answers`). That is a **named deviation**: a reply without a box can score
there and cannot score here. Every FutureX prompt demands the box.

## 4. Scoring

The FutureX authors publish a scorer, [`Futurex-ai/Futurex-Eval`](https://github.com/Futurex-ai/Futurex-Eval),
pinned here at `2626f7a297cd87c73a45408e23af8d838f5b60e5`. It is the reference for this
Benchmark. **It has no licence**, so it cannot be vendored byte for byte as MuSiQue's scorer
is. We **re-implement its rules** in our own code and write our own judge prompts that make the
same decisions. Each rule's README entry links to the authors' file and line at the pinned
commit. Asking the authors to add a licence would let a later PR vendor the code; that is an
outward action and not part of this unit.

### 4.1 Levels 1–2: rules, no judge (official `estimate_score_level_1_2`)

Each label is normalised: stripped of whitespace and quotes, with a `\boxed{}` or `\text{}`
wrapper removed, a single letter upper-cased, and yes/no turned into `Yes`/`No`.

- One gold label: the score is 1.0 when the predicted list equals `[gold]`, else 0.0.
- Several gold labels: the score is the set F1 of the prediction against the gold set.

### 4.2 Levels 3–4: the judge (decision: judge for all of L3/L4, with routing)

These follow `llm_judge_level_34.py` and `metric_router.py`. The gold is normalised first: a
single string that parses as a number becomes a float.

| Gold shape | Route | Score |
|---|---|---|
| one number | — | if the box text is a clean number (`utils.to_float` rules), use it; otherwise the **judge extracts** the number (averaging when there are several, `None` when there is none). Score = `max(0, 1 − ((ŷ − y)/σ)²)`; `None` scores 0 |
| one non-number | — | the **judge** decides whether the prediction matches the answer, ignoring language and wording: 1.0 or 0.0 |
| several items | **judge router**, once per Case: `ranking` / `unordered_set` / `labels`, with the official contract-conflict short-cut | `ranking`: 1.0 when every option token matches in sorted order or the judge says the lists match position by position; otherwise 0.8 × (judge's overlap count)/k. `unordered_set`: 1.0 on a case-folded set match; otherwise the judge counts one-to-one matches m, and the score is 1.0 when m = k = \|prediction\|, else 0.8 × m/k. `labels`: the level-1/2 rule |

As in the harness, the prediction for a single-item gold is the **first** comma piece of the
box. The harness's other edge behaviours are kept as well. Each one is listed in the README
under "Upstream notes", so a reader can see we copied it on purpose.

**The judge** is the house judge every judged Benchmark here pins,
`screamingface/openrouter/openai/gpt-5.4` (as frames and healthbench do), at temperature 0. It
is called through the existing `judge_until_parsed` redraw helper. The official harness uses
DeepSeek V4 Flash or GPT-4.1, so the judge is a **named deviation**, the same one every other
judged Benchmark here declares. Unlike the official harness, the router decision is not cached
across runs. Each grading run routes each multi-item Case again at temperature 0.

### 4.3 Numeric σ (decision: the official code's rule)

σ = 0.05 × gold, or 0.01 when the gold is 0. This is `eval.py:estimate_score_level_3_4`. The
paper's text says "standard deviation over the past 7 days", and the dataset's `std` column is
filled on only 238 rows. The harness ignores that column, and so do we. The column stays in the
metadata, and the README states the paper/harness disagreement as an upstream note.

### 4.4 Roll-up (decision: tier-weighted headline)

- One scorer, `futurex_score`, gives each Case a value in [0, 1]. Its Score metadata carries
  the `level`, the route, and the judge's redraw count, so a run can be cut per level.
- **Headline** = the paper's overall score: Σ w_L × mean(level L), with w = 0.1/0.2/0.3/0.4
  (`run_weekly_leaderboard.py:LEVEL_WEIGHTS`). It is a Task-level `@metric`, imported with
  `--whole-run-metric honour`, as ARC-AGI-2's is.
- When a run lacks a level (a sample of the Cases), the weights are renormalised over the levels
  present. The official code would count the missing level as 0. With all 2,036 Cases the two
  rules agree; on a subset ours is the study's `tier_weighted`. This is a declared deviation.
- A Case with no metadata (the no-network lane's stand-ins) counts as its own level-less Case,
  so the metric falls back to the plain mean, as ARC's does.

## 5. Generation

`solver=generate()`, with no tools and no retrieval. FutureX was built for **agents with web
search**. FutureX-Past questions resolved between 2026-01 and 2026-11, so a model whose
training data reaches past an event may simply know its outcome. The dataset card itself warns
that FutureX-Past "should not be used to evaluate the live future prediction capabilities of
LLMs". The README and the catalogue row say so plainly: a score here measures closed-book
answering of resolved events, it is contamination-prone, and it is **not comparable to the live
FutureX leaderboard**.

## 6. Failure policy, Draft Feedback, revision

- Failure policy: `withhold`, as the other judged Benchmarks use. A Case whose judge reply stays
  unparseable after redraws is `judge_reply_invalid`, never scored 0.
- Draft Feedback: off. Judge-graded feedback on a forecasting question would leak the answer.
- `published_revision` = the fingerprint on the day it is added (the bump command prints it),
  pinned in `test_published_revisions.py` and `test_benchmark_fingerprints.py`.

## 7. Fidelity

The `sf-benchmark-fidelity` agent audits the finished Task against Futurex-Eval at `2626f7a2`
and the paper, and writes `apps/screamingface-engine/docs/benchmarks-fidelity/futurex_past.md`.
The expected verdict is `not-comparable`, because the judge model differs (as on every judged
Benchmark here). Every other dimension should match or be a declared deviation.

## 8. Out of scope

- BTF-3. It is the next unit, with its own spec. Its headline is already decided: 1 − mean Brier
  (higher is better), with accuracy at 0.5 as a second Named Score.
- Vendoring Futurex-Eval (blocked on a licence).
- Search or tool use for the Candidate.
- Any change to other Benchmarks' rows, revisions or digests.

## 9. Process notes (Linear skipped)

- **Test-table approvals.** A new Benchmark adds one row to several existing test tables:
  declaration, imported-benchmarks family, failure-policy rows and counts, published revisions,
  fingerprints. The append-only gate accepts such edits only through
  `.claude/test-change-approvals/OME-<N>.json`, keyed to a Linear issue, branch and blob pair,
  and written after the owner approves. This is the repo's rule
  (`.claude/scripts/approved_test_changes.py`), and the contributor said to follow it. Because no
  issue is filed, **no approval file is written**. The PR body lists the exact table edits and the
  base and approved blob ids, ready for a maintainer to commit as `OME-<N>.json` once they file
  the issue. Until then, the append-only check is the one expected red gate. Every other gate is
  green.
- **Cross-cutting.** A local Task ships its own example notebook
  (`packages/screamingface/examples/21_futurex_past.ipynb` via `scripts/build_notebooks.py`), so
  the PR touches two components. The PR body says so; no sub-issues are filed.
- Commits are conventional and carry no `Co-Authored-By` line. Nothing is pushed and no PR is
  opened without the contributor's explicit OK.
- The second Benchmark (§10) adds a second row to each per-Benchmark test table and a second
  notebook section. Both go into the same PR and the same drafted approval manifest.

## 10. `futurex_past_study` — the study's scoring, for replication

The contributor's study ("behavior-aware LLM crowds for future prediction") reports FutureX-Past
scores with its own deterministic rules. Its best committee scored **0.302**. This Benchmark lets
anyone rerun those numbers on ScreamingFace.

### 10.1 Data

- Commit `3c2e39690de35eb1fcc621251f56343c72bae8c4` (2026-08-02), file
  `data/train-00000-of-00001.parquet`, sha256
  `55ecf4f11909d412d515eeeab5b5891012adde4ff4353d35204179728704ad50`. It holds 1,118 rows:
  level 1 = 423, level 2 = 453, level 3 = 117, level 4 = 125. This commit has no `std` or
  `std_reason` columns, and `level` is an integer. The shared loader handles both schemas.
- **Why this commit.** It is the latest one that holds all 100 of the study's questions
  (`1_forecasting_prompts/questions/futurex_100.json`). Each question's prompt is byte-identical
  and its gold, after normalisation, is identical. Upstream removed one of the 100
  (`68774e69336fa8003b890146|2026/3/30`) on 2026-08-09, so `8299bfa1` holds only 99.
- Case ids, `input`, `target` and metadata are built exactly as in §2, by the same loader.
- **The study's 100 questions**, as Case positions to pass to
  `sf.evaluate(..., benchmark="futurex_past_study", cases=[...])`. Positions are 1-based, in
  file order, and the SDK accepts at most 1,000 ids:
  `[172, 182, 188, 189, 202, 212, 234, 242, 261, 266, 273, 276, 284, 289, 291, 293, 297, 311, 338, 341, 365, 378, 386, 397, 401, 403, 427, 431, 438, 439, 454, 468, 494, 501, 507, 515, 518, 527, 543, 560, 578, 600, 603, 609, 615, 622, 630, 663, 664, 707, 713, 731, 738, 749, 759, 762, 763, 764, 783, 785, 789, 794, 799, 810, 812, 814, 826, 834, 836, 839, 847, 852, 878, 887, 896, 906, 909, 923, 957, 959, 971, 976, 979, 989, 991, 993, 1006, 1013, 1021, 1035, 1040, 1045, 1056, 1058, 1065, 1068, 1070, 1075, 1107, 1114]`.
  The list goes in the README, in the notebook, and in a test that checks the 100 Case ids equal
  the study's `item_id`s. A run on a subset can't be submitted to the leaderboard; that is the
  SDK's rule, and it is fine for replication.

### 10.2 Reading the reply

The same rule as §3: the last `\boxed{}`, split on commas. This is the study's `futurex_parse`
plus `build_data.py`'s split, which strips each token and drops empty ones. No box means no
answer, which scores 0, the study's "abstention".

### 10.3 Scoring: the study's code, vendored

- The scorer is the study's `committee_kit/metrics.py`, copied **byte for byte** into
  `futurex_past/vendor/study_metrics.py`, with a header that names its source. The file is pinned
  by a sha256 test (`2c94cb74…`), on the musique vendor pattern. Its author is the contributor,
  and it is contributed under the repo's Apache-2.0 licence. The study package carries no
  licence of its own, so the contributor states this in the PR.
- Normalisation: both gold and answer go through the study's `corpus.normalise`, which
  case-folds and collapses whitespace. This one-line function is rewritten in our code with a
  `WHY:` that cites `corpus.py:28`.
- Per Case: `item_score(level, gold, answer)`. Level 1 is ordered list equality, level 2 is set
  F1, and levels 3–4 are `ordered_overlap`: 1.0 for an exact ordered match, else 0.8 × overlap/k.
  This is exact string comparison after normalisation, with no judge and no σ.
- **Headline:** the vendored `tier_weighted`, with weights 10/20/30/40 renormalised over the
  levels present. It is a Task-level `@metric` and is honoured as the whole-run headline. On the
  study's 100 questions, where every level is present, it equals the study's `futurex_score`.
- No judge, so the score is deterministic and grading is free. Failure policy: `withhold`, so a
  Case whose Candidate call fails is left out of the score, never counted as 0. This matches the
  study's `NO_RESPONSE` rule (`metrics.py`: "excludes a missing prediction from the
  denominator").

### 10.4 The replication check

A unit test feeds the study's stored answers through our scorer and metric. These are the
per-model token lists in `3_results_report/data/futurex_results.csv`, with the gold from
`futurex_gold.csv`, and a small fixture of 3 models × 100 items goes in the repo. The test requires
each model's score to equal the study's own `futurex_score` to 0.0 tolerance. A second test runs
the fused-medoids decisions (`4_fused_committee`) and requires **0.302**.

### 10.5 What this Benchmark is not

It is not the FutureX authors' scoring. Free-text and ranking answers are compared as exact
strings, so it scores below `futurex_past` on levels 3–4. The README and the row say so, and point
to `futurex_past` for a FutureX-comparable number. Its fidelity reference is the study's own
code, not Futurex-Eval; the fidelity agent audits it against the study package.

## 11. Amendments during implementation (2026-11-16)

Recorded after the contributor approved this spec. Each one came from the Engine's rules, from
the fidelity audits, or from the code review; the ledger lists them too.

- §4.2 routing: the router sees **every** level-3/4 question, not only list answers, as upstream
  `route_metric` does.
- §6 and §10.3 failure policy: both rows are `coverage_declare`, not `withhold`, because the
  Engine refuses `withhold` with a whole-run metric (OME-1642).
- §3 reading, in `futurex_past`:
  - a whole-box `\text{}` wrapper is removed at levels 1-2 too;
  - LaTeX's `{,}` thousands separator is read as a comma;
  - a number in prose reaches the judge as its first comma piece;
  - option letters reach the rank judge sorted;
  - the router reply is parsed as strictly as upstream's.
  All of these follow upstream.
- §10.2 and §10.3, in `futurex_past_study`: the study did **not** score a reply with no usable
  answer as 0. Its `rank.score_entry` dropped such a cell from both sides of the fraction, and
  its `interpret_answer` decided usability. The study's `bench_formats.py` is now vendored too,
  and the study roll-up leaves such a Case out. The replication test covers all 27 models and
  every one of the study's 38 exclusions.
