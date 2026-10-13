# PRD: Answer operators — extract, normalize, reduce, select (component)

**Source:** prompt (OME-1289), ans:Q4, ans:Q7, ans:Q8 · **Priority:** P1, build second
**Lifecycle:** planned
**Owner:** unassigned
**Landing:** `apps/screamingface-engine` (`screamingface_engine/combine/operators/`)

## 1. Summary and the flows it serves

This component is the library of pure operators that the combine endpoint runs. Each operator has
an id `name@version`. It serves majority-vote-and-median, weighted-vote, judge-pick,
pick-and-merge, rank-keep-k, and concatenate. The endpoint and the registry are in
[operator-framework.md](operator-framework.md).

## 2. Background and constraints

- "Normalization the library must do: trim, collapse whitespace, lowercase for text answers,
  `9.0` → `9`, strip one trailing period." `[stated prompt]`
- "Extraction the library must offer: last number in the text, the inside of `\boxed{...}`, a
  named JSON field, the last non-empty line." `[stated prompt]`
- Free-text answers are equal only when their normalized text is equal. There is no similarity
  match `[stated ans:Q8]`.
- The median reducer returns the nearest member or the value, as the recipe declares
  `[stated ans:Q4]`.
- E4a does not move existing graders to these operators `[stated ans:Q7]`. The grader-parity
  risk on imported boards is parked (see 00-overview.md, deferred items).

## 3. Operator catalog (v1)

Each operator is a pure function. It gets only its inputs and its `args`. It returns a value and a
status. It has no I/O and no clock, and it does not read the environment `[stated prompt]`.

### 3.1 Extract (one member text → raw value or empty)

| id | Behavior | Tag |
|---|---|---|
| `last_number@1` | The last number token in the text. It accepts a sign (`-` or `−`), thousands separators (`1,200`), and decimals. The pattern runs in linear time. | [stated prompt]; separators [proposed — from the parked parity finding] |
| `boxed@1` | The content of the last `\boxed{…}`. Brace counting handles nested braces up to depth 8. | [stated prompt] |
| `json_field@1` (`args.path`) | Parse the trimmed text as JSON. If that fails, parse the last fenced json code block. Then read `args.path` with the url4 field-path grammar (`a.b[0]`). | [stated prompt]; fence rule and grammar [proposed] |
| `last_line@1` | The last line that is not empty after trimming. | [stated prompt] |
| `whole@1` | The whole text. | [proposed] |

### 3.2 Normalize (raw value → comparable value, or a status)

| id | Behavior | Tag |
|---|---|---|
| `numeric@1` | Remove `$ € £`, remove `,` between digit groups, strip one trailing period, parse as a decimal. Write it in canonical form: no trailing zeros, no exponent, `-0` → `0`. Text that is not a number gets the status `not_numeric`. | [stated prompt]; currency [proposed] |
| `text@1` | Trim, collapse whitespace to one space, casefold, strip one trailing period. | [stated prompt] |
| `identity@1` | No change. | [proposed] |

### 3.3 Reduce (member values → tally, statistic, or projection)

| id | Behavior | Tag |
|---|---|---|
| `mode@1` | Count one vote for each member with status `voted`. | [stated prompt] |
| `weighted_mode@1` | Add the member's weight for each voter. | [stated prompt] |
| `median@1` | The median of the numeric values. For an even count, the mean of the two middle values. | [stated prompt]; even rule [proposed] |
| `project_field@1` (`args.field`) | Return the JSON value of one field for each member (used by a model-written merge field). | [proposed] |
| `field_rules@1` (`args.fields`) | Build an object from per-field rules (see pick-and-merge.md). | [stated prompt] |
| `join@1` (`args.separator`) | Join the texts in author order. | [stated prompt] |
| `scores@1` | Use the parsed judge scores, or a numeric field, as the score of each member. | [proposed] |

### 3.4 Select (reduction → chosen members or a value)

| id | Behavior | Tag |
|---|---|---|
| `first_holder@1` | The first member in author order that holds the winning value. | [stated prompt] |
| `max_weight_holder@1` | The holder with the highest weight; a tie goes to the first in author order. | [stated prompt] |
| `nearest@1` | The member whose value is nearest to the median; a tie goes to the first in author order. | [stated ans:Q4] |
| `value@1` | The median value itself, in canonical numeric form. | [stated ans:Q4] |
| `by_label@1` | The member that the judge label names. | [stated prompt] |
| `max_score@1` | The member with the highest score; a tie goes to the first in author order. | [stated prompt] |
| `top_k@1` (`args.k`) | The k members with the highest scores, in score order. Ties go by author order. | [stated prompt] |
| `by_field@1` (`args.order`: `max`, `min`, or `equals` + `args.value`) | The member whose field value is the max, the min, or equal to the value. | [stated prompt] |
| `all@1` | All members (used by concatenate). | [proposed] |

## 4. Scenarios and acceptance criteria

### 4.1 Happy path

**OP-H1 Numbers that mean the same value group together.** `[stated prompt]`
Given the extracts `9`, `9.0`, `9.00`, and `9.`,
When `numeric@1` runs,
Then each one becomes `9`.

**OP-H2 Text normalization.** `[stated prompt]`
Given `"  Paris. "` and `"paris"`,
When `text@1` runs,
Then both become `paris`.

**OP-H3 Each required extractor.** `[stated prompt]`
Given `"… so x = 9, final \boxed{12}"`,
When `last_number@1` runs, the result is `12`; when `boxed@1` runs, the result is `12`.
Given `'{"answer": {"value": 7}}'`, when `json_field@1` runs with path `answer.value`, the
result is `7`.
Given `"a\n\nfinal: B\n  \n"`, when `last_line@1` runs, the result is `final: B`.

**OP-H4 Median select modes.** `[stated ans:Q4]`
Given the values 3, 9, 9, 12,
When `median@1` runs, the median is 9.
When `nearest@1` runs, the result is the first member with 9.
When `value@1` runs, the result is the text `9`.

### 4.2 Error and edge paths

**OP-E1 No match gives the status `empty`.** `[stated prompt]`
Given a text with no number, when `last_number@1` runs, then the status is `empty`, and the
member does not vote.

**OP-E2 Text that is not a number gives `not_numeric`.** `[proposed]`
Given the extract `twelve`, when `numeric@1` runs, then the status is `not_numeric`.

**OP-E3 JSON that cannot be read gives `not_json`.** `[stated prompt]`
Given the text `answer: 7`, when `json_field@1` runs, then the status is `not_json`, and the
member is skipped.

**OP-E4 A missing field gives `field_missing`.** `[proposed]`
Given valid JSON without the path, when `json_field@1` runs, then the status is `field_missing`.

### 4.3 Derived scenarios (risk order)

| ID | Title | Tag | I×L | Given / When / Then |
|---|---|---|---|---|
| OP-D1 | Behavior is frozen for each version | [proposed] | H×M | Given the golden file for each operator id, when the suite runs, then each output matches. A changed output fails the test, and the fix is a new `@version`. |
| OP-D2 | Hostile regex input | [proposed — gap §cross-cutting/security] | H×L | Given 1 MiB of `1,1,1,…` or `\boxed{` repeated, when an extractor runs, then it ends in ≤ 50 ms. |
| OP-D3 | Thousands separators | [proposed] | M×M | Given `$1,200`, when `last_number@1` + `numeric@1` run, then the value is `1200`, not `200`. |
| OP-D4 | Unicode | [proposed] | M×M | Given a unicode minus (`−3`) and full-width digits, when `numeric@1` runs, then `−3` becomes `-3`, and full-width digits get `not_numeric` (v1 accepts ASCII digits only). |
| OP-D5 | Nested boxed | [proposed] | M×L | Given `\boxed{\frac{1}{2}}`, when `boxed@1` runs, then the result is `\frac{1}{2}`. |
| OP-D6 | Deep JSON | [proposed — gap §cross-cutting/security] | M×L | Given JSON nested 1,000 levels deep, when `json_field@1` runs, then the status is `not_json`, and nothing crashes. |
| OP-D7 | Median with an even count | [proposed] | M×M | Given 2, 4, when `median@1` runs, then the median is 3. Both members are at distance 1, so `nearest@1` picks the first one in author order. |
| OP-D8 | Canonical number form | [proposed] | M×M | Given `1e3`, `1000.0`, and `-0`, when `numeric@1` runs, then the results are `1000`, `1000`, and `0`. |
| OP-D9 | No shared state | [proposed] | M×L | Given two operator calls that run at the same time in one process, when they finish, then neither result depends on the other. |

## 5. Non-functional requirements

- Each extractor is O(n) in the text length `[proposed]`.
- Each operator module imports only the standard library and `url4.core` (for the field-path
  grammar) `[proposed]`.

## 6. Out of scope

- Semantic or embedding similarity `[stated ans:Q8]`.
- Grader migration and grader parity on imported boards `[stated ans:Q7]`.
- Borda, IRV, and Condorcet (E4e) `[stated prompt]`.

## 7. Open questions

None.

## 8. TDD plan (core-out)

Order: core-out, by risk. Determinism and hostile input come first.

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| OP-1 | `golden_outputs_match_for_every_registered_operator` | unit | [proposed] | H×M | golden JSON fixture for each id |
| OP-2 | `extractors_finish_under_50ms_on_hostile_1mib_input` | unit | [proposed] | H×L | linear regex; brace counter |
| OP-3 | `numeric_groups_9_9_0_9_00_and_9_dot` | unit | [stated prompt] | H×M | `Decimal` normalize |
| OP-4 | `last_number_reads_thousands_separators` | unit | [proposed] | M×M | grouped-digit alternative first |
| OP-5 | `text_normalize_trims_collapses_casefolds_strips_one_period` | unit | [stated prompt] | M×M | four steps |
| OP-6 | `boxed_reads_last_and_nested_braces` | unit | [stated prompt] | M×M | brace counter, depth 8 |
| OP-7 | `json_field_reads_path_and_fenced_block` | unit | [stated prompt] | M×M | `json.loads` + fence fallback |
| OP-8 | `json_field_statuses_not_json_and_field_missing` | unit | [stated prompt] | M×M | typed statuses |
| OP-9 | `json_field_rejects_depth_over_64` | unit | [proposed] | M×L | depth walk after parse |
| OP-10 | `last_line_skips_blank_lines` | unit | [stated prompt] | L×M | reverse scan |
| OP-11 | `median_even_count_is_mean_of_middle` | unit | [proposed] | M×M | sorted list |
| OP-12 | `nearest_and_value_select_modes` | unit | [stated ans:Q4] | M×M | two select ops |
| OP-13 | `max_weight_holder_tie_goes_to_author_order` | unit | [stated prompt] | M×M | stable sort |
| OP-14 | `top_k_orders_by_score_then_author_order` | unit | [stated prompt] | M×M | stable sort |
| OP-15 | `by_field_max_min_equals` | unit | [stated prompt] | M×M | three branches |
| OP-16 | `numeric_canonical_form_cases` | unit | [proposed] | M×M | `format(Decimal.normalize(), "f")` |
| OP-17 | `unicode_minus_ok_fullwidth_not_numeric` | unit | [proposed] | M×L | explicit char map |
| OP-18 | `concurrent_operator_calls_share_no_state` | unit | [proposed] | M×L | no module-level mutable state |
