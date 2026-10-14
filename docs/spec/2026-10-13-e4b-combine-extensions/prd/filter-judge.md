# PRD: Filter by judge score (`sf.Filter(..., judge=...)`)

**Source:** prompt (S10 variant), ans:Q4, ans:Q9 · **Priority:** P2
**Lifecycle:** existing (characterize + delta)
**Owner:** unassigned
Paths: [erd §9](../erd.md) · component: [catalog-and-schema](catalog-and-schema.md) ·
hand-off: [selection-input](selection-input.md)

## 1. Summary and user story

As a benchmark author, I want to keep only the answers that a third-party judge scores above a
threshold, and then let a model write the final answer from them, so that weak drafts never reach
the writer.

This is the threshold variant of S10 ("third party model gives a score to each -> ... -> keep
top-N"), and the judge counterpart of S9 ("keep >value"). [stated prompt] [stated ans:Q9]

## 2. Background and constraints

- The user selected "Filter by judge score" as an extra. [stated ans:Q9]
- When no member passes, the Filter step abstains, the same as today. [stated ans:Q4] The next
  stage gets `{"input":"<input>","selected":[]}` (overview §6 P12, fix 2026-10-14).
- A bad judge reply fails the Case with `judge_reply_invalid` (permanent), the same as every judge
  path. [existing E/combine/ports.py:121-125]

### 2.1 Current behavior

- `sf.Filter(*, where, extract=None)`. `where` is `sf.matches(...)` or `sf.signal(key) <op> value`.
  [existing S/selection.py:312]
- A comparison on `score:judge` is refused: "Filter cannot read sf.signal('score:judge'): it has no
  judge; use sf.Rank(...)". [existing S/selection.py:279-289] [existing S/reducer.py:112-118]
- `sf.Vote` already pairs `judge=sf.Judge(returns="scores")` with `weights=sf.signal("score:judge")`.
  The pairing rule refuses a lone half. [existing S/reducer.py:319-335]
- The engine `filter@1` threshold form takes any known signal key. For `score:judge`, the endpoint
  reads the numbers from the judge reply through `parse_scores`.
  [existing E/combine/operators/signals.py:99-151] [existing E/combine/endpoint.py:242-246]
- Each member's evidence row records its `signals` and its `score` (for a filter, the pass mark).
  [existing E/combine/endpoint.py:561-571]
- A Filter Fusion must be followed by another stage. [existing S/_evaluation/candidate.py:215-220]

**Delta (SDK only).** `sf.Filter` gets `judge: Judge | None = None`. A `score:judge` comparison
needs a `judge`, and a `judge` needs a `score:judge` comparison (the same pairing rule as Vote).
The compile adds the judge call and `signals: {judge: '$judge_N'}` to the combine context, as Vote
does. The `filter` block in `S/blocks.py` takes the same `judge` option.

## 3. Scenarios and acceptance criteria

### 3.1 Happy path

- **FJ-1** Given
  `sf.Filter(where=sf.signal("score:judge") >= 7, judge=sf.Judge(m, returns="scores", rubric=R))`
  in a Pipeline with a writer Model, and a judge reply `{"member_1": 9, "member_2": 4, "member_3": 7}`,
  then the writer receives `member_1` and `member_3` in author order, and the Case input
  ([selection-input](selection-input.md)). [stated ans:Q9]
- **FJ-2** Given FJ-1, then the evidence names the read signal `score:judge`, and each member row has
  `signals["score:judge"]` and a pass mark (`score` 1 or 0). The judge's raw reply is in the judge
  call's own operation record (`op_judge_N`), not in the combine evidence. [implied]

### 3.2 Error paths

- **FJ-E1** Given no member at or over the threshold, then the Filter step abstains with
  `no_votes`, and its output is the empty envelope `{"input":"<input>","selected":[]}`.
  [stated ans:Q4] [stated ans:Q7]
- **FJ-E2** Given a judge reply that is not strict JSON scores, then the Case fails with
  `judge_reply_invalid`. It does not abstain. [existing E/combine/ports.py:121-125]
- **FJ-E3** Given `where=sf.signal("score:judge") >= 7` and no `judge`, then the SDK raises
  `ValueError` and names `judge=`. [proposed]
- **FJ-E4** Given `judge=` and a `where` that is not a `score:judge` comparison, then the SDK raises
  `ValueError`. [proposed]

### 3.3 Derived scenarios (risk-ordered)

- **FJ-D1** (H×M) [implied] Given a quorum Fusion, then the judge sees the panel, and a member with
  no row is dropped by the Filter (it has no score). [existing S/judge.py:49-55]
- **FJ-D2** (H×M) [proposed] Given `judge=sf.Judge(..., returns="label")` or `order="min"`, then the
  SDK raises `ValueError` (judge-order JO-D1).
- **FJ-D3** (M×M) [implied] Given a url4 with a judge Filter, then the SDK rebuilds
  `sf.Filter(where=..., judge=...)`.
- **FJ-D4** (M×L) [implied] Given a threshold with `<` (keep low scores), then the engine keeps the
  members below it. The judge prompt still says higher is better. Any comparison is allowed.

## 4. Non-functional requirements

- Cost: one judge call for each Case, the same as `Rank(by=Judge)`. [existing S/judge.py:139-142]
- No engine change is expected. Test 1 characterizes it. [implied]

## 5. Out of scope

- One judge call per member (G4). [stated ans:Q10]
- A fallback when no member passes. [stated ans:Q4]

## 6. Open questions

None.

## 7. TDD plan

Order: characterize the engine threshold on `score:judge`, then the SDK delta.

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| 1 | CHAR `engine_filter_threshold_on_score_judge_keeps_passing_members` | unit | [existing E/combine/operators/signals.py:99-151] | H×M | expected to pass today |
| 2 | `sdk_filter_with_judge_compiles_the_judge_call_and_signal` | unit | FJ-1 | H×M | reuse the Vote judge wiring |
| 3 | `sdk_filter_score_judge_without_judge_is_refused` | unit | FJ-E3 | H×M | pairing rule; approved edit of the message pin `test_filter.py:343` |
| 4 | `sdk_filter_judge_without_score_judge_where_is_refused` | unit | FJ-E4 | M×M | pairing rule |
| 5 | `sdk_filter_refuses_a_label_or_min_judge` | unit | FJ-D2 | M×M | shared judge check |
| 6 | `engine_filter_by_judge_evidence_has_signal_values_and_marks` | unit | FJ-2 | M×M | no change |
| 7 | `engine_filter_by_judge_with_no_pass_abstains` | unit | FJ-E1 | H×M | the empty envelope (fix 2026-10-14) |
| 8 | `engine_filter_by_judge_with_invalid_reply_fails_permanently` | unit | FJ-E2 | H×M | no change |
| 9 | `engine_filter_by_judge_drops_a_missing_panel_member` | unit | FJ-D1 | H×M | no change |
| 10 | `engine_filter_by_judge_less_than_keeps_low_scores` | unit | FJ-D4 | M×L | no change |
| 11 | `url4_round_trip_rebuilds_a_judge_filter_and_filter_block` | unit | FJ-D3 | M×M | rebuild rows; `_OPS["filter"]` option |
| 12 | `engine_runs_sdk_filter_by_judge_then_writer` (recipe) | integration | FJ-1 | H×M | `run_candidate`, mocked judge reply |
