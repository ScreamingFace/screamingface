# PRD: Pick by a field, merge field by field

**Source:** prompt (OME-1289 §5), ans:Q1, ans:Q12 · **Priority:** P1
**Lifecycle:** planned
**Owner:** unassigned
**Uses:** [reducer-slot.md](reducer-slot.md), [operator-framework.md](operator-framework.md),
[answer-operators.md](answer-operators.md) (`json_field@1`), [combine-evidence.md](combine-evidence.md)

## 1. Summary and user story

As a researcher whose members return JSON, I want to pick the member whose field is the largest,
the smallest, or equal to a value, or to build one JSON object with a rule for each field, so that
structured outputs are joined by declared rules and not rewritten by a model. `[stated prompt]`

## 2. Background and constraints

- "Pick. Read one field from each member. Choose the member whose field is largest or smallest, or
  whose field matches a stated value. The answer is that member's whole JSON, unchanged."
  `[stated prompt]`
- "Merge. Build one JSON object. Each field has its own rule: majority on that field, the max,
  'take it from member B,' or 'let this model write only this field.'" `[stated prompt]`
- "If a member's text is not valid JSON … that member is skipped for field rules and the report says
  so." `[stated prompt]`
- "The merged object contains only the declared fields." `[stated prompt]`
- "Pick reports which field was compared and the value per member." `[stated prompt]`
- The model-written field is in P1 `[stated ans:Q12]`. BioASQ needs list fields that are the union
  of the members' lists `[stated prompt]`.

**API** `[proposed]`:

```python
sf.Pick(field="confidence", order="max")                    # or "min", or equals=<value>
sf.Merge(fields={
    "answer":   sf.FieldRule.majority(normalize="text"),
    "score":    sf.FieldRule.max(),
    "source":   sf.FieldRule.from_member(2),                 # 1-based author position
    "synonyms": sf.FieldRule.union(normalize="text"),
    "summary":  sf.FieldRule.model("anthropic/claude-sonnet-5", prompt="…"),
})
```

**Compile** `[proposed]`:
- Pick → one combine call: `extract=json_field@1(path)`, `select=by_field@1(order|equals)`.
- Merge without a model rule → one combine call: `reduce=field_rules@1(fields)`.
- Merge with model rules → for each model field F:
  1. a combine call `project_F` (`reduce=project_field@1(F)`) that returns
     `{"member_1": <value>, …}` as JSON (`kind = projection`);
  2. a model call `writer_N` with that projection as its context and the author prompt as its
     intent;
  3. the final merge combine call reads `signals: {"writer.F": $writer_N}`, and uses the writer's
     text as the value of F.
  The writer sees only the values of F `[stated prompt]`.

## 3. Scenarios and acceptance criteria

### 3.1 Happy path

**PM-H1 Pick max.** `[stated prompt]`
Given members `{"a": 1, "confidence": 0.4}`, `{"a": 2, "confidence": 0.9}`, `{"a": 3, "confidence": 0.7}`,
When `Pick(field="confidence", order="max")` runs,
Then the answer is member 2's text byte for byte, and the evidence lists the field and the three
values.

**PM-H2 Merge by rules.** `[stated prompt]`
Given three JSON members,
When `Merge` runs with majority, max, from_member, and union rules,
Then the answer is one JSON object with exactly the declared keys. Each value follows its rule,
`built = true`, and the evidence has one `FIELD_READING` for each field.

**PM-H3 Union keeps only member strings.** `[stated prompt]`
Given `synonyms` lists `["MI", "heart attack"]`, `["heart attack", "myocardial infarction"]`,
When the union rule runs,
Then the result is `["MI", "heart attack", "myocardial infarction"]`: the values in first-seen
author order, joined by normalized text, each one written as its first spelling.

**PM-H4 Model-written field.** `[stated ans:Q12]`
Given a `summary` rule that uses a model,
When the case runs,
Then the writer gets only the `summary` values of each member, its text becomes `summary`, and the
other fields follow their function rules.

### 3.2 Error paths

**PM-E1 Member is not JSON.** `[stated prompt]`
Given member 2 replies `Sure! Here it is: …` (not JSON, no fence),
When Pick or Merge runs,
Then member 2 is skipped, the evidence says `not_json`, and the others are used.

**PM-E2 Every member is unusable.** `[stated ans:Q9]`
Given no member gives the field (because of `not_json` or `field_missing`),
When Pick or a majority rule runs,
Then the case fails with `combine_no_votes`.

**PM-E3 from_member out of range.** `[proposed]`
Given `FieldRule.from_member(5)` with three members,
When the Fusion is built,
Then `ValueError` is raised.

### 3.3 Derived scenarios (risk order)

| ID | Title | Tag | I×L | Given / When / Then |
|---|---|---|---|---|
| PM-D1 | Writer failure | [implied] | H×M | Given the writer call fails, when the case runs, then it fails with the existing model error code, and no partial object is returned. |
| PM-D2 | Writer sees one field only | [stated prompt] | H×M | Given a model rule for `summary`, when the writer call is built, then its context holds only the `summary` projection, and the test compares the exact context. |
| PM-D3 | Pick ties | [stated prompt] | M×M | Given equal max values, when Pick runs, then the first member in author order is chosen, and `tie = true`. |
| PM-D4 | Mixed types in a max rule | [proposed] | M×M | Given `score` values 3, "high", 5, when the max rule runs, then the non-numbers are skipped with the status `not_numeric`, and the result is 5. |
| PM-D5 | from_member member is not JSON | [proposed] | M×M | Given from_member(2) and member 2 is `not_json`, when the merge runs, then the field is null, and the evidence says why. The case does not fail. |
| PM-D6 | Merged output is canonical JSON | [proposed] | M×M | Given the same members, when the merge runs twice, then the text is byte-identical (sorted keys, compact separators). |
| PM-D7 | Pick equals with normalization | [proposed] | L×M | Given `equals="yes"` and values "Yes.", "no", when Pick runs with `text`, then member 1 is chosen. |
| PM-D8 | Large JSON | [proposed] | L×L | Given a member JSON over 1 MiB, when it is parsed, then it gets `too_large` and is skipped. |

## 4. Non-functional requirements

- A merge with M model fields adds 2M + 1 calls in the url4 graph: M projections and the final
  merge are pure, and the M writer calls are model calls `[proposed]`.

## 5. Out of scope

- A writer that runs only on conflict (E4c) `[stated prompt]`.
- Planner/executor/critic "take the last stage" behavior, which a Pipeline already does
  `[stated prompt]`.

## 6. Open questions

None.

## 7. TDD plan (core-out)

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| PM-1 | `pick_max_min_equals_returns_member_json_byte_for_byte` | unit | [stated prompt] | H×M | `by_field@1` |
| PM-2 | `non_json_member_is_skipped_and_reported` | unit | [stated prompt] | H×M | status `not_json` |
| PM-3 | `merge_output_has_only_declared_fields` | unit | [stated prompt] | H×M | build from the rule map |
| PM-4 | `merge_rules_majority_max_from_member_union` | unit | [stated prompt] | H×M | four rule functions |
| PM-5 | `union_contains_only_member_strings_first_seen_order` | unit | [stated prompt] | H×M | ordered dedupe |
| PM-6 | `writer_context_is_only_the_field_projection` | unit | [stated prompt] | H×M | `project_field@1` |
| PM-7 | `model_field_merge_compiles_projection_writer_and_merge` | unit | [stated ans:Q12] | H×M | three sources for each model field |
| PM-8 | `writer_failure_fails_case_without_partial_object` | integration | [implied] | H×M | no catch |
| PM-9 | `all_members_unusable_fails_with_combine_no_votes` | unit | [stated ans:Q9] | M×M | voter count |
| PM-10 | `pick_tie_goes_to_author_order` | unit | [stated prompt] | M×M | stable order |
| PM-11 | `merged_json_is_canonical` | unit | [proposed] | M×M | `json.dumps(sort_keys=True, separators=…)` |
| PM-12 | `from_member_out_of_range_raises_at_build` | unit | [proposed] | M×L | constructor check |
| PM-13 | `max_rule_skips_non_numbers` | unit | [proposed] | M×M | `numeric@1` |
| PM-14 | `from_member_not_json_gives_null_field_and_reason` | unit | [proposed] | M×M | per-field status |
| PM-15 | `pick_equals_uses_declared_normalizer` | unit | [proposed] | L×M | `text@1` before compare |
