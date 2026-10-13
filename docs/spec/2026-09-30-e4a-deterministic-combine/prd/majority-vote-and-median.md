# PRD: Majority vote and median

**Source:** prompt (OME-1289 §1), ans:Q1, ans:Q4, ans:Q8, ans:Q9 · **Priority:** P1 (first flow)
**Lifecycle:** planned
**Owner:** unassigned
**Uses:** [reducer-slot.md](reducer-slot.md), [operator-framework.md](operator-framework.md),
[answer-operators.md](answer-operators.md), [combine-evidence.md](combine-evidence.md)

## 1. Summary and user story

As a researcher, I want to ask N models (or one model N times), read a final answer out of each
text, and return the text of a member who gave the most common answer, so that the join is the
same on every replay, the tally is visible, and no model call is spent on counting.
`[stated prompt]`

## 2. Background and constraints

- "Every member … runs and produces text. Nothing is skipped." `[stated prompt]`
- "For each text, apply the author's `extract` rule, then normalize." `[stated prompt]`
- "Empty extracts do not vote." `[stated prompt]`
- "The Fusion's answer is the original text of one member who holds the winning answer, byte for
  byte." `[stated prompt]`
- "Ties: the first member in author order who holds the winning answer. The report says it was a
  tie." `[stated prompt]`
- "The report includes the tally and the agreement fraction (winner count / number of votes)."
  `[stated prompt]`
- Median: the recipe declares `select="nearest"` (a member) or `select="value"` (the number)
  `[stated ans:Q4]`.
- Free-text answers group only by exact normalized text `[stated ans:Q8]`.
- No votes → the case fails with `combine_no_votes` `[stated ans:Q9]`.

**API** `[proposed]`:

```python
sf.Vote(extract="last_number", normalize="numeric")          # plurality
sf.Median(extract="last_number", select="nearest")            # or select="value"
```

Defaults: `Vote(extract="last_line", normalize="text")` `[proposed]`. `Median` always uses
`normalize="numeric"`, and that cannot be changed `[proposed]`.

Compiled spec (plurality): `extract`, `normalize`, `reduce=mode@1`, `select=first_holder@1`.
Compiled spec (median): `extract`, `normalize=numeric@1`, `reduce=median@1`,
`select=nearest@1|value@1`.

## 3. Scenarios and acceptance criteria

### 3.1 Happy path

**VT-H1 Plurality picks the most common answer.** `[stated prompt]`
Given five member texts whose `last_number` values normalize to 18, 18, 26, 18, 18,
When the vote runs,
Then the answer is member 1's text byte for byte, the tally is `{"18": 4, "26": 1}`, the
agreement is 0.8, and `tie = false`.

**VT-H2 Normalization joins equal values.** `[stated prompt]`
Given the extracts `9`, `9.0`, `12`, `12`, `9.00`,
When the vote runs with `numeric`,
Then 9 wins 3 to 2.

**VT-H3 Median, nearest member.** `[stated ans:Q4]`
Given the values 10, 12, 30,
When `Median(select="nearest")` runs,
Then the answer is the text of the member with 12, and `built = false`.

**VT-H4 Median, the value.** `[stated ans:Q4]`
Given the values 10, 12, 30, 40,
When `Median(select="value")` runs,
Then the answer is the text `21`, `built = true`, and `chosen = []`.

### 3.2 Error paths

**VT-E1 Tie.** `[stated prompt]`
Given the values 7, 9, 7, 9,
When the vote runs,
Then the answer is member 1's text (the first holder of the first tied value in author order), and
`tie = true`.

**VT-E2 Empty extracts do not vote.** `[stated prompt]`
Given `boxed` extracts of `""`, `"5"`, `""`,
When the vote runs,
Then only member 2 votes, the agreement is 1.0 (1 of 1), and the evidence shows two members with
the status `empty`.

**VT-E3 No votes.** `[stated ans:Q9]`
Given no member text that contains a number,
When the vote runs,
Then the case fails with `combine_no_votes`.

### 3.3 Derived scenarios (risk order)

| ID | Title | Tag | I×L | Given / When / Then |
|---|---|---|---|---|
| VT-D1 | Tie break is by author order of the first holder | [stated prompt] | H×M | Given the values 9, 7, 7, 9, when the vote runs, then member 1 wins (9 is held first), and `tie = true`. |
| VT-D2 | A member call fails | [implied] | H×M | Given one member route raises a provider error, when the Fusion runs, then the candidate fails the same way that a model-synthesizer Fusion fails today. E4a does not skip members (skipping is E4c). |
| VT-D3 | Median ignores non-numbers | [proposed] | M×M | Given the values 4, "n/a", 8, when the median runs, then the median is 6, and member 2 has `not_numeric`. |
| VT-D4 | Median with one value | [proposed] | M×L | Given one numeric member, when `Median(select="nearest")` runs, then that member is chosen, and the agreement is 1.0. |
| VT-D5 | Median agreement | [proposed] | L×M | Given the values 9, 9, 12 and `select=nearest`, when the median runs, then the agreement is 2/3 (voters equal to the chosen value / numeric voters). |
| VT-D6 | Free text exact match | [stated ans:Q8] | M×M | Given `last_line` answers "Paris.", "paris", "Paris, France", when the vote runs with `text`, then "paris" wins 2 to 1. |
| VT-D7 | Single member | [proposed] | L×L | Given a Fusion with one member, when the vote runs, then that member is chosen with agreement 1.0. |
| VT-D8 | Downstream check sees the member text | [stated prompt] | H×M | Given a GSM8K run, when `/check` runs, then its context is the chosen member's text, not a paraphrase. |

## 4. Non-functional requirements

- No model calls are added by the vote `[stated prompt]`.
- See operator-framework.md for latency and caps.

## 5. Out of scope

- Ranked ballots (Borda, IRV, Condorcet), which are E4e `[stated prompt]`.
- Early stop when the median is stable, which is E4c `[stated prompt]`.
- Image input `[stated prompt]`.

## 6. Open questions

None.

## 7. TDD plan (outside-in: SDK API → compiled spec → endpoint result)

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| VT-1 | `vote_returns_first_holder_text_byte_for_byte_with_tally_and_agreement` | unit | [stated prompt] | H×M | `mode@1` + `first_holder@1` |
| VT-2 | `vote_tie_goes_to_first_holder_in_author_order_and_flags_tie` | unit | [stated prompt] | H×M | stable order |
| VT-3 | `vote_normalization_groups_equal_numbers` | unit | [stated prompt] | H×M | `numeric@1` |
| VT-4 | `empty_extracts_do_not_vote_and_are_reported` | unit | [stated prompt] | M×M | status filter |
| VT-5 | `no_votes_fails_case_with_combine_no_votes` | integration | [stated ans:Q9] | H×M | endpoint error → case failure |
| VT-6 | `median_nearest_returns_member_text` | unit | [stated ans:Q4] | M×M | `nearest@1` |
| VT-7 | `median_value_returns_canonical_number_and_built_true` | unit | [stated ans:Q4] | M×M | `value@1` |
| VT-8 | `median_skips_non_numeric_members` | unit | [proposed] | M×M | status filter |
| VT-9 | `vote_compiles_to_pinned_spec` | unit | [proposed] | M×M | `Vote` → spec |
| VT-10 | `median_rejects_a_normalize_argument` | unit | [proposed] | L×M | fixed normalizer |
| VT-11 | `free_text_vote_uses_exact_normalized_text` | unit | [stated ans:Q8] | M×M | `text@1` |
| VT-12 | `member_failure_fails_candidate_like_model_synthesizer` | integration | [implied] | H×M | no new code; pin the behavior |
| VT-13 | `gsm8k_check_receives_chosen_member_text` | integration | [stated prompt] | H×M | route output is plain text |
| VT-14 | `single_value_median_single_member_vote_and_median_agreement` | unit | [proposed] | L×M | covers VT-D4, VT-D5, VT-D7 |
