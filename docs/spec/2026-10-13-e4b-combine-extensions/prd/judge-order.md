# PRD: Judge argmin (`sf.Judge(..., order="min")`)

**Source:** prompt (S11), ans:Q11 · **Priority:** P1
**Lifecycle:** existing (characterize + delta)
**Owner:** unassigned
Paths: [erd §9](../erd.md) · component: [catalog-and-schema](catalog-and-schema.md)

## 1. Summary and user story

As a benchmark author, I want a third-party judge to score each answer where a lower score is
better, and to return the original answer with the lowest score, so that I can use rubrics such as
error count or risk.

Scenario from the prompt: "third party model gives a score to each -> extract all numbers ->
argmin/argmax (use only a model response) -> response from the chosen model". [stated prompt]

## 2. Background and constraints

- With `order="min"`, the judge is told that a lower number means a better answer. [stated ans:Q11]
- The judge still replies with one strict JSON object of finite scores, one per member id. The
  strict parse is the "extract all numbers" step. A reply that is not strict scores fails with
  `judge_reply_invalid` (permanent), the same as today. [existing E/combine/ports.py:121-125,503-518]
- One judge call scores the whole panel. One call per member (G4) is deferred. [stated ans:Q10]

### 2.1 Current behavior

- `sf.Judge(model, *, returns, rubric, params=None)`. `returns` is `"label"` or `"scores"`.
  [existing S/judge.py:119-128]
- `returns="scores"` compiles `reduce: scores@1 {"source":"judge"}` and `select: max_score@1`.
  [existing S/judge.py:90-95]
- The template says "A higher number means a better answer". [existing S/judge.py:69]
- The engine accepts `scores@1` followed by `best_holder@1 {"order":"min"}`. Both read
  `reduction.scores`, both give a tie to the first member in author order, and no spec check
  forbids the pair. [existing E/combine/operators/signals.py:82-96] [existing E/combine/operators/judge.py:95-103]
- The judge tables are keyed by `returns` only: `_JUDGE_STEPS`, `JUDGE_TEMPLATES`,
  `JUDGE_PANEL_TEMPLATES`, `judge_from_signals` and `_parts`. `Judge._key`, `__repr__` and
  `_signal_call` do not know an order. The url4 rebuild matches the steps exactly.
  [existing S/judge.py:90-95,223-229] [existing S/reducer.py:228-234]

**Delta (SDK only).** `sf.Judge` gets `order: Literal["max", "min"] = "max"`. The tables above are
keyed by `(returns, order)`. With `"min"`, the compile gives `select: best_holder@1 {"order":"min"}`,
the template line changes, and the first line gets ` order=min`. `_key`, `__repr__`,
`_signal_call` and the `judge` block in `S/blocks.py` carry `order`. No engine operator changes.

## 3. Scenarios and acceptance criteria

### 3.1 Happy path

- **JO-1** Given `sf.Judge(m, returns="scores", rubric="Count the factual errors.", order="min")`
  and a judge reply `{"member_1": 3, "member_2": 0, "member_3": 1}`, when the Case runs, then the
  answer is the original text of `member_2`. [stated prompt] [stated ans:Q11]
- **JO-2** Given `order="min"`, then the judge system prompt starts with
  `judge-template@1 returns=scores order=min` and says "A lower number means a better answer".
  [stated ans:Q11]
- **JO-3** Given `order="max"` or no `order`, then the compiled bytes are the same as today
  (`max_score@1`, the old template). [implied]
- **JO-4** Given an `order="min"` judge, then the evidence records `returns: "scores"`, the parsed
  scores, the chosen member, and `tie`. [existing E/combine/endpoint.py:521-558,583-588]

### 3.2 Error paths

- **JO-E1** Given `returns="label"` with `order="min"`, then the SDK raises `ValueError`: a label has
  no order. [proposed]
- **JO-E2** Given `order="lowest"` or another value, then the SDK raises `ValueError`. [proposed]

### 3.3 Derived scenarios (risk-ordered)

- **JO-D1** (H×M) [proposed] Given a Judge with `order="min"` used as `Rank(by=...)`,
  `Vote(judge=...)` or `Filter(judge=...)`, then the SDK raises `ValueError`. Those reducers have
  their own `order` or threshold, so a second order would conflict. A "lower is better" rubric can
  therefore be used only with the judge pick. (Scope cut; see overview §7.)
- **JO-D2** (H×M) [implied] Given a url4 that has an `order="min"` judge spec, when the SDK rebuilds
  it, then the result is `sf.Judge(..., order="min")`.
- **JO-D3** (M×M) [implied] Given two members with the same lowest score, then the first in author
  order wins and `tie` is true. [existing E/combine/operators/signals.py:87-96]
- **JO-D4** (M×L) [implied] Given a quorum Fusion (panel form), then the first line is
  `judge-template@1 returns=scores input=panel order=min`. [existing S/judge.py:49-55]

## 4. Non-functional requirements

- No new engine operator and no engine change. [implied]
- Cost: the same single judge call. [existing S/judge.py:139-142]

## 5. Out of scope

- One judge call per member (G4). [stated ans:Q10]
- Free-text judge replies. [stated ans:Q3]

## 6. Open questions

None.

## 7. TDD plan

Order: characterize the engine pair first (it must already work), then the SDK delta.

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| 1 | CHAR `engine_scores_then_best_holder_min_picks_the_lowest_member` | unit | [existing E/combine/operators/signals.py:82-96] | H×M | passes today; pins the engine half |
| 2 | CHAR `sdk_judge_scores_without_order_compiles_max_score` | unit | JO-3 | H×M | passes today |
| 3 | `sdk_judge_order_min_compiles_best_holder_min` | unit | JO-1 | H×H | key the judge tables by `(returns, order)` |
| 4 | `sdk_judge_order_min_tells_the_judge_lower_is_better` | unit | JO-2 | H×H | template variant |
| 5 | `sdk_judge_label_refuses_an_order` | unit | JO-E1 | M×M | check in `__init__` |
| 6 | `sdk_judge_refuses_an_unknown_order` | unit | JO-E2 | M×L | Literal check |
| 7 | `rank_vote_and_filter_refuse_a_min_order_judge` | unit | JO-D1 | H×M | one shared judge check |
| 8 | `url4_round_trip_rebuilds_an_order_min_judge_and_judge_block` | unit | JO-D2 | H×M | rebuild rows; `_OPS["judge"]` option |
| 9 | `judge_order_min_tie_goes_to_the_first_member` | unit | JO-D3 | M×M | no change |
| 10 | `panel_judge_order_min_first_line` | unit | JO-D4 | M×L | template |
| 11 | `judge_key_and_repr_include_order` | unit | JO-3 | M×M | `_key`, `__repr__` |
| 12 | `engine_runs_sdk_judge_order_min_and_returns_the_lowest_member_text` (recipe S11 min) | integration | JO-1, JO-4 | H×M | `run_candidate`, mocked judge reply; assert evidence |
| 13 | `public_surface_lists_judge_order` | unit | [existing ST/public_surface_snapshot.json:494-497] | M×M | approved snapshot edit |
