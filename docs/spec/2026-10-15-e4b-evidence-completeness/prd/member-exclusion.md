# PRD: A member left out for a missing signal or weight (`status="excluded"`)

**Source:** ans:Q3 (epic OME-1290 gaps C2, D3) · **Priority:** P0
**Lifecycle:** existing (characterize + delta)
**Owner:** unassigned
Paths: [erd §2, §6](../erd.md) · component: [evidence-schema](evidence-schema.md)

## 1. Summary and user story

As a researcher who reads the evidence of a combine step, I want to see which members a rule left
out because they had no signal or no usable weight, and why, so that I do not read a silent drop
as a member that lost the vote.

## 2. Background and constraints

- Epic OME-1290 behavior 1: "A missing signal: that member does not vote, and the report says
  why." Behavior 2: "Missing signal excludes the member." [stated prompt]
- The member gets the new status `"excluded"`, with a reason. The user chose this against the
  recommendation (a new field with the status kept). [stated ans:Q3]
- The status and reason words are owned by [evidence-schema](evidence-schema.md).

### 2.1 Current behavior

- A signal weight becomes the member's weight only when it is not `None` and is in
  `(0, MAX_WEIGHT]`; otherwise the weight is `None`. [existing E/combine/endpoint.py:422-428]
- The weighted reducers drop a voter whose weight is `None`. When no voter is left, the step
  abstains with `no_votes`. [existing E/combine/operators/reduce.py:66-78]
- `by_signal@1` scores only the voters that have the signal. When none has it, the step abstains
  with `no_votes`. [existing E/combine/operators/signals.py:67-81]
- `filter@1` (threshold form) gives a member with no signal the mark 0, the same mark as a member
  that fails the threshold. [existing E/combine/operators/signals.py:132-137,146-157]
- In the evidence, such a member shows `status: "answered"`, `reason: null`, and `weight: null` or
  `score: null` (or `score: 0` for a Filter). Nothing says it was left out.
  [existing E/combine/endpoint.py:431-446,578-588]
- `dropped` counts only `status == "fail"`. [existing E/combine/endpoint.py:573]

**Delta.** The endpoint computes one exclusion reason per member from the plan and the answers
([erd §6](../erd.md), rows X1–X6), and writes it into the member record: `status: "excluded"` and
`reason: "no_weight"` or `"no_signal"`. The core `Answer` and every operator do not change, so the
answer of every Case stays the same. Only the record changes. [proposed]

**Where it runs (review m9).** The rule has two parts in two fixed places, and nowhere else:

1. `_plan` decides once per spec WHICH exclusion the step can make, and stores it on the plan:
   ```python
   @dataclass(frozen=True, slots=True)
   class _Exclusion:
       reason: ExcludeReason  # "no_weight" | "no_signal"
       key: str  # the signal key the rule reads

   def _exclusion(
       spec: CombineSpec, reduce: OperatorDescriptor, bound: _Step[ReduceOp]
   ) -> _Exclusion | None: ...

   # _Plan gets: excludes: _Exclusion | None
   ```
2. `_member_record` (called only from `_evidence`, which both `_decide` and `_abstain` reach)
   applies it to one member: an answered member with `answer.weight is None` (for `"no_weight"`)
   or with `answer.signals[key] is None` (for `"no_signal"`) gets `status: "excluded"`.
   [existing E/combine/endpoint.py:536-588]

`_signal_read` merges the two signal sources into one `SignalRead`, so `_exclusion` does not read
its result. It reads the two sources directly, as `_signal_read` does
[existing E/combine/endpoint.py:381-397]:

- X1 (`"no_weight"`): `isinstance(spec.weights, SignalWeights)` and `reduce.reads_weights` (the new
  descriptor flag, True only for `weighted_mode@1`, `weighted_mean@1`, `weighted_median@1`). The key
  is `spec.weights.signal`.
- X2 (`"no_signal"`): `reduce.signal_read` is set and returns a read for `bound.args`
  (`by_signal@1`, the threshold form of `filter@1`). The key is that read's key.
- Both at once cannot happen: `_signal_read` already refuses a step that reads two signals
  (`combine_spec_invalid`). None of the two: no exclusion.

**Design note.** The brief proposed that each operator reports its excluded members. This PRD
computes the exclusion in the endpoint instead, for two reasons. (1) When every member is left out,
the reduce step abstains by raising `NoVotes`, and a raised step returns no `Reduction`. An
operator report would be lost in exactly the case where it matters most. (2) The operators stay
unchanged, so no golden operator fixture changes. The endpoint needs one new descriptor flag,
`reads_weights`, and it already knows where the signal comes from (`_signal_read`).
[existing E/combine/endpoint.py:283-307,381-397] [proposed — gap §per-flow/failure]

## 3. Scenarios and acceptance criteria

### 3.1 Happy path

- **EX-1** Given a weighted vote with `weights=sf.signal("field:confidence")`, members 1 and 2
  answer "A" with confidence 0.9 and 0.4, and member 3 answers "B" with no `confidence` field, then
  the answer is "A", member 3 has `status: "excluded"`, `reason: "no_weight"`, `value: "B"`,
  `weight: null`, and members 1 and 2 stay `"answered"`. [stated ans:Q3]
- **EX-2** Given `sf.Pick(by_signal=sf.signal("field:confidence"), order="max")` and a member with
  no confidence field, then that member has `status: "excluded"`, `reason: "no_signal"`, and
  `score: null`. [stated ans:Q3]
- **EX-3** Given `sf.Rank(2, by_signal=sf.signal("cost_usd"))` and a member whose call has no price,
  then that member is `"excluded"` with `"no_signal"`, and it is not in the selection.
  [stated ans:Q3]
- **EX-4** Given `sf.Filter(where=sf.signal("field:confidence") >= 0.5)` and a member with no
  confidence field, then that member is `"excluded"` with `"no_signal"`, and a member with
  confidence 0.2 stays `"answered"` with `score: 0` (it failed the threshold; it was not left out).
  [stated ans:Q3] [existing E/combine/operators/signals.py:132-137]

### 3.2 Error paths

- **EX-E1** Given every member of a weighted vote has no usable weight, then the step abstains with
  `no_votes` (as today), and every member record is `"excluded"` with `"no_weight"`.
  [existing E/combine/operators/reduce.py:73-78] [stated ans:Q3]
- **EX-E2** Given every member of a Rank by signal has no signal, then the step abstains (as today),
  and every member record is `"excluded"` with `"no_signal"`. [stated ans:Q3]
- **EX-E3** Given a member that failed (for example `not_numeric`, or `missing` from a quorum
  panel) and also has no signal, then its record stays `"fail"` with its failure reason. A failure
  wins over an exclusion (X3). [proposed]

### 3.3 Derived scenarios (risk-ordered)

- **EX-D1** (H×H) [implied] Given any recipe, then the Case answer and the result record are the
  same as before part 2. Only member records may change from `"answered"` to `"excluded"`. This is
  a property test over the existing golden and evidence cases.
- **EX-D2** (H×M) [proposed] Given authored (constant) weights, then no member is ever excluded
  (X4): the spec check makes every authored weight usable. [existing E/combine/spec.py:145-151]
- **EX-D3** (H×M) [proposed] Given a signal weight on a reducer op that ignores weights (`mode@1`,
  `median@1`, `mean@1`), then no member is excluded (X5), because the weight did not count.
  [existing docs/spec/2026-10-13-e4b-combine-extensions/00-overview.md:101]
- **EX-D4** (H×M) [implied] Given a signal weight of 0, of a negative number, or above
  `MAX_WEIGHT`, then the member is `"excluded"` with `"no_weight"` (the same drop as today).
  [existing E/combine/endpoint.py:427]
- **EX-D5** (M×M) [proposed] Given an excluded member, then it is never in `chosen` and never the
  result member. The evidence validator checks this on both sides.
- **EX-D6** (M×M) [implied] Given `sf.Median(weights=...)` with `select="nearest"`, then an
  excluded member is never the nearest pick (part 1 P9 stays true).
  [existing E/combine/ports.py:290-291]
- **EX-D7** (M×L) [implied] Given a judge-weighted vote (`weights=sf.signal("score:judge")`), then
  a judge score of 0 or less excludes the member with `"no_weight"`.
- **EX-D8** (L×M) [implied] Given excluded members, then `dropped` does not count them, and the
  quorum and coverage counts do not change (they read the Case, not the record status).

## 4. Non-functional requirements

- O(n) over the members, no model call, no new I/O. [proposed]
- The exclusion is a pure function of the plan and the answers, so the same spec and context give
  the same records. [existing E/combine/ports.py:3]

## 5. Out of scope

- A new behavior: no member that votes today stops voting, and no member that is left out today
  starts voting. [proposed]
- Exclusion reasons for the declared signals of part 3. Part 3 reuses `no_signal`. [proposed]
- A count of excluded members. [proposed]

## 6. Open questions

None.

## 7. TDD plan

Order: characterize today's drops, then add the descriptor flag and the endpoint rule core-out.

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| 1 | CHAR `weighted_vote_drops_a_member_with_no_usable_weight` | unit | [existing E/combine/operators/reduce.py:73-78] | H×M | passes today |
| 2 | CHAR `filter_gives_a_missing_signal_mark_zero` | unit | [existing E/combine/operators/signals.py:132-137] | M×M | passes today |
| 3 | `case_answers_do_not_change_with_exclusion` | unit | EX-D1 | H×H | property over goldens and `evidence_cases.json` |
| 4 | `weighted_vote_records_no_weight_member_as_excluded` | unit | EX-1 | H×M | `_Plan.excludes`, `_member_record` |
| 5 | `all_members_without_weight_abstain_and_are_all_excluded` | unit | EX-E1 | H×H | rule runs in `_evidence`, also on abstain |
| 6 | `pick_by_signal_records_no_signal_member_as_excluded` | unit | EX-2 | H×M | X2 from `_signal_read` |
| 7 | `rank_by_signal_records_no_signal_member_as_excluded` | unit | EX-3 | H×M | X2 |
| 8 | `rank_with_no_signal_anywhere_abstains_with_all_excluded` | unit | EX-E2 | H×M | X2 on abstain |
| 9 | `filter_excludes_a_missing_signal_but_not_a_low_one` | unit | EX-4 | H×M | X2, threshold form only |
| 10 | `a_failed_member_stays_failed_when_its_signal_is_missing` | unit | EX-E3 | H×M | X3 first |
| 11 | `authored_weights_never_exclude` | unit | EX-D2 | H×M | X4 |
| 12 | `signal_weight_on_an_unweighted_op_never_excludes` | unit | EX-D3 | H×M | `reads_weights=False` |
| 13 | `zero_negative_and_over_cap_weights_exclude_with_no_weight` | unit | EX-D4 | H×M | boundary values 0, -1, cap, cap+ε |
| 14 | `excluded_member_is_never_chosen` | unit | EX-D5 | M×M | evidence validator, both sides |
| 15 | `weighted_median_nearest_never_picks_an_excluded_member` | unit | EX-D6 | M×M | passes with P9 |
| 16 | `judge_weight_of_zero_excludes_with_no_weight` | unit | EX-D7 | M×L | X1 |
| 17 | `dropped_and_quorum_ignore_excluded_members` | unit | EX-D8 | L×M | — |
| 18 | `sdk_run_shows_excluded_member_in_case_answers` | integration | EX-1, ES-4 | H×M | `run_candidate`, JSON replies |
