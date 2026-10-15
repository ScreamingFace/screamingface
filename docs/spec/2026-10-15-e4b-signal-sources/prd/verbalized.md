# PRD: Verbalized confidence (`sf.Verbalized(pattern)`)

**Source:** ans:Q1, ans:Q9 · **Priority:** P1
**Lifecycle:** planned
**Owner:** unassigned
Paths: [erd §1](../erd.md) · component: [declared-signals](declared-signals.md)

## 1. Summary and user story

As a benchmark author whose members write a line such as `Confidence: 90`, I want that number as
a signal of each member answer, so that I can weight a vote or pick a member by stated confidence
without a JSON reply format.

## 2. Background and constraints

- The source finds a pattern in the member text. If the pattern does not match, the value is
  missing, not a guess. [stated prompt] (epic sources table)
- The regex must have one capture group. The LAST match counts. The value is the number as written:
  `90` stays `90`. [stated ans:Q9]
- Today the nearest form is `field:confidence`, which needs a JSON reply.
  [existing S/_signals.py:19-20]
- The engine already runs author regexes safely: RE2 (linear in the text), a pattern of 1 to 256
  characters, a program size of at most 5000, refused at spec check.
  [existing E/combine/operators/extract.py:11-15,141-195]

**Delta.** `sf.Verbalized(pattern, *, ignore_case=False)` is a declared source. The engine reuses the
regex@1 checks (`check_regex_pattern`) for the pattern. It computes the value in the combine step
from the member text, like `field:<path>` [existing E/combine/endpoint.py:250], with no model call.

## 3. Scenarios and acceptance criteria

**Definition [proposed].** Read the member text under the 1 MiB read cap
[existing E/combine/ports.py:74]. Find every match of the pattern with RE2. Take the LAST match.
Take capture group 1. Strip spaces. If the group text is an ASCII decimal number
(`[-+]?[0-9]+(\.[0-9]+)?`), the value is that number as a float. Else the value is None.

WHY the whole text and not the last 1024 characters as regex@1 does: a model often writes the
confidence line first and the long explanation after it. RE2 is linear, so the cost on 1 MiB is
bounded. [proposed]

### 3.1 Happy path

- **VB-1** Given the text `"Answer: 12\nConfidence: 90"` and the pattern `Confidence: ([0-9]+)`, then
  the value is `90.0`. [stated ans:Q9]
- **VB-2** Given `"Confidence: 40 ... on reflection, Confidence: 75"`, then the value is `75.0`
  (last match). [stated ans:Q9]
- **VB-3** Given `sf.Vote(weights=sf.signal("conf"))` with three members that state 90, 60 and 30
  for answers A, B and A, then the tally is A = 120, B = 60, and the answer is A's first holder.
  [stated prompt] (behavior 1); [existing E/combine/operators/reduce.py:81-84]

### 3.2 Error paths

- **VB-E1** Given a text with no match, then the value is None, and a vote leaves that member out.
  [stated prompt]; [existing E/combine/endpoint.py:422-428]
- **VB-E2** Given a pattern that RE2 does not compile, that is longer than 256 characters, or that has
  no capture group, then `sf.Verbalized` raises `ValueError` at construction, and the engine
  refuses the spec with `combine_spec_invalid`. [existing E/combine/operators/extract.py:154-176];
  [proposed] (group rule)
- **VB-E3** Given a match whose group text is not a number (`"Confidence: high"` with `(\w+)`), then
  the value is None. [stated ans:Q9]

### 3.3 Derived scenarios (risk-ordered)

- **VB-D1** (H×M) [implied] Given a group text `"1e9"`, `"NaN"`, `"inf"` or `"9,5"`, then the value is
  None (ASCII decimal only, I-S2).
- **VB-D2** (H×M) [existing E/combine/operators/extract.py:212-214] Given a text with a lone
  surrogate, then RE2 reads it as U+FFFD and does not fail.
- **VB-D3** (M×M) [existing E/combine/ports.py:74] Given a text over 1 MiB, then the value is None.
- **VB-D4** (M×M) [stated ans:Q9] Given members that use different scales (90 and 0.9), then the
  engine does not normalize. The README says: use one scale for all members.
- **VB-D5** (M×M) [implied] Given a value of 0 or less used as a vote weight, then the member is left
  out (the part 1 weight rule). [existing E/combine/endpoint.py:427]
- **VB-D6** (M×L) [proposed] Given `ignore_case=True`, then `confidence: 90` matches
  `Confidence: ([0-9]+)`.
- **VB-D7** (M×L) [implied] Given a hostile text of 1 MiB with many partial matches, then the time
  stays linear (RE2). A test checks the CPU time against a generous bound (see OME-1619 for timing
  test care).

## 4. Non-functional requirements

- RE2 time is linear in the text and grows with the program size, capped at 5000.
  [existing E/combine/operators/extract.py:183-189]
- The pattern never reaches a log (RE2 `log_errors = False`). [existing E/combine/operators/extract.py:166-170]

## 5. Out of scope

- A `scale=` argument. [stated ans:Q9]
- First-match mode. [stated ans:Q9]
- Calibration of stated confidence (a research question). [proposed]

## 6. Open questions

None.

## 7. TDD plan

Order: core-out. The parse function first, then the SDK object, then the engine read.

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| 1 | `verbalized_takes_group_one_of_the_last_match` | unit | VB-1, VB-2 | H×M | `finditer`, keep the last |
| 2 | `verbalized_with_no_match_is_none` | unit | VB-E1 | H×M | — |
| 3 | `verbalized_non_number_group_is_none` | unit | VB-E3, VB-D1 | H×M | ASCII decimal regex |
| 4 | `verbalized_refuses_a_bad_pattern_in_sdk_and_engine` | unit | VB-E2 | H×M | `check_regex_pattern` + group check |
| 5 | `verbalized_reads_the_whole_text_under_the_read_cap` | unit | VB-D3 | M×M | not the 1024 window |
| 6 | `verbalized_survives_a_lone_surrogate` | unit | VB-D2 | M×M | reuse `_regex_window` substitution |
| 7 | `verbalized_ignore_case` | unit | VB-D6 | M×L | RE2 options |
| 8 | `vote_weighted_by_verbalized_confidence` | integration | VB-3 | H×M | `run_candidate` |
| 9 | `verbalized_zero_weight_leaves_the_member_out` | unit | VB-D5 | M×M | — |
| 10 | `verbalized_stays_linear_on_hostile_text` | unit | VB-D7 | M×L | generous CPU bound |
