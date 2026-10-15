# PRD: Rank and cut of a top-k step (`rank`, `cut`)

**Source:** ans:Q1 (epic OME-1290 gap E3) · **Priority:** P1
**Lifecycle:** existing (characterize + delta)
**Owner:** unassigned
Paths: [erd §2, §3, §5](../erd.md) · component: [evidence-schema](evidence-schema.md)

## 1. Summary and user story

As a researcher who cuts a panel to its top k members before a writer, I want the evidence to show
each member's rank, and the k and the order of the cut, so that I can see how far each dropped
member was from the cut.

## 2. Background and constraints

- Epic OME-1290 behavior 3: "The report shows the score and the rank, including members that were
  dropped." "The cut is exact: k survivors, originals, author-order tie break." [stated ans:Q1]
- The words and keys are owned by [evidence-schema](evidence-schema.md).

### 2.1 Current behavior

- `top_k@1` takes `k` (1..256) and an optional `order` (`"max"` default, or `"min"`).
  [existing E/combine/operators/selection.py:55-67]
- It sorts the scored members by score with a stable sort, so equal scores keep author order, and
  it keeps the first k. Fewer than k scored members abstain with `cut_not_met`. `tie` says the cut
  fell inside a group of equal scores. [existing E/combine/operators/selection.py:70-95]
- The evidence writes each member's `score` from the reduce step, also for members that were not
  kept. [existing E/combine/endpoint.py:578-588]
- The evidence has no rank, no `k` and no `order`. `operators` lists only the operator ids.
  [existing E/combine/evidence.py:111-137]

**Delta.**

1. `OperatorDescriptor` gets two select-only hooks, `ranks` and `cut`, that the catalog does not
   publish. `top_k@1` sets both. [proposed]
2. `top_k@1` and its `ranks` hook use one shared ordering function, so the rank and the cut can
   never disagree. [proposed]
3. The endpoint writes `rank` on each scored member and `cut` on the evidence, also when the step
   abstains with `cut_not_met`. [stated ans:Q1]

**Definition [proposed].** The rank is the 1-based position of a member in the `top_k@1` order:
scored members only, sorted by score (`order="max"`: high first; `"min"`: low first), equal scores
in author order. Each member has a different rank (ordinal ranking). A member with no score (it
failed or was excluded) has no rank.

## 3. Scenarios and acceptance criteria

### 3.1 Happy path

- **RK-1** Given `sf.Rank(2, by_signal=sf.signal("cost_usd"), order="min")` and costs member_1
  0.03, member_2 0.01, member_3 0.02, member_4 0.01, then the ranks are member_2 1, member_4 2,
  member_3 3, member_1 4; `chosen` is `[member_2, member_4]`; `tie` is false; `cut` is
  `{"k": 2, "order": "min"}`. [stated ans:Q1]
- **RK-2** Given `sf.Rank(2, by_signal=...)` with the default order and scores member_1 0.9,
  member_2 0.5, member_3 0.5, then the ranks are 1, 2, 3, `chosen` is `[member_1, member_2]`,
  `tie` is true, and `cut` is `{"k": 2, "order": "max"}` (the default is written).
  [stated ans:Q1] [existing E/combine/operators/selection.py:94]
- **RK-3** Given `sf.Rank(1, by=sf.Judge(...))` with judge scores 7, 9, 8, then the ranks are
  3, 1, 2 and `cut` is `{"k": 1, "order": "max"}`. [stated ans:Q1]

### 3.2 Error paths

- **RK-E1** Given `k=3` and only two scored members, then the step abstains with `cut_not_met` (as
  today), the two scored members have ranks 1 and 2, and `cut` is `{"k": 3, ...}`. [stated ans:Q1]
- **RK-E2** Given a member with no score (failed, or excluded by
  [member-exclusion](member-exclusion.md)), then its record has no `rank` key. [proposed]

### 3.3 Derived scenarios (risk-ordered)

- **RK-D1** (H×M) [implied] Given any `top_k@1` step that answered, then `chosen` equals the members
  with `rank <= cut.k`, in rank order (CE-I2). This is a property test.
- **RK-D2** (H×M) [implied] Given every step that is not `top_k@1` (`kept@1`, `best_holder@1`, a
  vote), then no record has `rank` and the evidence has no `cut`, so its bytes do not change.
- **RK-D3** (M×M) [implied] Given `k` equal to the number of scored members, then every scored
  member is chosen, and the last rank equals k.
- **RK-D4** (M×L) [implied] Given all scores equal, then the ranks follow author order.
- **RK-D5** (M×L) [implied] Given the reduce step abstains (no member has a score), then no record
  has a rank, and `cut` is still written (the spec asked for it).

## 4. Non-functional requirements

- O(n log n) for n ≤ 256 members; the ranks reuse the one sort of `top_k@1`. [proposed]
- No catalog change: the hooks are not in `GET /v1/operators`. [existing E/combine/ports.py:390-398]

## 5. Out of scope

- A rank for `best_holder@1` (Pick by signal) or for a vote tally. [proposed]
- A `cut` for `kept@1` (the filter threshold or pattern). [proposed]
- Dense or competition ranking. [proposed]

## 6. Open questions

None.

## 7. TDD plan

Order: characterize `top_k@1`, extract the shared ordering, then add the hooks and the evidence.

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| 1 | CHAR `top_k_keeps_author_order_on_equal_scores` | unit | [existing E/combine/operators/selection.py:70-95] | H×M | passes today |
| 2 | `ranks_follow_the_top_k_order_for_min` | unit | RK-1 | H×M | shared `_ranked()`; `ranks` hook |
| 3 | `ranks_and_tie_for_max_with_equal_scores_at_the_cut` | unit | RK-2 | H×M | — |
| 4 | `cut_writes_k_and_the_default_order` | unit | RK-2 | H×M | `cut` hook fills `"max"` |
| 5 | `chosen_equals_members_ranked_within_k` | unit | RK-D1 | H×M | property test |
| 6 | `judge_scored_rank_has_ranks` | unit | RK-3 | M×M | — |
| 7 | `cut_not_met_still_writes_ranks_and_cut` | unit | RK-E1 | H×M | `_evidence` reads the reduction on abstain |
| 8 | `unscored_member_has_no_rank_key` | unit | RK-E2 | M×M | `exclude_if` None |
| 9 | `steps_other_than_top_k_keep_their_bytes` | unit | RK-D2 | H×M | goldens and `evidence_cases.json` |
| 10 | `k_equal_to_scored_count_chooses_all` | unit | RK-D3 | M×M | boundary |
| 11 | `all_equal_scores_rank_in_author_order` | unit | RK-D4 | M×L | — |
| 12 | `reduce_abstain_writes_cut_without_ranks` | unit | RK-D5 | M×L | — |
| 13 | `sdk_reads_rank_and_cut_from_a_rank_run` | integration | RK-1, ES-3 | H×M | `run_candidate` |
