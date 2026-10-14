# PRD: Rank, keep k, then a later stage writes

**Source:** prompt (OME-1289 §6), ans:Q1 · **Priority:** P1
**Lifecycle:** planned
**Owner:** unassigned
**Uses:** [reducer-slot.md](reducer-slot.md), [operator-framework.md](operator-framework.md),
[judge-pick.md](judge-pick.md) (scores), [combine-evidence.md](combine-evidence.md)

## 1. Summary and user story

As a researcher, I want to order the members, keep only the top k original texts, and give exactly
those k to the next stage, so that "focus on the best three" is enforced and not a request inside
a prompt. `[stated prompt]`

## 2. Background and constraints

- "The rank step's output is a list of member ids of length k, not an answer." `[stated prompt]`
- "A Fusion that ends in a rank is not a finished candidate. It must be followed by another stage."
  `[stated prompt]`
- "k is enforced." `[stated prompt]`
- "Pairwise judgments, if a model made them, are kept in the report even if only the top k
  proceed." `[stated prompt]`
- Ranking by a measured signal is E4b. E4a builds the cut `[stated prompt]`.

**API** `[proposed]`:

```python
sf.Pipeline([
    sf.Fusion(members, synthesizer=sf.Rank(k=2, by=sf.Judge("anthropic/claude-opus-5", returns="scores"))),
    sf.Model("anthropic/claude-sonnet-5", prompt="Write the final answer from these drafts."),
])
sf.Rank(k=2, by_field="score")          # members return JSON with a numeric "score"
```

**Output to the next stage** `[proposed]`: canonical JSON
`{"selected": [{"id": "member_2", "text": "<original>"}, {"id": "member_4", "text": "<original>"}]}`
in rank order. The evidence has `kind = selection` and `chosen = ["member_2", "member_4"]`.

## 3. Scenarios and acceptance criteria

### 3.1 Happy path

**RK-H1 Top 2 by judge scores.** `[stated prompt]`
Given four members and the scores 0.1, 0.8, 0.3, 0.9,
When `Rank(k=2, by=Judge(...))` runs,
Then the next stage gets exactly members 4 and 2, in that order, with their original texts.

**RK-H2 Top k by field.** `[stated prompt]`
Given JSON members with the `score` values 5, 9, 7,
When `Rank(k=2, by_field="score")` runs,
Then members 2 and 3 continue.

**RK-H3 Judge output is kept.** `[stated prompt]`
Given RK-H1,
When the Report is read,
Then `op_judge_1.output` and the parsed scores for all four members are present.

### 3.2 Error paths

**RK-E1 Rank at the end.** `[stated prompt]`
Given a candidate whose last step is a Fusion with Rank,
When it compiles,
Then `ValueError` says that a Rank must be followed by another stage.

**RK-E2 k out of range.** `[stated prompt]`
Given k = 0, or k greater than the member count,
When the Fusion is built,
Then `ValueError` is raised.

**RK-E3 Fewer usable members than k.** `[proposed]`
Given k = 3 and only 2 members with a usable score (`by_field`),
When the rank runs,
Then the case fails with `combine_no_votes` (the cut cannot be met).

### 3.3 Derived scenarios (risk order)

| ID | Title | Tag | I×L | Given / When / Then |
|---|---|---|---|---|
| RK-D1 | Rank as a member of another Fusion | [proposed] | H×M | Given a Rank Fusion used as a member of a vote Fusion, when it compiles, then `ValueError` is raised. A selection goes only to a following Pipeline stage. |
| RK-D2 | Ties at the cut | [stated prompt] | M×M | Given scores 0.9, 0.5, 0.5 and k = 2, when the rank runs, then member 2 is kept (author order), and `tie = true`. |
| RK-D3 | Next stage sees nothing else from the panel | [stated prompt] | H×M | Given RK-H1, when the next stage's context is built, then it holds the selection JSON only, not `$model_1 …`. |
| RK-D4 | Judge parse failure | [stated prompt] | H×M | Given bad scores, when the rank runs, then it fails as in judge-pick.md JG-E3. |

## 4. Non-functional requirements

- The selection JSON holds k texts, so its size is at most the sum of k member outputs
  `[implied]`.

## 5. Out of scope

- Scores measured during the run (E4b) `[stated prompt]`.
- Pairwise tournaments and Bradley-Terry (E4e) `[stated prompt]`.

## 6. Open questions

None.

## 7. TDD plan (outside-in)

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| RK-1 | `rank_at_end_of_candidate_raises_at_compile` | unit | [stated prompt] | H×M | compile check |
| RK-2 | `rank_as_fusion_member_raises_at_compile` | unit | [proposed] | H×M | compile check |
| RK-3 | `top_k_by_judge_scores_passes_k_originals_in_rank_order` | unit | [stated prompt] | H×M | `top_k@1` |
| RK-4 | `next_stage_context_is_selection_only` | unit | [stated prompt] | H×M | Pipeline context |
| RK-5 | `top_k_by_field` | unit | [stated prompt] | M×M | `json_field@1` + `scores@1` |
| RK-6 | `k_bounds_are_enforced` | unit | [stated prompt] | M×M | constructor check |
| RK-7 | `fewer_usable_than_k_fails_with_combine_no_votes` | unit | [proposed] | M×M | voter count |
| RK-8 | `cut_tie_goes_to_author_order` | unit | [stated prompt] | M×M | stable sort |
| RK-9 | `judge_output_and_all_scores_kept_in_report` | integration | [stated prompt] | M×M | evidence |
