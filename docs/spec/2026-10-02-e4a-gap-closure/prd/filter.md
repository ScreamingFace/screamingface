# PRD: Filter members by a check or a threshold

**Source:** PRD Reduce op `filter` ("on `check` or a threshold"), criterion A3 · ans:Q4 ·
**Priority:** P1
**Lifecycle:** planned
**Owner:** Ionesio (E4a)

Paths: see [erd.md](../erd.md). Uses [signals](signals.md),
[block-api](block-api.md), [abstain](abstain.md).

## 1. Summary and user story

As a researcher, I want to keep only the members that pass a check or a threshold, and hand them
to the next stage, so that I can express "drop low-confidence answers, then synthesize" and the
first half of the corrective-loop recipe.

## 2. Background and constraints

- "`filter` (on `check` or a threshold)" `[stated prompt]`.
- "`mode: select(k)` returns k original Answers" `[stated prompt]`: a filter is a select whose k
  is the number of members that pass.
- `check` (a declared pass/fail signal) is E4b. In E4a a check is a regex match on the member text
  or a JSON field that is `true` `[stated ans:Q4]` (E4a sources).
- A selection is a hand-off to the next stage, not an answer
  `[existing packages/screamingface/README.md:375]`.

### 2.1 `filter` contract `[proposed]`

`sf.Filter(where=…)` = `sf.Reduce("filter", where=…)`. One predicate:

| `where` | Passes when |
|---|---|
| `sf.signal(key) >= v` (also `>`, `<`, `<=`, `==`) | the member's signal is not `None` and compares true |
| `sf.matches(pattern)` | the `regex@1` rule ([extract-rules](extract-rules.md)) finds a match |
| `sf.signal("field:<path>") == True` | a JSON bool field is `true` |

Engine: reducer `filter`, reduce `filter@1` (`key`, `cmp`, `value`) or (`pattern`, …), select
`kept@1`. Output: the selection envelope of `sf.Rank` (`{"selected": [{"id", "text"}, …]}`), in
author order. Exactly one member passes → still the envelope `[proposed]` (a filter result is a
list; the shape does not change with the count).

## 3. Scenarios and acceptance criteria

### 3.1 Happy path

- **FL-1** Given 4 members with `field:confidence` 0.9, 0.2, 0.7, 0.5 and
  `sf.Filter(where=sf.signal("field:confidence") >= 0.6)` in a Fusion followed by a Model stage,
  then the Model stage receives the envelope with member_1 and member_3, in that order.
  `[stated prompt]`
- **FL-2** Given `where=sf.matches(r"ANSWER: \d+")`, then only members whose text matches are kept.
  `[stated prompt]` (check)
- **FL-3** The evidence shows each member's signal value, `chosen` = the kept members, and
  `dropped` = members that failed to parse. `[stated prompt]` ("records its tally and the chosen
  member_ids")

### 3.2 Error paths

- **FL-E1** Given no member passes, then the step abstains (`reason="no_votes"`); inside a
  Pipeline the next stage gets `""` ([abstain](abstain.md) AB-D2). `[stated ans:Q3]`
- **FL-E2** Given a Filter as the last stage of a candidate (no next stage), then `ValueError` at
  build time, as for `sf.Rank` and `sf.Concat` `[existing S/_evaluation/candidate.py:160]`.

### 3.3 Derived scenarios (risk-ordered)

- **FL-D1** Missing signal `[proposed]` (H×M): a member with `None` for the key does not pass.
- **FL-D2** Compare on a non-finite `value` (`nan`, `inf`) → `ValueError` at construction
  `[proposed]` (M×L).
- **FL-D3** Envelope size `[existing E/combine/endpoint.py:279]` (M×L): the 8 MiB output cap applies; a
  too-large envelope fails the Case with `combine_input_too_large`.
- **FL-D4** Determinism (M×L): order is author order, never dict order.
- **FL-D5** Regex safety (H×M): `sf.matches` uses the `regex@1` ban and window (RX-D1, RX-D2).

## 4. Non-functional requirements

- No model call `[implied]`. Same p99 budget as E4a K4.

## 5. Out of scope

- The E4b `check` signal and the full corrective-loop recipe (needs Branch, E4c) `[stated prompt]`.
- Boolean combinations of predicates (`and`, `or`) `[proposed]` (future).

## 6. Open questions

None.

## 7. TDD plan

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| 1 | `filter_with_no_passing_member_abstains` | unit | FL-E1 | H×M | abstain path |
| 2 | `member_with_missing_signal_does_not_pass` | unit | FL-D1 | H×M | `filter@1` |
| 3 | `threshold_filter_keeps_members_in_author_order` | unit | FL-1, FL-D4 | H×H | `filter@1` + `kept@1` |
| 4 | `regex_check_filter_keeps_matching_members` | unit | FL-2, FL-D5 | M×M | reuse `regex@1` pure functions |
| 5 | `filter_evidence_records_values_chosen_and_dropped` | unit | FL-3 | M×M | — |
| 6 | `filter_as_last_stage_is_rejected` | unit (SDK) | FL-E2 | M×M | reuse selection check |
| 7 | `non_finite_threshold_is_rejected` | unit (SDK) | FL-D2 | M×L | — |
| 8 | `filter_then_model_receives_envelope` | integration (fake transport) | FL-1 | H×M | — |
| 9 | `reduce_filter_block_equals_sf_filter` | unit (SDK) | block-api BK-2 | M×M | op table row |
| 10 | `filter_envelope_over_output_cap_fails_input_too_large` | unit | FL-D3 | M×L | existing 8 MiB cap |
