# PRD: Weighted vote with constant weights

**Source:** prompt (OME-1289 §3), ans:Q1 · **Priority:** P1
**Lifecycle:** planned
**Owner:** unassigned
**Uses:** [reducer-slot.md](reducer-slot.md), [operator-framework.md](operator-framework.md),
[answer-operators.md](answer-operators.md), [combine-evidence.md](combine-evidence.md).
The tally rules are the same as in [majority-vote-and-median.md](majority-vote-and-median.md),
with one change: each vote adds a weight, not 1.

## 1. Summary and user story

As a researcher, I want each member's vote to count with a weight that I set in the recipe, so that
I can express methods such as MSLEF that trust some models more. `[stated prompt]`

## 2. Background and constraints

- "Author supplies a weight per member, positive." `[stated prompt]`
- "Each distinct answer's score is the sum of the weights of members who gave it." `[stated prompt]`
- "Return the original text of the highest-weight member among those who gave the winning answer."
  `[stated prompt]`
- "The report shows the weight per member and the summed score per answer." `[stated prompt]`
- "A weight the author did not set is an error before any call, not a silent 1." `[stated prompt]`
- Weights measured during the run are E4b `[stated prompt]`.

**API** `[proposed]`: `sf.Vote(extract=…, normalize=…, weights=[2, 1, 1])`. The list has one
number for each member, in author order. The spec uses `reduce=weighted_mode@1`,
`select=max_weight_holder@1`, and `weights={"member_1": 2.0, …}`.

## 3. Scenarios and acceptance criteria

### 3.1 Happy path

**WV-H1 Weights decide.** `[stated prompt]`
Given the values 9, 9, 12, 12, 12 and the weights 3, 3, 1, 1, 1,
When the vote runs,
Then 9 wins with a score of 6 against 3, the answer is member 1's text, and the agreement is
6/9 ≈ 0.667.

**WV-H2 Highest-weight holder.** `[stated prompt]`
Given the values 9, 9 and the weights 1, 2,
When the vote runs,
Then the answer is member 2's text.

**WV-H3 Evidence.** `[stated prompt]`
Given WV-H1,
When the Report is read,
Then each member reading has its `weight`, and each tally row has its summed `score`.

### 3.2 Error paths

**WV-E1 Missing weight.** `[stated prompt]`
Given three members and `weights=[1, 2]`,
When the Fusion is built,
Then `ValueError` is raised before any call.

**WV-E2 Weight not positive or not finite.** `[stated prompt]`
Given a weight of 0, -1, NaN, or inf,
When the Fusion is built,
Then `ValueError` is raised.

**WV-E3 Spec bypass.** `[proposed]`
Given a hand-written url4 spec with a missing or non-positive weight,
When the endpoint runs,
Then it raises `combine_spec_invalid`.

### 3.3 Derived scenarios (risk order)

| ID | Title | Tag | I×L | Given / When / Then |
|---|---|---|---|---|
| WV-D1 | Tie in the score | [stated prompt] | H×M | Given equal summed scores for two values, when the vote runs, then the value whose first holder is first in author order wins, and `tie = true`. |
| WV-D2 | Tie in the holder weight | [proposed] | M×M | Given two holders of the winner with equal weight, when select runs, then the first in author order is chosen. |
| WV-D3 | Float sums are stable | [proposed] | M×M | Given the weights 0.1, 0.2, 0.3 in any order of summation, when the scores are compared, then they compare as `Decimal` sums from the canonical weight strings, so the result does not depend on order. |
| WV-D4 | Empty extract with weight | [stated prompt] | M×M | Given a member with weight 5 and an empty extract, when the vote runs, then its weight does not count. |
| WV-D5 | Weights with a non-vote reducer | [proposed] | L×M | Given `Median(weights=…)`, when it is built, then `TypeError` says that weights apply to `Vote` only. |

## 4. Non-functional requirements

- Weights are part of the spec, so they are part of the url4 text and of replay identity
  `[implied]`.

## 5. Out of scope

- Weights from signals: confidence, logprobs, perplexity (E4b) `[stated prompt]`.
- MSLEF's "a model writes the field only on conflict" (E4c) `[stated prompt]`.

## 6. Open questions

None.

## 7. TDD plan (outside-in)

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| WV-1 | `missing_weight_raises_before_any_call` | unit | [stated prompt] | H×M | length check in `Vote` |
| WV-2 | `weighted_vote_sums_weights_and_picks_highest_weight_holder` | unit | [stated prompt] | H×M | `weighted_mode@1` + `max_weight_holder@1` |
| WV-3 | `non_positive_or_non_finite_weight_raises` | unit | [stated prompt] | M×M | validation |
| WV-4 | `score_tie_uses_author_order_and_flags_tie` | unit | [stated prompt] | H×M | stable order |
| WV-5 | `weighted_sums_use_decimal_and_are_order_independent` | unit | [proposed] | M×M | `Decimal(str(w))` |
| WV-6 | `endpoint_rejects_spec_with_bad_weights` | unit | [proposed] | M×L | spec validation |
| WV-7 | `evidence_has_member_weights_and_tally_scores` | unit | [stated prompt] | M×M | fields in readings |
| WV-8 | `weights_on_median_raise_type_error` | unit | [proposed] | L×M | constructor check |
| WV-9 | `empty_extract_weight_does_not_count` | unit | [stated prompt] | M×M | status filter before sum |
