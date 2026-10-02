# PRD: Regex extract and set equality

**Source:** PRD "Extract and normalize" (`regex`; set equality), criterion A2 · **Priority:** P1
**Lifecycle:** existing (characterize + delta) — 6 extractors and 3 normalizers exist
**Owner:** Ionesio (E4a)

Paths: see [erd.md](../erd.md). Uses [block-api](block-api.md).

## 1. Summary and user story

As a researcher, I want to extract an answer with my own regular expression and to compare list
answers as sets, so that I can vote on answer formats that the built-in rules do not read.

## 2. Background and constraints

- "text → extract rule (`boxed`, `last_number`, `field`, `regex`) → normalize by declared
  equivalence (numeric tolerance, case, whitespace, set equality) → `value`." `[stated prompt]`
- A plugin imports only `combine.ports` and the standard library; no I/O and no clock
  `[existing .claude/scripts/check_layering.py:102]`.
- The combine handler is synchronous and blocks the worker loop while it runs
  `[existing E/world/combine.py:45]`. A slow regex
  blocks every Case on that worker. A running `re` match cannot be stopped from another thread.

### 2.1 Current behavior

- Extractors: `last_number@1`, `boxed@1`, `json_field@1`, `json_object@1`, `last_line@1`,
  `whole@1` `[existing E/combine/operators/extract.py:56]`.
- Normalizers: `numeric@1`, `text@1`, `identity@1` `[existing E/combine/operators/normalize.py:35]`.
- No `regex` and no set equality. "Numeric tolerance" is covered by `inspect_numeric@1`
  ([grader-parity](grader-parity.md)).

**Delta.** Add `regex@1` (extract) and `set@1` (normalize), with golden cases.

### 2.2 `regex@1` contract `[proposed]`

| Arg | Type | Default | Rule |
|---|---|---|---|
| `pattern` | str | required | 1–256 characters; compiles with Python `re`; passes the backtracking ban (RX-D1) |
| `group` | int or str | `0` | must exist in the compiled pattern |
| `occurrence` | `"last"` \| `"first"` | `"last"` | which match to take |
| `ignore_case` | bool | `false` | `re.IGNORECASE` |

Scan window: the last 1024 characters of the member text `[proposed]`. No match →
`status="fail"`, `reason="no_match"`. An empty group match → `reason="empty"`.

### 2.3 `set@1` contract `[proposed]`

Input: a raw value. A JSON list (starts with `[`) is read as JSON; else the value splits on `,`.
Each item: strip, collapse whitespace, casefold. Drop empty items and duplicates, sort by code point,
and emit canonical JSON (`["a","b"]`). Over 256 items → `reason="too_large"`. No items →
`reason="empty"`.

## 3. Scenarios and acceptance criteria

### 3.1 Happy path

- **RX-1** Given `sf.Extract("regex", pattern=r"Final: (\w+)", group=1)` and member texts
  `"… Final: B"`, `"Final: b"`, then with `normalize="text"` both values are `"b"` and they vote
  together. `[stated prompt]`
- **RX-2** Given `sf.Extract("json", normalize="set")` or `field` with `set`, and replies
  `["Paris","Rome"]` and `"rome, paris"`, then both values are `["paris","rome"]`.
  `[stated prompt]`

### 3.2 Error paths

- **RX-E1** Given `pattern="("` (does not compile), then `ValueError` at `sf.Extract` in the SDK,
  and `combine_spec_invalid` in the engine for a hand-written url4. `[implied]`
- **RX-E2** Given `group=2` on a one-group pattern, then the same two errors. `[implied]`
- **RX-E3** Given a member text with no match, then that Answer is `fail` / `no_match` and the vote
  goes on. `[stated prompt]` ("A parse failure is data")

### 3.3 Derived scenarios (risk-ordered)

- **RX-D1** ReDoS `[proposed — gap §security]` (H×M): a static check over the stdlib parse tree
  (`re._parser`, pinned by a test on Python 3.13) rejects, at spec parse in the SDK and the engine:
  (a) a quantifier inside an unbounded quantifier (`(a+)+`, `(a*)*`); (b) an unbounded quantifier
  over an alternation (`(a|aa)+`, `(x|y)*`); (c) two adjacent unbounded quantifiers whose atoms can
  match the same character (`\d*\d*`, `.*.*`, `\w+\d+`). A golden list pins each rejected shape.
  A **timed adversarial golden** runs every accepted pattern of the golden list on its worst-case
  1024-character input and must finish in under 5 ms each. **Tripwire:** if a p99 combine time over
  50 ms shows on regex specs, move regex matching to a subprocess with a deadline (a thread cannot
  stop `re`).
- **RX-D2** Window `[proposed]` (M×M): a match only before the last 1024 characters is not seen
  (`no_match`); a golden case pins it.
- **RX-D3** Unicode `[proposed]` (M×M): `\w` and `ignore_case` use Python's Unicode rules; a golden
  case with `"Ü"` and full-width digits pins them.
- **RX-D4** Determinism (M×L): the same pattern and text give the same value in 20 processes
  `[existing ET/test_combine_determinism.py:73]`.
- **RX-D5** `set@1` order and duplicates `[proposed]` (M×M): `"b, a, a"` and `["a","b"]` give
  one value.
- **RX-D6** `set@1` nested JSON `[proposed]` (L×M): a list item that is not a string, number or
  bool → `reason="not_json"`.
- **RX-D7** Catalog `[existing E/rest/operators.py:27]` (M×L): `GET /v1/operators` lists `regex@1` and
  `set@1` with `args_schema`; the ETag changes.

## 4. Non-functional requirements

- p99 ≤ 50 ms per combine call for 64 members of 64 KiB with a regex spec
  (same budget as E4a contract K4) `[implied]`.
- No message ever echoes the pattern match text (messages name ids and limits only)
  `[existing E/combine/ports.py:58]`.

## 5. Out of scope

- Regex flags beyond `ignore_case`; lookbehind limits; a regex engine other than `re`.
- A generic numeric tolerance with a chosen digit count (the grader tolerance comes from
  `inspect_numeric@1`).

## 6. Open questions

None.

## 7. TDD plan

Core-out, risk-first (the ReDoS ban before the happy path).

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| 1 | `backtracking_shapes_are_rejected` (golden list a–c) | unit | RX-D1 | H×M | static walk of the stdlib parse tree; one helper in `operators/extract.py` |
| 1b | `accepted_patterns_finish_under_5ms_on_worst_input` | unit (timed) | RX-D1 | H×M | — |
| 2 | `regex_pattern_that_does_not_compile_is_spec_invalid` | unit (engine + SDK) | RX-E1 | M×M | compile in args validation |
| 3 | `regex_group_must_exist` | unit | RX-E2 | M×M | `compiled.groups`, `groupindex` |
| 4 | `regex_takes_last_match_group_by_default` | unit | RX-1 | H×H | `finditer` over the window |
| 5 | `regex_no_match_is_fail_no_match` | unit | RX-E3 | H×M | `rejected("no_match")` |
| 6 | `regex_scans_only_last_1024_characters` | unit | RX-D2 | M×M | window slice |
| 7 | `regex_unicode_rules_are_pinned` | unit (golden) | RX-D3 | M×M | — |
| 8 | `set_normalizes_json_list_and_comma_text_to_one_value` | unit | RX-2, RX-D5 | M×M | `set@1` |
| 9 | `set_rejects_nested_items_and_oversize` | unit | RX-D6 | L×M | — |
| 10 | `operator_catalog_lists_regex_and_set` | integration (REST) | RX-D7 | M×L | register in `builtins.py` |
| 11 | `sdk_extract_regex_validates_before_spend` | unit (SDK) | RX-E1 | M×M | same ban in the SDK |
| 12 | `regex_value_is_identical_across_hash_seeds` | unit (subprocess) | RX-D4 | M×L | add regex specs to the determinism inputs |
