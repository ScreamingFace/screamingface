# PRD: Gate decision (the Engine chooses and records)

**Source:** ans:Q1 ("Chooses + records"), ans:Q2 (three numbers), ans:Q3 (three fallbacks)
· **Priority:** P0
**Lifecycle:** existing (characterize + delta)
**Owner:** unassigned
Paths: [erd §3–§5](../erd.md) · contracts: C3, C5, C6, C8, C9 · component: [gate-record](gate-record.md)

## 1. Summary and user story

As a researcher with a three-model majority vote, I want the combine step to keep the majority
answer only when the members agree enough (or when the chosen member is confident enough), and
otherwise to take the answer of a judge, of a writer, or to abstain, so that a weak majority does
not count as a confident answer. I want the step to record the number it compared, the comparison
and the branch, so that I can check and replay the decision from the evidence.

## 2. Background and constraints

- "Compute the agreement fraction from the panel (winner count / votes) ... If it is at least a
  threshold, the answer is the majority member's text ... If it is below, run the fallback."
  [stated epic]
- "Chooses + records": the fallback still runs; the gate picks the majority answer or the fallback
  answer, and records the comparison and the branch. [stated ans:Q1]
- The gate reads agreement, a declared signal of the chosen member, or the mean of a declared
  signal over the panel. [stated ans:Q2]
- Fallbacks: abstain (its own reason), the existing `sf.Judge` that copies, the existing model
  synthesizer that writes. [stated ans:Q3]
- The fraction is computed, not asked of a model. [stated epic]

### 2.1 Current behavior

- `_combine` (E/combine/endpoint.py:249-275) parses the spec and the context, computes the recorded
  signals (`_signal_values`, :278-295: the read key, then every declared name), reads the members,
  and returns `_abstain(... "no_votes")` when there is no voter (:273-274). Otherwise `_decide`.
- `_decide` (:411-437) runs reduce, then select. A `NoVotes` from either step gives `_abstain`
  (:424-429). Then `_output`, `_result`, `_evidence`.
- The select step of a vote writes `agreement` = winner score / total score
  (E/combine/operators/select.py:42-48): a count share for `mode@1`, a weight share for
  `weighted_mode@1`.
- `_evidence` (:736-790): `chosen = [] if selection is None else list(selection.chosen)`, `built =
  selection is not None and selection.output is not None`, `presentation_order = "author" if
  "judge" in combine_input.signals else None`.
- `judge_reply(signals, owner)` reads `signals["judge"]` with a 64 KiB cap (E/combine/ports.py:601-613).
  `parse_label(raw, members)` is in the plugin module E/combine/operators/judge.py:47-52. The core
  cannot import a plugin (part 3 erratum E1).
- `_SIGNAL = re.compile(r"judge|writer_[A-Za-z_][A-Za-z0-9_]*")` (E/combine/spec.py:53).

**Delta.**

1. `E/combine/spec.py`: `_SIGNAL = re.compile(r"judge|fallback_judge|fallback_writer|writer_[A-Za-z_][A-Za-z0-9_]*")`
   (one string literal: `ST/unit/test_signal_key_conformance.py:115-127` reads it with `ast`).
2. `E/combine/ports.py`: move `parse_label` and `_LABEL_INVALID` here, beside `parse_scores`.
   `E/combine/operators/judge.py` imports `parse_label` from ports and keeps it in its `__all__`, so
   `from screamingface_engine.combine.operators.judge import parse_label` still works. Give
   `judge_reply` a keyword `key: str = "judge"`; the message for a missing key becomes
   `f"{owner} needs the {key} signal"` only when `key != "judge"` (the `judge` text stays the same).
3. New pure module `E/combine/gate.py` (imports `math`, `operator`, `collections.abc`, and
   `combine.ports`, `combine.spec` types only):

   ```python
   def observed_number(
       gate: GateSpec, selection: Selection, recorded: Mapping[str, Mapping[str, float | None]],
       members: Sequence[str],
   ) -> float | None:
       """agreement: selection.agreement; chosen:<n>: recorded[chosen[0]][n];
       mean:<n>: math.fsum of the non-None recorded[m][n] over members / their count, None if none."""

   def passes(observed: float | None, cmp: GateCmp, threshold: float) -> bool:
       """False when observed is None (P10); else operator.ge/gt/le/lt(observed, threshold)."""

   def fallback_label(signals: Mapping[str, str], present: Sequence[str]) -> JudgeReading:
       """judge_reply(signals, "the gate fallback", key="fallback_judge"), then parse_label over present."""

   def fallback_text(signals: Mapping[str, str]) -> str:
       """signals["fallback_writer"]; SpecInvalid("the gate fallback needs the fallback_writer signal")."""

   def check_fallback_signals(gate: GateSpec | None, signals: Mapping[str, str]) -> None:
       """CX-I1: a fallback_* key that the gate does not name -> SpecInvalid(
       "a fallback signal needs a gate that names it")."""
   ```

4. `E/combine/endpoint.py`:
   - `_combine`: after `parse_context`, call `check_fallback_signals(spec.gate, context.signals)`.
   - Every "the vote found no answer" path (`no_votes` with no voter; a `NoVotes` from reduce or
     select) passes `gate=_not_run(spec)`: `None` when the spec has no gate, else
     `GateRecord(observe, observed=None, cmp, threshold, passed=None, branch=None, otherwise)`.
   - `_decide`: when `spec.gate is None`, nothing changes. Else, after the select step, call the new
     `_gated(spec, plan, combine_input, context, reduction, selection, trace, recorded=recorded)`:

     | `passes(...)` | `otherwise` | final selection | output | result | evidence extras |
     |---|---|---|---|---|---|
     | true | any | `selection` | `_output(selection, ...)` (today) | `_result(...)` (today) | `gate.branch = "majority"` |
     | false | `abstain` | — | `""` | `ResultRecord(None, None, "abstain", "gate_not_met")` | `chosen=[]`, `built=False`; `tally`, `agreement`, `tie` from `selection` |
     | false | `judge` | `Selection(chosen=(label,), tie=selection.tie, agreement=selection.agreement)` | the label member's text, byte for byte | that member's value | `judge` = the label reading; `presentation_order="author"` |
     | false | `writer` | `Selection(chosen=(), output=text, tie=selection.tie, agreement=selection.agreement)` | `text` (8 MiB cap through `_output`) | built, `value=text` | `built=True`, `chosen=[]` |

   - `_abstain` gets the keywords `selection: Selection | None = None` and `gate: GateRecord | None = None`.
   - `_evidence` gets the keyword `gate: GateRecord | None = None` and these two rules (they keep
     every existing evidence the same, because today an abstain has `selection is None`):
     `chosen = [] if result.status == "abstain" or selection is None else list(selection.chosen)`;
     `built = result.status == "answered" and selection is not None and selection.output is not None`.
     `presentation_order = "author" if "judge" in combine_input.signals or (gate is not None and
     gate.branch == "fallback" and gate.otherwise == "judge") else None`.
   - The fallback reply is read ONLY in the `false` rows (FB-I1, P8).

## 3. Scenarios and acceptance criteria

Fixture V (used below unless a scenario says otherwise): a vote spec over three members with
`extract last_line@1`, `normalize text@1`, `reduce mode@1`, `select first_holder@1`, no weights; the
member texts `"A"`, `"A"`, `"B"`. The values are `"a"`, `"a"`, `"b"`; the tally is
`[{"value": "a", "score": 2.0, "holders": ["member_1", "member_2"]},
{"value": "b", "score": 1.0, "holders": ["member_3"]}]`; the select step chooses `member_1`; the
agreement is 2/3 = `0.6666666666666666` (the float of `Decimal(2) / Decimal(3)`); `tie` is false.

### 3.1 Happy path

- **GD-1** Given fixture V and `gate = {agreement, >=, 0.6, abstain}`, then the output is `"A"`
  (member_1 text), `result = {"member_id": "member_1", "value": "a", "status": "answered", "reason":
  null}`, `chosen = ["member_1"]`, and `gate = {"observe": "agreement", "observed":
  0.6666666666666666, "cmp": ">=", "threshold": 0.6, "passed": true, "branch": "majority",
  "otherwise": "abstain"}`. [stated ans:Q1]
- **GD-2** Given fixture V and `gate = {agreement, >=, 0.7, abstain}`, then the output is `""`,
  `result = {"member_id": null, "value": null, "status": "abstain", "reason": "gate_not_met"}`,
  `chosen = []`, `built = false`, the tally as in V, `agreement = 0.6666666666666666`,
  `tie = false`, `judge = null`, and `gate.passed = false`, `gate.branch = "fallback"`. [stated ans:Q3]
- **GD-3** Given fixture V, `gate = {agreement, >=, 0.7, judge}` and the context signal
  `fallback_judge = " member_3\n"`, then the output is `"B"`, `result = {"member_id": "member_3",
  "value": "b", ...answered}`, `chosen = ["member_3"]`, `built = false`, `judge = {"raw":
  " member_3\n", "returns": "label", "parsed": "member_3"}`, `presentation_order = "author"`,
  `gate.branch = "fallback"`, `gate.otherwise = "judge"`. [stated ans:Q3]
- **GD-4** Given fixture V, `gate = {agreement, >=, 0.7, writer}` and `fallback_writer =
  "C written"`, then the output is `"C written"`, `result = {"member_id": null, "value":
  "C written", "status": "answered", "reason": null}`, `built = true`, `chosen = []`,
  `presentation_order = null`. [stated ans:Q3]
- **GD-5** Given a spec that declares `signals = {"conf": {"source": "verbalized", "pattern":
  "Confidence: ([0-9]+)"}}`, the V operators, the texts `"Confidence: 90\nA"`,
  `"Confidence: 60\nA"`, `"Confidence: 30\nB"`, and `gate = {chosen:conf, >=, 80, abstain}`, then
  `observed = 90.0`, `passed = true`, the output is `"Confidence: 90\nA"`. With threshold 95: the
  result abstains with `gate_not_met`, `observed = 90.0`. [stated ans:Q2]
- **GD-6** Given the GD-5 spec and texts with `gate = {mean:conf, >=, 50, abstain}`, then
  `observed = 60.0` ((90 + 60 + 30) / 3) and `passed = true`. Given the texts
  `"Confidence: 90\nA"`, `"Confidence: 60\nA"`, `"B"`, then `observed = 75.0` ((90 + 60) / 2: a
  None value is not counted). [stated ans:Q2]; [proposed] P12
- **GD-7** Given two members `"A"`, `"A"` (agreement 1.0): with `gate = {agreement, >=, 1.0,
  abstain}` the gate passes; with `gate = {agreement, >, 1.0, writer}` and `fallback_writer = "W"`
  the output is `"W"`. [stated epic "at least"]; [proposed] P4
- **GD-8** Given fixture V and `gate = {agreement, >=, 0.6, judge}`, then the evidence is the same
  bytes for these three contexts: no `fallback_judge` key; `fallback_judge = "member_3"`;
  `fallback_judge = "not a member id"`. None of them fails, `judge = null` and
  `presentation_order = null` in all three. [proposed] P8 (FB-I1)

### 3.2 Error paths

- **GD-E1** Given fixture V, `gate = {agreement, >=, 0.7, judge}` and `fallback_judge` =
  `"member_9"` or `"the third one"`, then `run_combine` raises `JudgeReplyInvalid`
  (`judge_reply_invalid`). The message holds neither reply. [existing judge rule]
- **GD-E2** Given fixture V, `gate = {agreement, >=, 0.7, judge}` and no `fallback_judge` key, then
  `SpecInvalid` with `"the gate fallback needs the fallback_judge signal"`. The same for a writer
  with `"... fallback_writer signal"`. [proposed] P18
- **GD-E3** Given fixture V with a `fallback_judge` signal and no gate, or a gate with
  `otherwise: "writer"`, or `otherwise: "abstain"`, then `SpecInvalid` with
  `"a fallback signal needs a gate that names it"`. [proposed] CX-I1
- **GD-E4** Given `gate = {agreement, >=, 0.7, writer}` and a `fallback_writer` of 8 MiB + 1 byte,
  then `InputTooLarge` (`combine_input_too_large`). [existing E/combine/endpoint.py:690-691]
- **GD-E5** Given `gate = {agreement, >=, 0.7, judge}` and a `fallback_judge` of 64 KiB + 1 byte,
  then `JudgeReplyInvalid` (`"the judge reply exceeds 64 KiB"`). [existing E/combine/ports.py:601-613]

### 3.3 Derived scenarios (risk-ordered)

- **GD-D1** (H×H) [proposed] P10 Given the texts `""`, `""`, `""` (no voter), `gate = {agreement,
  >=, 0.6, judge}` and `fallback_judge = "not a member id"`, then the result is
  `abstain` / `no_votes`, `gate = {"observe": "agreement", "observed": null, "cmp": ">=",
  "threshold": 0.6, "passed": null, "branch": null, "otherwise": "judge"}`, and no error (the
  reply is not read).
- **GD-D2** (H×M) [proposed] P10 Given the GD-5 spec, the texts `"A"`, `"Confidence: 60\nA"`,
  `"Confidence: 30\nB"`, and `gate = {chosen:conf, >=, 10, abstain}`, then the chosen member_1 has
  no `conf`: `observed = null`, `passed = false`, the result abstains with `gate_not_met`.
- **GD-D3** (H×M) [proposed] Given the GD-5 spec, fixture V texts (no confidence in any text) and
  `gate = {mean:conf, <=, 1000, abstain}`, then `observed = null`, `passed = false`, `gate_not_met`.
- **GD-D4** (M×M) [existing label@1 rule] Given the texts `"A"`, `"A"`, `""` (member_3 fails with
  `empty` but is present), `gate = {agreement, >, 1.0, judge}` and `fallback_judge = "member_3"`,
  then `agreement = 1.0`, the gate fails, and the result is `{"member_id": "member_3", "value":
  null, "status": "answered", "reason": null}` with the output `""`.
- **GD-D5** (M×M) [existing] Given a quorum panel context that leaves member_3 out (texts of
  member_1 and member_2 `"A"`, `"B"`), `gate = {agreement, >, 0.9, judge}` and
  `fallback_judge = "member_3"`, then `JudgeReplyInvalid` (a left-out member is not present).
- **GD-D6** (H×M) [proposed] P11 Given a weighted vote (`weights = {"member_1": 3.0, "member_2":
  1.0, "member_3": 1.0}`, `weighted_mode@1`, `max_weight_holder@1`), the texts `"A"`, `"B"`, `"B"`
  and `gate = {agreement, >=, 0.6, abstain}`, then the tally is `a: 3.0 [member_1]`,
  `b: 2.0 [member_2, member_3]`, `agreement = 0.6` (3 / 5), `observed = 0.6`, `passed = true`,
  `chosen = ["member_1"]`.
- **GD-D7** (H×M) [existing E/benchmarks/operation_outputs.py:94-111] Given a Case whose final
  operation has the GD-2 evidence, then `final_operation_abstained(...)` is true (the Case is
  `candidate_abstained`, so coverage counts it with the abstains).
- **GD-D8** (M×L) [existing E/combine/endpoint.py:244-245] Given GD-2, then the one combine log
  line ends with `outcome=abstain_gate_not_met`; its other fields are as today.
- **GD-D9** (H×M) [proposed] P19 The evidence contract fixture holds five gate cases, built with
  `builtin_vote_spec(3)` (`last_number@1`, `numeric@1`, `mode@1`, `first_holder@1`) and the texts
  `"The answer is 9"`, `"So 9"`, `"I get 12"` (tally `9: 2.0 [member_1, member_2]`,
  `12: 1.0 [member_3]`, agreement 0.6666666666666666):
  `vote_gate_majority` (`{agreement, >=, 0.6, abstain}`), `vote_gate_abstain`
  (`{agreement, >=, 0.7, abstain}`), `vote_gate_judge` (`{agreement, >=, 0.7, judge}`,
  `fallback_judge = "member_3"`), `vote_gate_writer` (`{agreement, >=, 0.7, writer}`,
  `fallback_writer = "It is 10"`), and `vote_gate_not_run` (texts `"none"`, `"no number"`,
  `"nothing"`; `{agreement, >=, 0.6, abstain}`). The 32 existing cases keep their bytes, and the
  abstain reasons of the scenarios cover `get_args(AbstainReason)`.
- **GD-D10** (M×M) [proposed] FC-I1 Given a judge-weighted vote (`weights = {"signal":
  "score:judge"}`, `weighted_mode@1`, `max_weight_holder@1`), fixture V texts, the signals
  `judge = '{"member_1": 0.2, "member_2": 0.3, "member_3": 0.9}'` and `fallback_judge =
  "member_1"`, and `gate = {agreement, >=, 0.7, judge}`, then the tally is `b: 0.9 [member_3]`,
  `a: 0.5 [member_1, member_2]`, `agreement = 0.6428571428571429` (`float(Decimal("0.9") /
  Decimal("1.4"))`), the gate fails, and the result is member_1 (the fallback judge, not the
  weights judge). `judge` holds the fallback label reading.

## 4. Non-functional requirements

- The gate adds O(members) work: one pass for `mean`, one lookup for `chosen`. No model call.
  [proposed]
- `math.fsum` gives the mean, so the member order does not change the number. [proposed]
- The combine core stays pure (C9).

## 5. Out of scope

- Not running the fallback call (E4c, D1). A scores judge fallback (D2). A gate on another reducer
  (D3). Sums of signals and the abstain band (part 6, D4).

## 6. Open questions

None.

## 7. TDD plan

Order: characterize the ungated vote, then the four branches on fixture V, then the declared-signal
numbers, then the errors, then the derived rows, then the contract fixture. New test file:
`ET/test_combine_gate.py` (rows 1–18, 20). Row 19 is the pinned contract fixture.

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| 1 | CHAR `ungated_vote_evidence_and_output_are_unchanged` (fixture V, the `vote_tie` and `vote_one_failed` cases byte-equal) | unit | — | H×M | passes today |
| 2 | `gate_passes_and_the_majority_answers` | unit | GD-1 | H×H | `gate.py`, `_gated` |
| 3 | `gate_fails_and_abstains_with_gate_not_met` | unit | GD-2 | H×H | abstain row; `_evidence` chosen/built rules |
| 4 | `gate_fails_and_the_fallback_judge_picks_a_member` (+ GD-D4 case) | unit | GD-3, GD-D4 | H×H | `fallback_label`, `parse_label` in ports |
| 5 | `gate_fails_and_the_fallback_writer_answers` | unit | GD-4 | H×H | `fallback_text` |
| 6 | `chosen_signal_gate_reads_the_chosen_members_value` | unit | GD-5 | H×M | `observed_number` |
| 7 | `mean_signal_gate_reads_the_fsum_mean_of_present_values` | unit | GD-6 | H×M | `math.fsum` |
| 8 | `equality_passes_for_ge_and_fails_for_gt` | unit | GD-7 | H×M | `operator` table |
| 9 | `majority_branch_never_reads_the_fallback_reply` | unit | GD-8 | H×H | FB-I1 |
| 10 | `no_voter_leaves_the_gate_not_run_and_reads_no_reply` | unit | GD-D1 | H×H | `_not_run` |
| 11 | `fallback_judge_reply_that_names_no_present_member_fails` (+ GD-D5 panel) | unit | GD-E1, GD-D5 | H×M | — |
| 12 | `fallback_branch_without_its_signal_is_spec_invalid` | unit | GD-E2 | M×M | — |
| 13 | `fallback_signal_without_a_matching_gate_is_spec_invalid` | unit | GD-E3 | M×M | `check_fallback_signals`, `_SIGNAL` |
| 14 | `oversize_writer_reply_is_input_too_large` | unit | GD-E4 | M×L | `_output` |
| 15 | `oversize_fallback_judge_reply_is_judge_reply_invalid` | unit | GD-E5 | M×L | `judge_reply(key=)` |
| 16 | `missing_observed_number_takes_the_fallback` | unit | GD-D2, GD-D3 | H×M | `passes(None)` is false |
| 17 | `weighted_vote_gate_reads_the_weight_share` | unit | GD-D6 | H×M | — |
| 18 | `gate_abstain_marks_the_case_abstained_and_logs_its_reason` | unit | GD-D7, GD-D8 | H×M | no change expected (CHAR-like after GREEN) |
| 19 | PIN `evidence_contract_fixture_has_the_five_gate_cases` (append builders and `SCENARIOS[...]` lines to `ET/test_combine_evidence_contract_fixture.py`; regenerate `evidence_cases.json`; append the names to `ST/test_combine_evidence_contract.py`; `ST/test_frozen_record_fields.py:184` 32 → 37) | unit | GD-D9 | H×M | pinned edits |
| 20 | `judge_weighted_vote_with_a_judge_fallback_reads_both_signals` | unit | GD-D10 | M×M | key `judge` vs `fallback_judge` |
