# PRD: Pick outputs one field (`sf.Pick(..., output="answer")`)

**Source:** prompt (S5, S8), ans:Q9, ans:Q12 · **Priority:** P2
**Lifecycle:** existing (characterize + delta)
**Owner:** unassigned
Paths: [erd §2, §4, §6](../erd.md) · component: [catalog-and-schema](catalog-and-schema.md)

## 1. Summary and user story

As a benchmark author, I want the member with the highest confidence to win, and the Case answer to
be only that member's `answer` field, so that the scorer sees `42` and not the whole JSON reply.

Scenarios from the prompt [stated prompt]:

- **S5** "extract two number from text -> (verbalized confidence and response) -> choose response
  with maximum confidence".
- **S8** "extract verbalized confidence from text -> argmax -> response from model chosen".

## 2. Background and constraints

- The user selected "Pick outputs one field" as an extra. [stated ans:Q9]
- When the winner's JSON has no usable output field, the Case abstains. The user chose this against
  the recommendation ("take the next best"). [stated ans:Q12]

### 2.1 Current behavior

- `sf.Pick(field=None, *, by_signal=None, order=None, equals=None, normalize=None)`.
  [existing S/fields.py:501-515]
- `Pick("confidence", order="max")` compiles `extract: json_field {path}`, `reduce: values`,
  `select: by_field {order}`. [existing S/fields.py:541-546]
- `Pick(by_signal=sf.signal(k), order=...)` compiles `reduce: by_signal`, `select: best_holder`.
  [existing S/blocks.py:221-225]
- Both selectors return `output=None`, so the answer is the winner's original text byte for byte.
  [existing E/combine/endpoint.py:466-477] [existing E/combine/operators/fields.py:205-216]
- Both arg checks are exact sets today, and `GET /v1/operators` pins the `best_holder@1` args schema
  with `additionalProperties: false`. [existing E/combine/operators/fields.py:157-170]
  [existing E/combine/operators/signals.py:82-84] [existing ET/test_rest_operators.py:89-93]
- A field name matches `[A-Za-z_][A-Za-z0-9_]{0,63}`. [existing S/fields.py:50]

**Delta.** `by_field@1` and `best_holder@1` accept an optional arg `output` (a top-level field name);
their arg checks and args schemas allow it. When `output` is set, `Selection.output` is that field of
the winner's JSON reply. `sf.Pick`, and the `pick_field` and `argmax` blocks, get
`output: str | None = None`. Without `output`, nothing changes.

## 3. Scenarios and acceptance criteria

**Output rule [proposed].** The winner's text is read with the same JSON reader as `json_field@1`
(same fence handling and the same size and depth caps). A JSON string is returned as it is. A
number, boolean, object or array is returned as canonical JSON (`42`, `4.5`, `true`, `{"a":1}`).
A missing key, `null`, a blank string, an unreadable reply, or a reply over the read cap all count
as **missing**.

### 3.1 Happy path

- **PO-1** (S5) Given replies `{"answer": 42, "confidence": 0.9}` and
  `{"answer": 40, "confidence": 0.6}`, and `sf.Pick("confidence", order="max", output="answer")`,
  then the Case answer is `"42"`. [stated prompt] [stated ans:Q9]
- **PO-2** (S8) Given the same replies and
  `sf.Pick(by_signal=sf.signal("field:confidence"), order="max", output="answer")`, then the Case
  answer is `"42"`. [stated prompt]
- **PO-3** Given `output="answer"` and the winner's `answer` is the string `"forty-two"`, then the
  Case answer is `forty-two` with no quotes. [proposed]
- **PO-4** Given a Pick with no `output`, then the compiled bytes and the answer are the same as
  today (the full original text). [implied]
- **PO-5** Given a Pick with `output`, then the evidence records the chosen member, `tie`, and the
  output text as the result value. [existing E/combine/endpoint.py:480-491]

### 3.2 Error paths

- **PO-E1** Given the winner's `answer` is missing, `null` or blank, then the Case abstains with the
  new reason `output_missing`, and it scores 0 on every score. [stated ans:Q12]
- **PO-E2** Given the winner's reply is not a JSON object, or is over the read cap, then the Case
  abstains with `output_missing`. [implied]
- **PO-E3** Given `output="2bad"` or a path such as `"a.b"`, then the SDK raises `ValueError`, and
  the engine refuses the arg with `combine_spec_invalid`. [existing S/fields.py:50]

### 3.3 Derived scenarios (risk-ordered)

- **PO-D1** (H×M) [stated ans:Q12] Given a winner without the field and a runner-up with it, then
  the Case still abstains. The runner-up is never used.
- **PO-D2** (H×M) [implied] Given `order="equals"` (`Pick("label", equals="yes", output="answer")`),
  then the output rule is the same: the first holder in author order, then its field.
- **PO-D3** (M×M) [implied] Given a tie on the compared value, then the first member in author order
  wins, `tie` is true, and its field is the output.
- **PO-D4** (M×M) [implied] Given a url4 with `output`, then the SDK rebuilds `sf.Pick(..., output=...)`.
- **PO-D5** (M×L) [proposed] Given the winner's reply in a fenced ```json block, then the result is
  the same as for the bare JSON. [existing E/combine/operators/extract.py:118-144]

## 4. Non-functional requirements

- The JSON reader has the same caps as `json_field@1`. [existing E/combine/operators/extract.py:118-144]
- No model call. [implied]

## 5. Out of scope

- A fallback to the next member. [stated ans:Q12]
- Nested output paths (`a.b[0]`). [proposed]

## 6. Open questions

None.

## 7. TDD plan

Order: characterize today's original-text pick, then build the engine arg, then the SDK.

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| 1 | CHAR `pick_without_output_returns_the_original_text` | unit | PO-4 | H×M | passes today |
| 2 | `by_field_with_output_returns_the_winners_field` | unit | PO-1 | H×H | read `outputs[chosen]` with the json_field reader |
| 3 | `best_holder_with_output_returns_the_winners_field` | unit | PO-2 | H×H | same helper |
| 4 | `missing_null_or_blank_output_on_the_winner_abstains_with_output_missing` | unit | PO-E1 | H×H | `NoVotes(reason="output_missing")` |
| 5 | `output_missing_does_not_fall_back_to_the_runner_up` | unit | PO-D1 | H×M | no walk past the winner |
| 6 | `non_json_or_oversized_winner_abstains_with_output_missing` | unit | PO-E2 | H×M | the reader returns None |
| 7 | `output_string_is_unquoted_and_number_is_canonical_json` | unit | PO-3 | M×M | render rule |
| 8 | `equals_order_with_output_uses_the_first_holder` | unit | PO-D2 | H×M | same helper |
| 9 | `tie_with_output_uses_the_first_member` | unit | PO-D3 | M×M | — |
| 10 | `fenced_json_winner_gives_the_same_output` | unit | PO-D5 | M×L | reuse the reader |
| 11 | `output_arg_with_a_bad_name_is_spec_invalid` | unit | PO-E3 | M×M | arg check |
| 12 | `operator_args_schemas_allow_output` | unit | [existing ET/test_rest_operators.py:89-93] | M×M | approved edit of the schema pin |
| 13 | `by_field_and_best_holder_goldens_cover_output` | unit | CS-D1 | M×M | add golden cases (approved) |
| 14 | `evidence_records_the_output_as_the_result_value` | unit | PO-5 | M×M | no change expected |
| 15 | `sdk_pick_output_compiles_the_select_arg` | unit | PO-1 | H×M | `_Steps` |
| 16 | `url4_round_trip_rebuilds_pick_output_and_its_blocks` | unit | PO-D4 | M×M | rebuild rows; `_OPS["pick_field"]`, `_OPS["argmax"]` |
| 17 | `engine_runs_sdk_pick_output_on_json_replies` (recipes S5, S8) | integration | PO-1, PO-2 | H×M | `run_candidate` |
