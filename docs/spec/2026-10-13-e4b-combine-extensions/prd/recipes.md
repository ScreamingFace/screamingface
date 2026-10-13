# PRD: Combine recipes for the 11 scenarios (Phase 0 and README)

**Source:** prompt (S1–S11), ans:Q3, ans:Q8 · **Priority:** P0 (existing recipes), P1 (README)
**Lifecycle:** existing (characterize + delta)
**Owner:** unassigned
Paths: component: [catalog-and-schema](catalog-and-schema.md)

## 1. Summary and user story

As a benchmark author, I want one tested recipe for each combine scenario, so that I can copy a
working pattern and trust that it runs end to end.

## 2. Background and constraints

- Proof is offline tests plus a README section. No paid calls and no recorded replay lanes.
  [stated ans:Q8]
- Members reply in JSON when a scenario needs two numbers. Free-text confidence is deferred.
  [stated ans:Q3]
- Lines 5 and 6 of the prompt are the same scenario. This PRD names it S5. [stated prompt]
- A judge reply that is not strict scores fails with `judge_reply_invalid` on every judge path
  (the S10 and S11 recipes too). [existing E/combine/ports.py:121-125]

### 2.1 Current behavior

- R1 (`Median select="value"`) and R2 (`Median` nearest) are covered at compile and evidence level.
  [existing ST/test_vote_median.py:51,69] [existing ET/test_combine_evidence_contract_fixture.py:86-89,169-170]
- R5 and R8 (Pick on `confidence`) are covered at compile and evidence level, but R8 only with
  `order="min"`. [existing ST/test_pick_by_signal.py:40]
- R7, R9 and R10 have no Pipeline test with a writer, except one filter pipeline with `>= 0.6`.
  [existing ET/test_sdk_candidate_contracts.py:155]
- R11 (Judge argmax) has no engine run. [existing ET/test_combine_evidence_contract_fixture.py:98]
- The offline engine-run harness is `run_candidate(url4, {model: (reply, cost)})` with a mocked
  gateway. [existing ET/_signal_world.py:86]
- The SDK writes url4 fixtures to `ET/data/combine_contract/`, with a drift guard.
  [existing ST/test_engine_url4_contract_fixtures.py:107-114]

**Delta.** Add one SDK-compiled url4 fixture and one engine run for each recipe that has no run.
Add a README section "Combine recipes" that maps S1–S11 to code.

## 3. Scenarios and acceptance criteria

Recipe map. "New" means the feature comes from another E4b PRD, and that PRD owns its test.

| S | Prompt line [stated prompt] | Recipe | Owner of the run test |
|---|---|---|---|
| S1 | extract number → median → return the median number | `sf.Median(extract="last_number", select="value")` | this PRD (RC-1) |
| S2 | … → choose the median → return the original model answer | `sf.Median(extract="last_number")` | this PRD (RC-2) |
| S3 | … → weighted average with static weights | `sf.Mean(weights=(…))` | [mean](mean.md) MN#22 |
| S4 | two numbers → weighted average by verbalized confidence | `sf.Reduce("mean", extract=sf.Extract("field", path="answer"), weights=sf.signal("field:confidence"))` | [mean](mean.md) MN#23 |
| S5 | two numbers → response with maximum confidence | `sf.Pick("confidence", order="max")` (full text) or `output="answer"` | this PRD (RC-3); output: [pick-output](pick-output.md) PO#17 |
| S7 | confidence → keep top-N → model synthesizer | `Pipeline([Fusion(…, synthesizer=sf.Rank(k=N, by_field="confidence")), sf.Model(…)])` | this PRD (RC-4) |
| S8 | confidence → argmax → response from model chosen | `sf.Pick(by_signal=sf.signal("field:confidence"), order="max")` | this PRD (RC-5) |
| S9 | confidence → keep >value → model synthesizer | `Pipeline([Fusion(…, synthesizer=sf.Filter(where=sf.signal("field:confidence") > 0.7)), sf.Model(…)])` | this PRD (RC-6) |
| S10 | judge scores each → keep top-N → model synthesizer | `Pipeline([Fusion(…, synthesizer=sf.Rank(k=N, by=sf.Judge(m, returns="scores", rubric=R))), sf.Model(…)])` | this PRD (RC-7) |
| S11 max | judge scores each → argmax → response | `sf.Judge(m, returns="scores", rubric=R)` | this PRD (RC-8) |
| S11 min | judge scores each → argmin → response | `sf.Judge(m, returns="scores", rubric=R, order="min")` | [judge-order](judge-order.md) JO#12 |

### 3.1 Happy path

Each RC row: given an SDK recipe compiled to a url4 fixture and mocked member, judge and writer
replies, when `run_candidate` runs it, then the final answer is the stated value. [stated ans:Q8]

- **RC-1** S1: replies `"… 10"`, `"… 20"`, `"… 90"` → answer `"20"`.
- **RC-2** S2: same replies → answer is the original text of the `"… 20"` member.
- **RC-3** S5: JSON replies with confidences 0.3, 0.9, 0.5 → the original text of the 0.9 member.
- **RC-4** S7: Rank k=2 by `confidence` → the writer receives the envelope with the 2 most confident
  members and the Case input ([selection-input](selection-input.md)), and the answer is the
  writer's reply.
- **RC-5** S8: same as RC-3 through `by_signal` with `order="max"`.
- **RC-6** S9: Filter `> 0.7` with confidences 0.7, 0.71, 0.9 → the writer receives the 0.71 and 0.9
  members. 0.7 is not kept, because `>` is strict.
- **RC-7** S10: judge reply `{"member_1": 2, "member_2": 9, "member_3": 5}`, k=2 → the writer
  receives `member_2` then `member_3` (best first).
- **RC-8** S11 max: the same judge reply → the original text of `member_2`.
- **RC-9** The README section "Combine recipes" lists S1–S11 with the code above and links each new
  feature. It tells authors to ask members for a JSON reply with one confidence scale (see mean
  MN-D9). [stated ans:Q3] [proposed]

### 3.2 Error paths

- **RC-E1** S9 with no confidence above 0.7 → the Case abstains with `no_votes`. [stated ans:Q4]
- **RC-E2** S5 with a member that replies plain text, not JSON → that member has no value and is not
  picked. If no member has a value, the Case abstains. [existing E/combine/operators/fields.py:132]
- **RC-E3** S10 with a judge reply that is not strict JSON → the Case fails with
  `judge_reply_invalid`. [existing E/combine/ports.py:121-125]

### 3.3 Derived scenarios (risk-ordered)

- **RC-D1** (H×M) [proposed] Each recipe fixture has a drift guard. When the SDK compile changes,
  the SDK test fails until the fixture is regenerated, and the engine test runs the new bytes.
- **RC-D2** (M×M) [implied] RC-6 pins the strict `>` boundary at exactly 0.7.
- **RC-D3** (M×L) [proposed] The README examples are the same code as the fixtures. A doc-example
  test compiles them. [existing ST/_fusion_doc_examples.py]

## 4. Non-functional requirements

- No network and no paid call in any RC test. [stated ans:Q8]
- Each engine-run test completes in under 2 s on CI. [proposed]

## 5. Out of scope

- Recorded e2e replay lanes. [stated ans:Q8]
- Example notebooks. [proposed]

## 6. Open questions

None.

## 7. TDD plan

Order: risk-first. The Pipeline recipes (S7, S9, S10) come first, because they cross the most hops
and depend on [selection-input](selection-input.md).

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| 1 | `recipe_s10_rank_by_judge_then_writer_runs_end_to_end` | integration | RC-7 | H×H | new fixture `recipe_s10.url4` |
| 2 | `recipe_s9_filter_confidence_then_writer_runs_end_to_end` | integration | RC-6, RC-D2 | H×H | new fixture; strict `>` at exactly 0.7 |
| 3 | `recipe_s7_rank_by_field_then_writer_runs_end_to_end` | integration | RC-4 | H×H | new fixture |
| 4 | `recipe_s9_with_no_pass_abstains` | integration | RC-E1 | H×M | same fixture |
| 5 | `recipe_s10_with_invalid_judge_reply_fails_permanently` | integration | RC-E3 | H×M | same fixture |
| 6 | `recipe_s11_judge_argmax_returns_the_best_member_text` | integration | RC-8 | H×M | new fixture |
| 7 | `recipe_s8_pick_by_field_signal_max_runs_end_to_end` | integration | RC-5 | M×M | new fixture; `order="max"` |
| 8 | `recipe_s5_pick_confidence_max_runs_end_to_end` | integration | RC-3 | M×M | new fixture |
| 9 | `recipe_s5_plain_text_member_is_not_picked` | integration | RC-E2 | M×M | same fixture |
| 10 | `recipe_s1_median_value_runs_end_to_end` | integration | RC-1 | M×L | new fixture |
| 11 | `recipe_s2_median_nearest_runs_end_to_end` | integration | RC-2 | M×L | new fixture |
| 12 | `recipe_fixtures_match_the_sdk_compile` (drift guard) | unit | RC-D1 | H×M | SDK generator test |
| 13 | `readme_combine_recipes_compile` | unit | RC-9, RC-D3 | M×L | add to doc examples |
