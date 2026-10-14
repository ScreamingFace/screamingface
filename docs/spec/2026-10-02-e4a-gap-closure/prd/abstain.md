# PRD: Abstain when no member gives a usable value

**Source:** PRD "Signals" rules (`abstain` on Reduce), divergence V4 · ans:Q3, ans:Q7, ans:Q10 ·
**Priority:** P1 (changes a wire code and a Case outcome)
**Lifecycle:** existing (characterize + delta)
**Owner:** Ionesio (E4a)

Paths: see [erd.md](../erd.md). Uses [answer-record](answer-record.md).

## 1. Summary and user story

As a researcher, I want a vote with no usable answers to give "no answer" (abstain) and a score of
0, so that one bad Case does not show as a run failure and a later cascade (E4c) can fall back.

## 2. Background and constraints

- "The combine returns an Answer with status abstain; the Case is graded (as not correct), not
  failed." `[stated ans:Q3]`
- "Counts as wrong: score 0 in the accuracy denominator; the Report shows the abstain count
  separately." `[stated ans:Q7]`
- "Graders still run on the empty output; the Case-result build (shared native hook + Inspect
  aggregate) overwrites the grade with score 0. … A judge-graded benchmark pays one judge call per
  abstained Case." `[stated ans:Q10]`

### 2.1 Current behavior

- `NoVotes` (`combine_no_votes`) rises when no member voted or a cut cannot be met
  `[existing E/combine/ports.py:79]` `[existing E/combine/endpoint.py:178]`; also in plugins
  `[existing E/combine/operators/fields.py:111]` `[existing E/combine/operators/fields.py:145]`
  `[existing E/combine/operators/selection.py:66]`.
- The adapter raises it as `ResolutionError(permanent=True)` `[existing E/world/combine.py:49]`; the
  Case becomes `status="failed"` `[existing E/benchmarks/aggregation.py:213]`.
- `CaseStatus` is `"scored" | "failed"` `[existing E/benchmarks/contract.py:44]`
  `[existing S/case_result.py:34]`; `CaseGrade` is `(method, score ≤ 1.0, metrics, checks)`, and
  HealthBench allows a negative score `[existing E/benchmarks/contract.py:203]`.
- Grading runs as a url4 subgraph per benchmark family `[existing E/benchmarks/protocol.py:36]`, but
  every family builds its Case results through one shared `BenchmarkAggregation`
  `[existing E/benchmarks/shared_grading/benchmark_aggregation.py:397]`; Inspect uses it too
  `[existing EI/single_shot.py:175]`.
- A CorrectiveLoop Case can hold a Vote (EV-10); its operations are not lifted
  `[existing ET/test_corrective_vote_contract_fixture.py:1]`.

**Delta.**
1. Core: a plugin raises `NoVotes(reason)` (internal, no failure code); the core catches it and
   returns `result.status="abstain"` with `reason` `no_votes` or `cut_not_met`; output `""`,
   `finish_reason="stop"` (erd §9 lists every raise site).
2. Invocation record `[existing E/benchmarks/invocation.py:72]`: when the expression's **final** node
   is a combine whose evidence has `result.status == "abstain"`, add `abstained: true`. Carry it
   through the invocation decoder, `CandidateAnswer`, the Case records and `CandidateFields`
   ([erd.md §9](../erd.md)).
3. Case-result build (the one shared hook, `BenchmarkAggregation`, used by every family): when the
   invocation is abstained, keep `status="scored"` and the grader's `method`, `metrics` and `checks`;
   replace only `score` with `0.0`; add the wire key `abstained: true` (omitted otherwise). A grader
   error on an abstained Case is ignored and logged. Graders still run `[stated ans:Q10]`.
4. SDK: `CaseResult.abstained`; the candidate summary shows an `abstained` count.
5. `combine_no_votes` leaves both vocabularies.

## 3. Scenarios and acceptance criteria

### 3.1 Happy path

- **AB-1** Given a Vote over 3 members that all reply `"I am not sure"`, when the Case runs, then the
  Case is `scored`, `score == 0.0`, `abstained is True`, the grade keeps the grader's `method`,
  `metrics` and `checks`, and the evidence `result` is `abstain` / `no_votes`. `[stated ans:Q3]` `[stated ans:Q7]`
- **AB-2** Given 10 Cases where 2 abstain and 5 are correct, then the candidate accuracy is
  `5 / 10` and the Report shows `abstained: 2`. `[stated ans:Q7]`
- **AB-3** Given an abstained Case on a judge-graded benchmark, then the grader runs once on `""`,
  and its grade is replaced by score 0.0. `[stated ans:Q10]`

### 3.2 Error paths

- **AB-E1** Given a spec error (unknown operator, bad args), then the Case still **fails** with
  `combine_spec_invalid` / `combine_operator_unknown`. `[implied]`
- **AB-E2** Given a member transport error, then the Case fails as today. `[implied]`

### 3.3 Derived scenarios (risk-ordered)

- **AB-D1** Cut not met `[proposed]` (H×M): `sf.Rank(k=3)` with 2 usable members → abstain
  `cut_not_met`.
- **AB-D2** Abstain inside a Pipeline `[implied]` (H×M): `Pipeline([Fusion(…, Vote), Model])` whose
  Vote abstains → the Model stage gets `""` and runs; the Case is not abstained. The evidence keeps the
  inner abstain.
- **AB-D3** Partial votes `[existing E/combine/ports.py:150]` (M×H): 1 of 3 members usable → that
  member wins; `dropped == 2`; no abstain.
- **AB-D4** No usable field `[proposed]` (M×M): a Merge field with no usable value → the whole Merge
  abstains (`no_votes`); a projection field that no member has → abstain (`no_votes`); `by_field@1`
  with no member equal to the target → abstain (`no_votes`).
- **AB-D11** Benchmark metrics kept `[proposed]` (H×M): on ContractEval, an abstain on a positive row
  counts as a false negative (the grader's metrics on `""` are kept), so F1 is right.
- **AB-D5** Weighted vote where no usable member has a weight → abstain (tested in
  [signal-reduce](signal-reduce.md) SR#3) `[proposed]`.
- **AB-D6** Byte-identical wire `[proposed]` (H×M): a Case that does not abstain has no `abstained`
  key on the Case or on the invocation record.
- **AB-D7** CorrectiveLoop `[proposed]` (M×M): an inner-round abstain hands `""` to the loop's check,
  which grades it by the benchmark's rule (usually a fail, so the next round runs); the Case record
  is the loop's own, so a last-round abstain is **not** marked and the grader scores `""` as it is.
- **AB-D8** Concat of empty texts `[proposed]` (M×L): output `""` but `result.status="answered"` →
  not abstained (I-E2 is one-way).
- **AB-D9** Replay `[existing ET/test_combine_determinism.py:73]` (M×M): a replay abstains again with
  the same evidence.
- **AB-D10** Every family `[stated ans:Q10]` (H×M): the grade replacement works for a native
  benchmark (IFEval), an Inspect benchmark (GSM8K) and a judge-graded benchmark (HealthBench).

## 4. Non-functional requirements

- Cost: an abstained Case on a judge-graded benchmark costs one grader call (accepted,
  `[stated ans:Q10]`).
- Observability: the Report shows the abstain count; each abstained Case keeps its evidence.

## 5. Out of scope

- A recipe option `on_empty="fail"` (rejected in ans:Q3); abstain from Classify or Branch (E4c);
  abstain on member Answers (I-A3); lifting CorrectiveLoop operations (U4 follow-up).

## 6. Open questions

None. (O1, HealthBench and negative scores, is decided `[stated ans:Q15]`: an abstain scores 0.0,
which is higher than a harmful answer's negative score; the README says so.)

## 7. TDD plan

Core-out: core result, adapter mark, Case-result hooks, then SDK.

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| 1 | CHAR: today a no-vote Case fails with `combine_no_votes` (a stack test; the delta commit changes it) | integration | [existing E/world/combine.py:49] | — | passes today |
| 2 | `no_usable_member_returns_abstain_result_not_error` | unit | AB-1 | H×H | core catches `NoVotes(reason)` |
| 3 | `cut_not_met_abstains_with_reason` | unit | AB-D1 | H×M | `selection.py:66` raises with reason |
| 4 | `merge_projection_and_by_field_without_usable_value_abstain` | unit | AB-D4 | M×M | `fields.py:111`, `:145`, `:197` |
| 5 | `spec_errors_still_fail_the_case` | unit | AB-E1 | H×M | — |
| 6 | `member_transport_error_still_fails_the_case` | integration | AB-E2 | H×M | — |
| 7 | `abstained_combine_output_is_empty_with_stop` | integration (adapter) | I-E2 | H×M | — |
| 8 | `empty_concat_is_not_abstain` | unit | AB-D8 | M×L | detect only from `result.status` |
| 9 | `invocation_record_marks_final_combine_abstain` | integration (`invocation.py`) | delta 2 | H×H | inspect the final node + its evidence; carry through the decoder and `CandidateFields` |
| 10 | `inner_abstain_in_pipeline_does_not_mark` | integration | AB-D2 | H×M | final-node rule |
| 11 | `abstained_case_score_replaced_native` (IFEval) | integration | AB-1, AB-D10 | H×H | `BenchmarkAggregation` `_scored_result` |
| 12 | `abstained_case_score_replaced_inspect` (GSM8K) | integration (inspect lane) | AB-D10 | H×H | same hook via `single_shot.py:175` |
| 13 | `abstained_case_grade_replaced_judge_graded` (HealthBench, grader called once) | integration | AB-3, AB-D10 | H×M | — |
| 14 | `non_abstained_wire_has_no_abstained_key` | unit | AB-D6 | H×M | `exclude_if` |
| 15 | `corrective_loop_inner_and_last_round_abstain` | integration | AB-D7 | M×M | — |
| 16 | `combine_no_votes_is_not_a_declared_code` | unit (engine + SDK twin) | delta 5 | M×H | `DECLARED_FAILURE_CODES` |
| 17 | `sdk_decodes_abstained_and_counts_it` | unit (SDK) | AB-2 | H×M | — |
| 18 | `engine_accuracy_counts_abstain_as_zero_per_family` | integration (engine aggregates) | AB-2 | H×H | — |
| 19 | `one_usable_member_wins_with_dropped_count` | unit | AB-D3 | M×H | — |
| 20 | `abstain_replays_identically` | unit | AB-D9 | M×M | — |
| 21 | `abstained_grader_error_is_ignored_and_logged` | integration | delta 3 | M×M | `_ladder_result`, `_graded_result` |
| 22 | `contracteval_abstain_on_positive_row_is_false_negative` | integration | AB-D11 | H×M | keep grader metrics |
| — | AB-D5 is tested as SR#3 | — | — | — | — |
