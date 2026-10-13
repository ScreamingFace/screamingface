# PRD: Extract and Reduce blocks (component)

**Source:** PRD "Blocks" (`Extract(rule, normalize)`, `Reduce(op, mode)`), divergence V1 · ans:Q1 ·
**Priority:** P1
**Lifecycle:** existing (characterize + delta) — the reducer classes exist
**Owner:** Ionesio (E4a)

Paths: see [erd.md](../erd.md).

## 1. Summary and the flows it serves

Add the PRD block syntax to the SDK: `sf.Extract(rule, normalize=None, **args)` and
`sf.Reduce(op, mode="select", **options)`. A `sf.Reduce` goes in the Fusion synthesizer slot (the
PRD Fan-out is the Fusion member list `[stated prompt]`). It compiles to the **same** combine
spec, and so the same url4 bytes, as the matching named reducer. `sf.Vote`, `sf.Median`,
`sf.Judge`, `sf.Pick`, `sf.Merge`, `sf.Rank`, `sf.Concat` stay as named shortcuts
`[stated ans:Q1]`.

Flows that use it: every flow PRD in this spec writes its examples in both forms.

## 2. Background and constraints

- "Add `sf.Reduce(op, mode)` and `sf.Extract(rule, normalize)` that compile to the same combine
  call; `sf.Vote` etc. stay as named shortcuts. PRD syntax works, no shipped work is thrown
  away." `[stated ans:Q1]`
- "`mode: select(k)` returns k original Answers; `mode: compute` returns one new Answer with
  `member_id: none`." `[stated prompt]`
- Reduce ops in v1: `plurality`, `weighted`, `argmax`, `top_k`, `filter`, `pick_field`, `concat`
  `[stated prompt]`; plus the E4a extras `median`, `judge`, `merge` `[existing S/reducer.py:242]`.
- The SDK does not export the `Reducer` base on `sf` `[existing S/reducer.py:81]`.

### 2.1 Current behavior

- Each named reducer class builds its own spec and compiles to one url4 combine call
  `[existing S/reducer.py:242]` `[existing S/judge.py:77]` `[existing S/fields.py:433]`
  `[existing S/selection.py:45]`.
- url4 recovery (in `S/url4.py`) rebuilds the named class from the spec; `to_python()` prints it
  `[implied]`.
- The public surface snapshot pins every `sf.*` name `[existing ST/public_surface_snapshot.json:1]`.
- `sf.Reduce` is a `Reducer`, so it triggers the operator catalog fetch and the reducer member cap
  `[existing S/fusion.py:59]`; the `context` op is excluded from both ([fusion-recipe](fusion-recipe.md)).

**Delta.**
1. One internal `ReducerPlan` (spec builder) that both the blocks and the named classes produce.
   The named classes keep their constructors and validation; they build a plan.
2. `sf.Extract` and `sf.Reduce` (new public names) build a plan from the op table in §3.1.
3. Recovery: a recovered spec becomes the named class when one matches exactly, else a
   `sf.Reduce` `[proposed]`.

### 2.2 Op table

| `sf.Reduce(op, …)` | mode | Equal named form | Required options | Optional options |
|---|---|---|---|---|
| `plurality` | select | `sf.Vote(extract, normalize)` | `extract` | — |
| `weighted` | select | `sf.Vote(weights=…)` | `extract`, `weights` (list of floats or `sf.signal`) | — |
| `argmax` | select (one answer) | `sf.Pick(by_signal=…, order=…)` ([signal-reduce](signal-reduce.md)) | `by_signal` | `order` (`max`) |
| `top_k` | select (envelope) | `sf.Rank(k, by=…)`, `sf.Rank(k, by_field=…)`, `sf.Rank(k, by_signal=…)` | `k`, exactly one of `by` / `by_field` / `by_signal` | `order` |
| `filter` | select | `sf.Filter(…)` ([filter](filter.md)) | `where` | `extract` |
| `pick_field` | select | `sf.Pick(field, order \| equals)` | `field` | `normalize` |
| `concat` | compute | `sf.Concat(separator, label)` | — | `separator`, `label` |
| `median` | select or compute | `sf.Median(select="nearest" \| "value")` | `extract` | — |
| `judge` | select | `sf.Judge(model, returns)` | `judge` | `rubric` |
| `merge` | compute | `sf.Merge(fields)` | `fields` | — |
| `context` | compute | (the named Fusion recipe, [fusion-recipe](fusion-recipe.md)) | — | — |

`sf.Extract(rule, normalize)` rules: `boxed`, `last_number`, `field` (path arg), `regex`
(pattern arg), `last_line`, `whole`, `json`, `benchmark`, `inspect_number`, `inspect_aime`;
normalizers: `numeric`, `text`, `set`, `inspect_numeric`, `identity`, `None`
`[stated prompt]` `[stated ans:Q5]`.

## 3. Scenarios and acceptance criteria

### 3.1 Happy path

- **BK-1** Given `sf.Reduce("plurality", extract=sf.Extract("last_number", normalize="numeric"))`
  and `sf.Vote(extract="last_number", normalize="numeric")`, when each is compiled in the same
  Fusion, then the two url4 strings are byte-identical. `[stated ans:Q1]`
- **BK-2** Given every row of the op table, when compiled, then its url4 equals the named form's
  url4 (where a named form exists). `[stated ans:Q1]`
- **BK-3** Given `sf.Fusion(sf.samples(m, 5), synthesizer=sf.Reduce("plurality", extract=…))`,
  then the run reproduces self-consistency exactly like `sf.Vote` (A5 in block syntax).
  `[stated prompt]`

### 3.2 Error paths

- **BK-E1** Given `sf.Reduce("plurality")` with no `extract`, then `ValueError` at construction
  names the missing option. `[implied]`
- **BK-E2** Given `sf.Reduce("concat", mode="select")`, then `ValueError`: `concat` is a compute op.
  `[stated prompt]`
- **BK-E3** Given an unknown op `sf.Reduce("mean")`, then `ValueError` lists the v1 ops.
  `[implied]`

### 3.3 Derived scenarios (risk-ordered)

- **BK-D1** Option that the op does not take `[proposed]` (M×H): `sf.Reduce("plurality", k=2)` →
  `ValueError` naming the option and the op.
- **BK-D2** Recovery round trip `[proposed]` (H×M): for every op-table row, `url4 → recover →
  compile` returns the same url4; a spec equal to a named form recovers as that named class.
- **BK-D3** `to_python()` round trip `[proposed]` (M×M): `to_python()` of a `sf.Reduce` prints a
  `sf.Reduce(…)` call that rebuilds an equal value.
- **BK-D4** Equality and hash `[proposed]` (M×L): `sf.Reduce` is a frozen value; two equal blocks
  are `==` and hash the same.
- **BK-D5** `sf.Extract("benchmark")` outside an evaluation `[proposed]` (M×M): compile without a
  benchmark → `ValueError` "extract='benchmark' needs a benchmark"; resolution is in
  [grader-parity](grader-parity.md).
- **BK-D6** Public surface `[existing ST/public_surface_snapshot.json:1]` (M×H): the snapshot adds
  `sf.Extract`, `sf.Reduce`, `sf.signal`, `sf.matches`, `sf.Answer`, `sf.Filter`; no other name
  changes.
- **BK-D7** Duplicate members warning `[existing S/_evaluation/candidate.py:641]` (L×M): a `sf.Reduce`
  Fusion warns exactly as a `sf.Vote` Fusion.

## 4. Non-functional requirements

- Compile cost is unchanged (one plan per reducer) `[proposed]`.
- No new engine route; no new url4 node kind `[stated ans:Q1]`.

## 5. Out of scope

- A free-standing `sf.FanOut`: the Fusion member list is the Fan-out `[stated prompt]`.
- Reduce blocks as their own Pipeline stage (they need the members' Answers; url4 stage hand-offs
  stay text, `[stated ans:Q2]`).
- Removing the named classes `[stated ans:Q1]`.

## 6. Open questions

None.

## 7. TDD plan

Characterize the named forms, then build the plan seam, then the blocks.

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| 1 | CHAR: golden url4 for each named reducer (the stack's existing golden contract files) | unit | [existing ST/e2e/test_reducer_golden_contracts.py:158] | — | passes today |
| 2 | `named_reducers_build_a_reducer_plan` (refactor seam; goldens stay green) | unit | delta 1 | H×M | extract the spec builder |
| 3 | `reduce_plurality_compiles_byte_identical_to_vote` | unit | BK-1 | H×H | `sf.Reduce` → plan |
| 4 | `every_op_table_row_matches_its_named_form` (parametrized) | unit | BK-2 | H×H | op table |
| 5 | `reduce_without_required_option_raises_at_construction` | unit | BK-E1 | M×H | per-op required set |
| 6 | `reduce_rejects_mode_the_op_does_not_have` | unit | BK-E2 | M×M | per-op modes |
| 7 | `reduce_rejects_unknown_op_and_foreign_options` | unit | BK-E3, BK-D1 | M×H | closed op set |
| 8 | `recovered_spec_prefers_named_class_else_reduce` | unit | BK-D2 | H×M | recovery table |
| 9 | `reduce_to_python_round_trips` | unit (property over op table) | BK-D3 | M×M | printer |
| 10 | `extract_benchmark_without_benchmark_raises` | unit | BK-D5 | M×M | compile check |
| 11 | `public_surface_adds_only_block_names` | unit | BK-D6 | M×H | regenerate snapshot with `UPDATE_SURFACE_SNAPSHOT=1` |
| 12 | `samples_with_reduce_plurality_runs_self_consistency` | integration (fake transport) | BK-3 | M×M | — |
| 13 | `equal_reduce_blocks_are_equal_and_hash_equal` | unit | BK-D4 | M×L | frozen dataclass |
| 14 | `reduce_fusion_warns_on_duplicate_members_like_vote` | unit | BK-D7 | L×M | reuse `DuplicateMembersWarning` path |
