# PRD: Concatenate, do not rewrite

**Source:** prompt (OME-1289 §7), ans:Q1 · **Priority:** P1 (ships with Rank)
**Lifecycle:** planned
**Owner:** unassigned
**Uses:** [reducer-slot.md](reducer-slot.md), [operator-framework.md](operator-framework.md),
[rank-keep-k.md](rank-keep-k.md) (the same "selection must be followed" rule)

## 1. Summary and user story

As a researcher, I want the next stage to receive every member's original text, joined in author
order with visible boundaries, so that a multi-document hand-off does not go through a model that
summarizes. `[stated prompt]`

## 2. Background and constraints

- "No model call." `[stated prompt]`
- "Order is the member order in the recipe." `[stated prompt]`
- "The next stage receives that string and can see the boundaries." `[stated prompt]`
- "Ship it with rank." `[stated prompt]`

**API** `[proposed]`: `sf.Concat(separator="\n\n---\n\n", label=True)`. With `label=True`, each
part starts with `[member_i]` on its own line.

**Rule** `[proposed]`: like Rank, a Concat result is `kind = selection`. It must be followed by a
Pipeline stage. The ticket says the output is "for the next stage", so a Concat at the end of a
candidate is a compile error.

## 3. Scenarios and acceptance criteria

### 3.1 Happy path

**CC-H1 Join in author order.** `[stated prompt]`
Given members "A", "B", "C" and the default separator,
When the Concat runs,
Then the next stage gets `[member_1]\nA\n\n---\n\n[member_2]\nB\n\n---\n\n[member_3]\nC`.

**CC-H2 No labels.** `[proposed]`
Given `label=False`,
When the Concat runs,
Then the text is `A\n\n---\n\nB\n\n---\n\nC`.

### 3.2 Error paths

**CC-E1 Concat at the end.** `[proposed]`
Given a candidate whose last step is a Concat Fusion,
When it compiles,
Then `ValueError` says that a Concat must be followed by another stage.

**CC-E2 Separator inside a member.** `[proposed]`
Given a member text that contains the separator,
When the Concat runs,
Then the text is joined unchanged, and the evidence flags `separator_collision = true` so that a
reader knows the boundaries are not unique.

**CC-E3 Empty separator.** `[proposed]`
Given `separator=""`,
When the Fusion is built,
Then `ValueError` is raised (the boundaries would not be visible).

### 3.3 Derived scenarios (risk order)

| ID | Title | Tag | I×L | Given / When / Then |
|---|---|---|---|---|
| CC-D1 | Empty member text | [proposed] | M×M | Given member 2 is "", when the Concat runs, then its part is present and empty, and the order is kept. |
| CC-D2 | Size | [proposed] | M×L | Given the joined text is over 8 MiB, when the Concat runs, then it fails with `combine_input_too_large`. |
| CC-D3 | Concat as a Fusion member | [proposed] | M×L | Given a Concat Fusion used as a member of another Fusion, when it compiles, then `ValueError` is raised (same rule as Rank). |

## 4. Non-functional requirements

- O(total length) `[implied]`.

## 5. Out of scope

- Summaries or truncation of members `[stated prompt]`.

## 6. Open questions

None.

## 7. TDD plan (outside-in)

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| CC-1 | `concat_joins_in_author_order_with_labels_and_separator` | unit | [stated prompt] | H×M | `join@1` + `all@1` |
| CC-2 | `concat_makes_no_model_call` | unit | [stated prompt] | H×L | pure route |
| CC-3 | `concat_at_end_or_as_member_raises_at_compile` | unit | [proposed] | M×M | shared selection check |
| CC-4 | `separator_collision_is_flagged` | unit | [proposed] | M×M | substring check |
| CC-5 | `empty_separator_raises` | unit | [proposed] | L×M | constructor check |
| CC-6 | `empty_member_keeps_its_slot` | unit | [proposed] | M×M | no filter |
| CC-7 | `joined_text_over_cap_fails` | unit | [proposed] | M×L | size check |
