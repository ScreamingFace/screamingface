---
ticket: OME-1642
status: approved (owner, 2026-10-19 — D1–D6 as recommended)
date: 2026-10-19
related: OME-1039 (failure policy declaration), OME-1037 (refusal status split), OME-1268 (Named Scores), OME-1646 (judge redraw, DRACO reference rule)
---

# Count failed Cases in the score of a mean-score Benchmark

## 1. Problem

The Engine publishes a Benchmark score that is the mean over the **graded** Cases only. A
Case that failed (the provider refused, the call errored, the reply was empty) leaves the
denominator. A Candidate that fails more Cases therefore gets a **higher** score than the same
answers get in the upstream eval, where the failed Case counts as 0.

The effect is largest where the failures are model behavior. On FrontierScience, Anthropic's
content filter declines 24 of 160 Cases for claude-opus-5.5 and 31 for claude-fable-5.1.
These two Candidates rank first and second on the leaderboard only because of this rule.

## 2. What the data says (measured 2026-10-19)

**Local replay, exact.** The published claude-opus-5.5 FrontierScience url4 was replayed on a
local kind stack whose gateway cache holds a copy of the production cache (622,779 rows):

- 300 gateway cache hits, 0 misses, $0.
- Score 0.7396, equal to production. Each of the 160 Case results equals the exported
  production Case result (status, grade, failure code).
- Case score sum 100.5855. Over the 136 graded Cases: 0.7396. Over all 160 Cases: 0.6287.

**The 24 failed Cases.** Each has `finish_reason: content_filter`, empty text, and the failure
code `provider_refusal`. The inspect scorer did grade each one: 20 got `0.0` with
`error: empty_completion`, 4 got `I` (incorrect). The Engine dropped all 24 grades. The
prompts are normal science questions (example: Case 7, an optogenetics design task).

**All candidates.** From the OME-1642 attachment (Filip, 2026-10-19; expected = sum of
exported grades / all Cases):

| Benchmark / candidate | Graded / total | Published | All-Case mean | Failure codes |
| --- | --- | --- | --- | --- |
| FrontierScience / claude-opus-5.5 | 136 / 160 | 0.7396 | 0.6287 | provider_refusal ×24 |
| FrontierScience / claude-fable-5.1 | 129 / 160 | 0.7390 | 0.5958 | provider_refusal ×31 |
| FrontierScience / qwen3.8-2.4t-a95b | 156 / 160 | 0.6105 | 0.5952 | model_empty_content ×4 |
| FrontierScience / glm-5.3 | 158 / 160 | 0.5969 | 0.5894 | model_token_cap ×2 |
| FrontierScience / sota_cheap_synth | 159 / 160 | 0.6855 | 0.6813 | upstream_error ×1 |
| GDPval-text / sota_cheap_synth | 101 / 102 | 0.8144 | 0.8064 | 1 failed |
| GDPval-text / external_synth_trio (unpublished) | 98 / 102 | 0.8259 | 0.7935 | 4 failed |

8 of the 14 FrontierScience candidates have at least one failed Case. The other 6 have none,
and their scores do not change under this spec.

## 3. Root cause

Three rules work together:

1. **Refusal → failed Case.** `world/model_response.py:56` reports `content_filter` (or a
   non-null `refusal`) as `provider_refusal`. `benchmarks/aggregation.py`
   `refusal_case_result` (:262) makes a textless refusal a failed Case and drops its grade
   (:314; reason in the docstring, :285–290, OME-1037).
2. **Graded subset only.** `finalize_candidate_result` passes only the Cases with a numeric
   grade to the scorer (`aggregation.py:143–146`).
3. **Mean over the subset.** `_accuracy` (`screamingface_engine_inspect/single_shot.py:1186`)
   divides by the number of graded Cases. `_column_means` (Named Scores, OME-1268),
   `_whole_run_tally` (:1217) and medxpert's `_accuracy` (`benchmarks/medxpert/aggregate.py:221`)
   see the same subset.

Each Benchmark declares this as `failure_policy="coverage_declare"`
(`single_shot.py:597`, `medxpert/definition.py:225`). The declared alternative, `withhold`
("the lost sheets count against the candidate: score = earned / all 157",
`benchmarks/definition.py:32–35`), exists in the type but no code implements it. Every
Benchmark declares `coverage_declare` today (OME-1039 made all six builtins uniform).

## 4. Rule (proposed)

- **R1. `withhold` divides by all selected Cases.** For a Benchmark that declares `withhold`,
  the published score is the sum of the numeric Case grades divided by `case_count` (all
  selected Cases). A failed Case adds 0. This is the meaning `definition.py` already gives
  `withhold`; this change implements it.
- **R2. Coverage keeps its meaning.** Coverage stays "numeric Case grades / selected Cases"
  (`contract.py:632`), for both policies. A reader still sees "graded 136 of 160". The
  `definition.py` comment that says coverage "always reads 100%" under `withhold` is corrected.
- **R3. One denominator.** Under `withhold`, each Named Score column uses the same
  denominator as the headline (all selected Cases), so the OME-1268 invariant holds. The
  rule for a column that a graded Case could not fill (published as unknown) does not change.
- **R4. No plausible zero from an outage.** When no Case has a numeric grade, the score stays
  `None` and coverage 0, for both policies (`contract.py:563–567`). An outage never becomes a
  published 0.
- **R5. Case results do not change.** A failed Case keeps status `failed` and its failure
  codes. A content-filter refusal stays `failed / provider_refusal` and keeps its dropped grade
  as audit evidence. Only the reduction changes.
- **R6. A new revision for each switched Benchmark.** `benchmark_revision` does not hash the
  failure policy or the reducer today (`single_shot.py:511–545`). The fingerprint gets the pin
  `failure_policy=withhold` **only** when the policy is `withhold`, with the same conditional
  pattern as the judge pins (OME-1240). Each switched Benchmark gets a new revision. Each
  `coverage_declare` Benchmark keeps a byte-identical revision. The scoreboard ranks only the
  registered revision (`apps/scoreboard/src/scoreboard/scores/store.py:851`), so old and new
  scores never share one board.
- **R7. `coverage_declare` does not change.** Its reduction, coverage and revision stay as
  they are.

## 5. Which Benchmarks switch (decision D2–D4)

| Group | Benchmarks | Policy after this change | Why |
| --- | --- | --- | --- |
| A. Mean of one grade | the single-scorer imported rows (e.g. frontierscience, gsm8k, mmlu, pubmedqa, wmdp_*), and medxpert | `withhold` | The upstream evals count a failed sample as incorrect. medxpert already scores an empty answer 0 (`medxpert/aggregate.py:14–20`). |
| B. Mean with Named Scores | squad, math, musique | `withhold` | Same reduction as A, per column (R3). |
| C. Rubric mean | gdpval-text, frames_oracle | `withhold` | Mean of a 0–1 rubric grade. Filip's GDPval check uses the all-Case mean. |
| D. Reference rule | draco, draco-3pass | `coverage_declare` (no change) | The owner's rule (OME-1646 §6): the DRACO reference leaves error rows out, and the Engine reproduces it. |
| E. A decline is the graded behavior | xstest_unsafe, coconot_original, fortress_benign (`inverted_grade`), strong_reject, and the other refusal-measuring rows (xstest_safe, coconot_contrast, air_bench, cyse4_mitre_frr) | `coverage_declare` (no change) — **D2** | On these Benchmarks a refusal can be the correct answer. Scoring a content-filter decline 0 would punish the behavior the Benchmark rewards. Each row needs its own rule. |
| F. Whole-run metric | arc_agi_2, contracteval, healthbench-professional, ifeval, simpleqa, simpleqa_verified | `coverage_declare` (no change) — **D3** | The metric is not a mean of Case grades (F1, per-task accuracy, clipped mean, pooled instruction accuracy). "A failed Case is 0" needs a per-metric definition (for example, F1 counts it as no predictions). One follow-up unit per metric. |
| G. Open | healthbench-worst30 | **D4** | Its grades can be negative, so 0 is not the worst value. |

The plan stage produces the exact row list from `screamingface_engine_inspect/benchmarks.py`
and pins it in `tests/unit/inspect/test_benchmark_declaration.py`.

## 6. Effect

- FrontierScience (expected, from the exported grades): claude-opus-5.5 0.6287,
  claude-fable-5.1 0.5958, qwen3.8-2.4t-a95b 0.5952, glm-5.3 0.5894. The 6 candidates with
  no failed Case keep their values, on the new revision.
- GDPval-text: sota_cheap_synth 0.8064, member_synth_trio 0.8205.
- Every Group A–C Benchmark gets a new revision (R6). Its current leaderboard rows stop
  ranking on the default board after the new Engine is deployed (D5).
- Benchmarks in groups D–G: no change.

## 7. Out of scope

- Re-scoring or re-running existing leaderboard rows (D5, separate unit). The scoreboard
  stores only the submitted score and cannot recompute it (`PATCH /scores/{id}` edits only
  authors and `paper_url`, `routes/scores.py:504–531`).
- Group E–G per-row rules (follow-up units).
- Retrying a failed infrastructure call. A failed call still fails; under `withhold` it adds 0.
- Two defects found during the investigation, filed separately:
  - The SDK sometimes rejects a successful run with `ValueError: Span end cannot precede start`
    (`packages/screamingface/src/screamingface/events.py:304`; seen in 1 of 3 full replays).
  - A raw url4 replay (`sf.evaluate("<url4>")`) does not admit a dynamically admitted model
    first, so each Case fails "Answering failed" with 0 calls until something calls
    `GET /v1/model-parameters` for that model.

## 8. Verification

- **V1 — reducer.** `withhold`: 3 graded Cases (1.0, 0.5, 0.0) and 1 failed Case → score
  0.375, coverage 0.75. `coverage_declare`, same input → 0.5, 0.75 (today's value).
- **V2 — Named Scores.** Under `withhold`, each column divides by all selected Cases; a column
  a graded Case could not fill stays unknown.
- **V3 — no Case graded.** Both policies → score `None`, coverage 0, no metrics.
- **V4 — contract validator.** `_candidate_outcome` accepts a `withhold` score over all Cases
  and still refuses a scored Candidate with no numeric grade.
- **V5 — declarations.** The declaration test pins the policy of every Benchmark (§5).
- **V6 — revisions.** Each Group A–C revision changes. Each Group D–G revision is
  byte-identical to `origin/main` (a test lists the current values). The FrontierScience
  literal in `test_inspect_frontierscience_benchmark.py:187` is updated.
- **V7 — replay (manual, recorded in the ledger).** On the local kind stack with the
  production cache copy, replay the published FrontierScience candidates and GDPval-text
  `sota_cheap_synth` on the new revision. Expected: every value in §6, all calls cache hits.
  A DRACO replay gives the same score as before.

## 9. Owner decisions

- **D1.** Implement the existing `withhold` value (R1), not a new policy name.
  *Recommended: yes.* The declared meaning already matches the ticket.
- **D2.** Group E (refusal-measuring rows) stays `coverage_declare` in this unit.
  *Recommended: yes*, with a follow-up that decides per row.
- **D3.** Group F (whole-run metrics) stays `coverage_declare` in this unit.
  *Recommended: yes*, with one follow-up per metric.
- **D4.** healthbench-worst30: stay `coverage_declare`, or switch with a failed Case worth the
  scale minimum instead of 0. *Recommended: stay*, decide with group F.
- **D5.** Existing leaderboard rows on a switched Benchmark: re-run each published entry on
  the new revision (a replay from the gateway cache costs about $0: the measured opus replay
  had 0 misses), or leave the old rows off the default board. *Recommended: re-run, as a
  separate unit after deploy.*
- **D6.** Coverage keeps "graded / selected" under `withhold` (R2), not 100%.
  *Recommended: yes.* Infrastructure failures stay visible next to the score.
