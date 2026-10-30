# PRD: Mean and weighted mean reducer (`sf.Mean`)

**Source:** prompt (S3, S4), ans:Q1, ans:Q2, ans:Q3, ans:Q9 · **Priority:** P1
**Lifecycle:** planned
**Owner:** unassigned
Paths: [erd §2, §5, §7](../erd.md) · component: [catalog-and-schema](catalog-and-schema.md)

## 1. Summary and user story

As a benchmark author, I want a Fusion to return the average of the numbers its members propose,
with optional static or confidence weights, so that I can test averaging methods without a model
synthesizer.

Scenarios from the prompt [stated prompt]:

- **S3** "extract number from text -> choose a weighted average with static weights".
- **S4** "extract two number from text -> (verbalized confidence and response) -> choose a weighted
  average with weights being verbalized confidence".

## 2. Background and constraints

- Two operators, not one: `mean@1` and `weighted_mean@1`, the same split as `mode@1` and
  `weighted_mode@1`. [stated ans:Q1] [existing E/combine/operators/reduce.py:57-74]
- A member with a missing or `<= 0` weight is dropped. A dropped member takes no part in the
  result: not in the sum and not as the `nearest` pick. [stated ans:Q2]
- Confidence comes from a JSON reply (`field:confidence`). Free-text confidence is out of scope.
  [stated ans:Q3]
- `select="nearest"` returns the original text of the member nearest the mean. [stated ans:Q9]
- Engine weights already accept authored numbers or one signal key, and give `None` for an unusable
  signal number. [existing E/combine/endpoint.py:407-413]
- The engine reads a signal from a member's JSON reply with `field:<path>`. [existing E/combine/ports.py:446-456]
- Named reducers take `extract` as an operator name. A JSON-field extract needs the block form
  `sf.Reduce(..., extract=sf.Extract("field", path=...))`, the same as `median` today.
  [existing S/reducer.py:520-528] [existing S/blocks.py:246,264-266,523]

## 3. Scenarios and acceptance criteria

SDK forms:

```python
sf.Mean(*, extract="last_number", select="value", weights=None)
# extract: an extract operator name, the same set as sf.Median; normalize is always numeric
# select:  "value" (the mean as text, the default) or "nearest" (the member nearest the mean)
# weights: None, a tuple with one positive number per member, or sf.signal(key)

sf.Reduce("mean", mode="compute" | "select", extract=sf.Extract(...), weights=...)
sf.Reduce("mean", select="value" | "nearest", extract=sf.Extract(...), weights=...)
# block form; "compute" (default) = select "value", "select" = select "nearest".
# select= is a second name for mode= (playground fix, 2026-10-14). Give one of the two.
```

Compile [proposed]: `reducer: "mean"`, `normalize: numeric@1`, `reduce: mean@1` (no weights) or
`weighted_mean@1` (weights), `select: value@1` or `nearest@1`.

**Weight check [proposed — gap §per-element/store].** The engine follows the Vote precedent, not a
new spec rule (the `ReducerRule` docstring says later units add no per-reducer operator rule
[existing E/combine/spec.py:62-63]). `weighted_mean@1` uses the same helper as `weighted_mode@1`:
an answer with no weight and no signals means the spec has no weights, which is
`combine_spec_invalid` [existing E/combine/operators/reduce.py:62-66]. `mean@1` ignores weights,
as `mode@1` does. The SDK always pairs the op with the weights.

**Participants [proposed].** `Reduction` gets `participants: tuple[str, ...] | None = None`.
`weighted_mean@1` sets it to the members with a usable weight. `nearest@1` picks only from
`participants` when it is set, and from all voters when it is `None`, as today. `mean@1` leaves it
`None`. [stated ans:Q2] [existing E/combine/operators/select.py:81-102]

### 3.1 Happy path

- **MN-1** Given 3 members that reply `"x = 10"`, `"x = 20"`, `"x = 60"` and `sf.Mean()`, when the
  Case runs, then the answer is `"30"`. [stated prompt]
- **MN-2** (S3) Given the same replies and `sf.Mean(weights=(1, 1, 2))`, then the answer is
  `(10 + 20 + 120) / 4 = "37.5"`. [stated prompt]
- **MN-3** (S4) Given JSON replies `{"answer": 10, "confidence": 0.2}` and
  `{"answer": 20, "confidence": 0.8}`, and
  `sf.Reduce("mean", extract=sf.Extract("field", path="answer"), weights=sf.signal("field:confidence"))`,
  then the answer is `(2 + 16) / 1.0 = "18"`. [stated prompt] [stated ans:Q3]
- **MN-4** Given MN-1 with `select="nearest"`, then the answer is the original text of the member
  nearest 30, which is `"x = 20"`. [stated ans:Q9]
- **MN-5** Given any mean call, then the evidence has `reducer: "mean"`, `mean: "<value>"`,
  `median: null`, and one member row each with its `value` and `weight`. [proposed]

### 3.2 Error paths

- **MN-E1** Given `weighted_mean@1` and a member whose `field:confidence` is `0`, negative, absent,
  or not a number, then that member is dropped and the mean uses the others. [stated ans:Q2]
- **MN-E2** Given every member dropped (no value, or no usable weight), then the Case abstains with
  reason `no_votes`, and the Case scores 0 on every score. [stated ans:Q2] [existing E/combine/endpoint.py:280-303]
- **MN-E3** Given `sf.Mean(weights=(1, 2))` on a 3-member Fusion, then the SDK raises `ValueError`
  before any call. [existing S/reducer.py:292-298]
- **MN-E4** Given `sf.Mean(weights=sf.signal("score:judge"))`, then the SDK raises `ValueError`
  ("no judge"), the same rule as Vote without `judge=`. [existing S/reducer.py:112-118]

### 3.3 Derived scenarios (risk-ordered)

- **MN-D1** (H×H) [proposed — gap §cross-cutting/performance] Given replies 1, 1, 2, then the answer
  is `"1.333333333333333333333333333333333"` (34 significant digits, `ROUND_HALF_EVEN`), not a
  1000-digit text.
- **MN-D2** (H×H) [stated ans:Q2] Given `weighted_mean@1` with `select="nearest"`, and a dropped
  member whose value equals the mean, then the dropped member is not picked. The pick is the nearest
  member among the participants.
- **MN-D3** (H×M) [proposed] Given a `weighted_mean@1` spec with no `weights`, then the result is
  `combine_spec_invalid`. Given a `mean@1` spec with `weights`, then the weights are ignored.
- **MN-D4** (H×M) [implied] Given a member that failed or whose reply has no number, then it is not
  in the mean. This is the same as median. [existing E/combine/operators/reduce.py:83-90]
- **MN-D5** (M×M) [proposed] Given authored float weights such as `0.1`, then each becomes
  `Decimal("0.1")` through `str()`, so the result is the same on every platform.
  [existing E/combine/endpoint.py:413]
- **MN-D6** (M×M) [implied] Given one usable member, then the answer is that member's value.
- **MN-D7** (M×M) [implied] Given negative values and values with many decimals (the 64-character
  cap of `numeric@1`), then the sum is exact in `DECIMAL_CONTEXT` and only the division is rounded.
- **MN-D8** (M×L) [implied] Given `select="nearest"` and two members at the same distance from the
  mean, then the first member in author order wins and the evidence has `tie: true`.
  [existing E/combine/operators/select.py:91-102]
- **MN-D9** (M×L) [proposed] Given confidences on mixed scales (one member writes 80, another
  0.8), then the mean is skewed. The engine does not detect this. The README tells authors to ask
  every member for the same scale.
- **MN-D10** (L×L) [implied] Given the same spec and replies twice, then the result is
  byte-identical (replay determinism). [existing E/combine/ports.py:3]

## 4. Non-functional requirements

- **Cost.** O(n) for n ≤ 256 members, with no model call. [existing E/combine/spec.py:48]
- **Determinism.** Decimal arithmetic only, with no float in the result path. [proposed]
- **Observability.** The evidence shows each member's weight (`null` when dropped) and the mean.
  [proposed]

## 5. Out of scope

- Confidence from free text (G2). [stated ans:Q3]
- Weights from the judge score (`score:judge`) for `Mean`. [proposed]
- A JSON-field `extract` on the named `sf.Mean` (use the block form). [proposed]
- Trimmed means or other robust means. [proposed]

## 6. Open questions

None.

## 7. TDD plan

Order: core-out (engine operator, then the select rule, then the SDK compile, then an engine run of
an SDK-compiled url4).

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| 1 | `mean_rounds_a_repeating_division_to_34_significant_digits` | unit | MN-D1 | H×H | `localcontext(prec=34)` for the division only |
| 2 | `weighted_mean_drops_a_member_with_no_usable_weight` | unit | MN-E1 | H×H | skip `answer.weight is None` |
| 3 | `nearest_after_weighted_mean_never_picks_a_dropped_member` | unit | MN-D2 | H×H | `Reduction.participants`; `nearest@1` reads it when set |
| 4 | `weighted_mean_with_no_usable_member_raises_no_votes` | unit | MN-E2 | H×M | `NoVotes(reason="no_votes")` |
| 5 | `mean_returns_the_plain_average_as_statistic` | unit | MN-1 | H×M | `Reduction(statistic=sum/n)` |
| 6 | `weighted_mean_returns_sum_wx_over_sum_w` | unit | MN-2 | H×M | Decimal sums in `DECIMAL_CONTEXT` |
| 7 | `weighted_mean_without_spec_weights_is_spec_invalid_and_mean_ignores_weights` | unit | MN-D3 | H×M | reuse `_signal_weight` |
| 8 | `mean_skips_failed_and_valueless_members` | unit | MN-D4 | H×M | read only `answered` voters |
| 9 | `mean_golden_fixtures_match` (`mean@1.json`, `weighted_mean@1.json`) | unit | CS-D1 | H×M | one golden per id |
| 10 | `nearest_with_no_participants_is_unchanged_for_median` (CHAR) | unit | [existing E/combine/operators/select.py:91-102] | H×M | passes today and after |
| 11 | `nearest_after_mean_returns_the_closest_member_text` | unit | MN-4 | M×M | no change |
| 12 | `nearest_tie_after_mean_goes_to_the_first_member` | unit | MN-D8 | M×L | no change |
| 13 | `float_weight_becomes_its_str_decimal` | unit | MN-D5 | M×M | no change; pins `Decimal(str(w))` |
| 14 | `mean_of_one_usable_member_is_its_value` | unit | MN-D6 | M×M | — |
| 15 | `mean_sum_is_exact_for_negative_and_long_values` | unit | MN-D7 | M×M | sums in `DECIMAL_CONTEXT` |
| 16 | `evidence_for_mean_sets_mean_and_leaves_median_null` | unit | MN-5 | M×M | `_evidence`: `mean=` for reducer `mean`, `median=None` |
| 17 | `sdk_mean_compiles_mean_or_weighted_mean_by_weights` | unit | MN-1, MN-2 | H×M | `_plan` picks the op |
| 18 | `sdk_mean_refuses_a_wrong_weight_count` | unit | MN-E3 | M×M | reuse `_weights_option` |
| 19 | `sdk_mean_refuses_score_judge_weights` | unit | MN-E4 | M×M | reuse `_refuse_judge_signal` |
| 20 | `sdk_reduce_block_mean_compiles_to_the_same_bytes_as_sf_mean` | unit | MN-1 | M×M | `_OPS["mean"]` with modes `compute`, `select`; reuse `_median_extract` |
| 21 | `url4_round_trip_rebuilds_sf_mean_and_the_mean_block` | unit | [existing S/blocks.py:648-664] | M×M | rebuild rows |
| 22 | `engine_runs_sdk_mean_with_static_weights` (recipe S3) | integration | MN-2 | H×M | `run_candidate` with mocked replies |
| 23 | `engine_runs_mean_block_weighted_by_field_confidence` (recipe S4) | integration | MN-3 | H×M | JSON replies; `field:confidence` signal |
| 24 | `mean_is_byte_identical_on_replay` | unit | MN-D10 | L×L | property test over random inputs |
| 25 | `mean_of_equal_weights_equals_plain_mean` | unit | MN-2 | M×L | property test |

MN-D9 has no test: the engine cannot see the author's scale. See test-plan §5.
