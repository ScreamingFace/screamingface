# PRD: Weighted median (`sf.Median(weights=...)`)

**Source:** ans:Q2, ans:Q9 · **Priority:** P2
**Lifecycle:** existing (characterize + delta)
**Owner:** unassigned
Paths: [erd §2, §5](../erd.md) · component: [catalog-and-schema](catalog-and-schema.md) ·
shared rules: [mean](mean.md) §3 (weight check, participants)

## 1. Summary and user story

As a benchmark author, I want a median that gives more say to members I trust more, so that a
robust number-combine can still use static or confidence weights.

## 2. Background and constraints

- The user selected "Weighted median" as an extra. [stated ans:Q9]
- A member with a missing or `<= 0` weight is dropped, and it cannot be the `nearest` pick.
  [stated ans:Q2]
- The weight sources are the same as for Vote and Mean: authored numbers or one signal key.
  [existing E/combine/endpoint.py:407-413]

### 2.1 Current behavior

- `sf.Median(weights=...)` raises `TypeError("weights apply to Vote only")`. [existing S/reducer.py:523-527]
- `REDUCER_RULES["median"]` forbids weights. [existing E/combine/spec.py:79]
- `median@1` sorts the values. With an odd count it takes the middle value. With an even count it
  takes the exact mean of the two middle values. [existing E/combine/operators/reduce.py:83-90]
- `select` is `nearest` (default) or `value`. [existing S/reducer.py:174]
- The block form `sf.Reduce("median", extract=sf.Extract(...))` takes a JSON-field extract.
  [existing S/blocks.py:246,523]

**Delta.** `sf.Median` and the `median` block accept `weights`. With weights, they compile
`reduce: weighted_median@1`. `REDUCER_RULES["median"].weights` becomes `optional`.
`weighted_median@1` uses the weight check and sets `participants`, as in [mean](mean.md) §3.
With no weights, the bytes do not change.

**Delta (playground fix, 2026-10-14).** The `median` block also takes `select="nearest" |
"value"`, the word of `sf.Median`. `select="value"` is `mode="compute"`, and `select="nearest"`
(the default) is `mode="select"`. The block keeps only the mode, so the url4 and the evidence do
not change. Before the fix, the block refused `select=`, and the README "S4, median form"
returned the nearest member's whole JSON reply.

## 3. Scenarios and acceptance criteria

**Definition [proposed].** Sort the participants (members with a usable weight) by value, ascending.
Members with an equal value keep author order. Let W be the sum of the weights. Walk the sorted
members and add each weight. Stop at the first member k where the running sum is `>= W/2`. If the
running sum is exactly `W/2`, the result is `(x_k + x_{k+1}) / 2`. Otherwise the result is `x_k`.
With equal weights, this rule gives the same result as `median@1`.

### 3.1 Happy path

- **WM-1** Given values 10, 20, 60 with weights `(1, 1, 3)`, then the weighted median is `"60"`.
  (W = 5, and the running sums are 1, 2, 5.) [stated ans:Q9]
- **WM-2** Given values 10, 20, 60 with weights `(1, 1, 2)`, then the running sum reaches exactly
  `W/2 = 2` at 20, so the result is `(20 + 60) / 2 = "40"`. [proposed]
- **WM-3** Given `sf.Median(weights=...)` with the default `select="nearest"`, then the answer is the
  original text of the participant nearest the weighted median. [existing S/reducer.py:523-525]
- **WM-4** Given `sf.Median()` with no weights, then the compiled url4 is byte-identical to today.
  [implied]
- **WM-5** Given `sf.Reduce("median", extract=sf.Extract("field", path="answer"),
  weights=sf.signal("field:confidence"), select="value")` and JSON replies 10 (confidence 0.6),
  20 (0.3) and 99 (0), then the answer is `"10"`, the weighted median number, and not the JSON
  reply of a member. [playground fix 2026-10-14]

### 3.2 Error paths

- **WM-E1** Given a member with a weight that is missing or `<= 0`, then that member is dropped.
  [stated ans:Q2]
- **WM-E2** Given every member dropped, then the Case abstains with `no_votes`. [stated ans:Q2]
- **WM-E3** Given a `weighted_median@1` spec with no `weights`, then the result is
  `combine_spec_invalid`. A `median@1` spec with `weights` ignores them. [proposed]

### 3.3 Derived scenarios (risk-ordered)

- **WM-D1** (H×M) [proposed] Given equal weights, then `weighted_median@1` equals `median@1` for any
  input. This is a property test.
- **WM-D2** (H×M) [stated ans:Q2] Given members at 30 (w=1), 50 (w=1) and 40 (confidence 0), then the
  weighted median is `(30 + 50) / 2 = 40`, and `nearest` picks 30 (tie with 50, first in author
  order), never the dropped member at 40.
- **WM-D3** (M×M) [implied] Given duplicate values, then the result does not depend on how the
  duplicates are ordered among themselves.
- **WM-D4** (M×L) [implied] Given one usable member, then the result is its value.

## 4. Non-functional requirements

- O(n log n) for n ≤ 256 members, with no model call. [proposed]
- Same Decimal rules as `median@1`. Division by 2 is always exact. [existing E/combine/operators/reduce.py:89]

## 5. Out of scope

- A weighted median for `Vote`. [proposed]
- Interpolated (continuous) weighted quantiles. [proposed]

## 6. Open questions

None.

## 7. TDD plan

Order: characterize the unweighted median, then build the weighted operator core-out.

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| 1 | CHAR `sdk_median_without_weights_compiles_the_same_bytes` | unit | WM-4 | H×M | passes today |
| 2 | CHAR `median_even_count_is_the_mean_of_the_middle_two` | unit | [existing E/combine/operators/reduce.py:83-90] | H×L | passes today |
| 3 | `weighted_median_takes_the_first_value_past_half_the_weight` | unit | WM-1 | H×M | running sum over sorted participants |
| 4 | `weighted_median_at_exactly_half_is_the_mean_of_neighbors` | unit | WM-2 | H×M | equality branch |
| 5 | `weighted_median_nearest_never_picks_a_dropped_member` | unit | WM-D2 | H×H | set `participants` |
| 6 | `weighted_median_with_equal_weights_equals_median` | unit | WM-D1 | H×M | property test, odd and even counts |
| 7 | `weighted_median_drops_members_with_no_usable_weight` | unit | WM-E1 | H×M | skip `weight is None` |
| 8 | `weighted_median_with_no_usable_member_raises_no_votes` | unit | WM-E2 | H×M | `NoVotes` |
| 9 | `weighted_median_without_spec_weights_is_spec_invalid` | unit | WM-E3 | H×M | reuse `_signal_weight` |
| 10 | `weighted_median_ignores_the_order_of_duplicates` | unit | WM-D3 | M×M | property test |
| 11 | `weighted_median_of_one_member_is_its_value` | unit | WM-D4 | M×L | — |
| 12 | `weighted_median_golden_fixture_matches` | unit | CS-D1 | H×M | `weighted_median@1.json` |
| 13 | `sdk_median_with_weights_compiles_weighted_median` | unit | WM-3 | H×M | remove the `TypeError` (approved edit of `test_signal_weighted_vote.py:32-35`) |
| 14 | `sdk_reduce_block_median_accepts_weights_and_round_trips` | unit | [existing S/blocks.py:246] | M×M | `_OPS["median"]` option, rebuild row |
| 15 | `engine_runs_median_block_weighted_by_field_confidence` | integration | WM-3 | M×M | `run_candidate`, JSON replies |
| 16 | `numeric_block_select_is_a_second_name_for_mode` and the select refusals | unit | WM-5 | H×M | `_numeric_select` in `S/blocks.py` |
| 17 | `recipe_s4_median_value_returns_the_weighted_median_number` | integration | WM-5 | H×M | `recipe_s4_median.url4`, `run_candidate` |
