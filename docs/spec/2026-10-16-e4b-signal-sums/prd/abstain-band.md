# PRD: Abstain band (spec key, gate decision, gate record, the word `in_band`)

**Source:** ans:Q2 ("inside [lo, hi] the Case abstains with a NEW reason; outside, the gate
compares as today; recorded in the gate record") · **Priority:** P0 (band-api and
sum-band-display use it)
**Lifecycle:** existing (characterize + delta on the part 5 gate)
**Owner:** unassigned
Paths: [erd §3, §4, §5](../erd.md) · contracts: C4, C5, C7, C8 · used by: [band-api](band-api.md),
[sum-band-display](sum-band-display.md)

## 1. Summary and user story

As a benchmark author, I give a vote gate a borderline band: `sf.Gate("mean:risk", "<=", 3.0,
abstain_band=(2.5, 3.5))`. When the observed number is in the band, the Case abstains with the
reason `in_band` (a scored decline, "abstains to a human" in CodeX-Verify). When it is outside the
band, the gate keeps the majority or takes the fallback as in part 5. The evidence records the band
and the branch, so a reader can replay the decision.

This PRD owns the WORDS, the WIRE KEYS and the Engine DECISION, and the SDK evidence mirror (the
decoder must read the new contract case in the same unit). The SDK `sf.Gate` keyword, the compile
and the url4 round trip are [band-api](band-api.md).

## 2. Background and constraints

- "CodeX-Verify — borderline severity band abstains to a human instead of forcing a verdict."
  [stated epic behavior 4]
- "Abstain is a distinct outcome, not an empty string that looks like a wrong answer. Coverage
  counts it separately." [stated epic]
- E4c: "`fail_closed` versus abstain. Abstain is a scored decline. Fail-closed is an error. They
  must not share a status code." [stated OME-1291]
- Part 5 FB-I1: the majority branch never reads a fallback reply, so E4c can skip the call with no
  wire change. The band branch must keep this property. [existing part 5 P8]
- The gate record keeps its part 5 bytes when there is no band. [stated brief]

### 2.1 Current behavior

- `GateSpec` (E/combine/spec.py:172-182): `observe`, `cmp`, `threshold`, `otherwise`; closed.
  `_check_gate` (:238-252) and `_check_agreement_gate` (:255-259).
- `_gated` (E/combine/endpoint.py:491-533): computes `observed`, then `passed`, then the record,
  then the branch. `_not_run` (:592-596) and `_gate_record` (:599-609) build the record.
- `GateRecord` (E/combine/evidence.py:113-140) with GR-I1 and GR-I2; `_gate_reason_holds`
  (:168-174, GR-I3); `CombineEvidence._check_gate` (:245-275, GR-I3 first, then GR-I1 evidence
  part, GR-I4, GR-I5).
- `AbstainReason`, `AnswerReason`, `ABSTAIN_REASONS`, `GateBranch` (E/combine/ports.py:55-80).
- SDK: `GateBranch` (S/combine_evidence.py:41), `CombineGate` (:197-246), `_check_gate`
  (:486-516), `_gate_reason` (:629-634); `_GATE_KEYS` and `_gate` (S/_evaluation/combine_evidence.py:73,
  :200-215); `AbstainReason`, `AnswerReason` (S/answer.py:29-46).

**Delta (Engine).**

```python
# E/combine/ports.py
AbstainReason = Literal["no_votes", "cut_not_met", "output_missing", "gate_not_met", "in_band"]
AnswerReason = Literal[..., "output_missing", "gate_not_met", "in_band"]
ABSTAIN_REASONS = ("no_votes", "cut_not_met", "output_missing", "gate_not_met", "in_band")
GateBranch = Literal["majority", "fallback", "band"]

# E/combine/spec.py
class GateSpec(_SpecModel):
    observe: str
    cmp: GateCmp
    threshold: float
    otherwise: GateOtherwise
    abstain_band: list[float] | None = Field(default=None, min_length=2, max_length=2)  # new
# _check_gate, after the observe rules: when "abstain_band" is in gate.model_fields_set,
#   _check_band(gate).

# E/combine/gate.py
def in_band(observed: float | None, band: Sequence[float] | None) -> bool:
    """True when the band is set and lo <= observed <= hi; False for a missing number (P10)."""

# E/combine/endpoint.py, _gated: after `observed = observed_number(...)`, and BEFORE `passes`:
#   if in_band(observed, gate.abstain_band):
#       record = _gate_record(gate, observed, None, "band")
#       return _abstain(spec, plan, combine_input, reduction, "in_band", recorded=recorded,
#                       selection=selection, gate=record)
#   (trace.agreement and trace.tie are set before this check, as part 5 erratum E2 says.)
#   Outside the band: passed = passes(...), then
#   record = _gate_record(gate, observed, passed, "majority" if passed else "fallback").
# _gate_record(gate, observed, passed, branch: GateBranch | None): the caller gives the branch;
#   the function no longer derives it from `passed`. _gated gives "band", "majority" or
#   "fallback"; _not_run gives _gate_record(gate, None, None, None). WHY a branch argument and not
#   a `band: bool` flag: a flag is valid only with passed=None, so a caller could build a record
#   that the model refuses at run time. The function copies
#   abstain_band = list(gate.abstain_band) when the spec has one, else None.

# E/combine/evidence.py
class GateRecord(_EvidenceModel):
    ...  # the seven part 5 fields, unchanged order
    abstain_band: list[float] | None = Field(
        default=None, min_length=2, max_length=2, exclude_if=lambda value: value is None
    )
```

`_check_band(gate)` failures (fixed messages, no value echoed):

| Rule | Message |
|---|---|
| explicit null | `"gate abstain_band must be a pair when present"` |
| `lo > hi` | `"a gate abstain_band needs lo <= hi"` |
| `observe == "agreement"` and not `0 <= lo <= hi <= 1` | `"an agreement gate abstain_band is between 0 and 1"` |

A list that is not two numbers fails inside `GateSpec` and gives the existing quiet message
`"gate must be a valid gate object"` (E/combine/spec.py:208-215).

`GateRecord._check`, in this order (the part 5 messages stay for the part 5 cases):

1. the observe grammar (existing);
2. GB-I1: `abstain_band` is None or `lo <= hi` → `"a gate band is two numbers lo <= hi"`;
3. when `branch == "band"`: `passed is None` → else `"a gate in its band made no comparison"`;
   `abstain_band` is set, `observed` is a number and `lo <= observed <= hi` → else
   `"a gate band branch observed a number inside its band"`;
4. when `branch != "band"`: GR-I1 and GR-I2 exactly as today;
5. GB-I3: `abstain_band` set, `branch` in (`majority`, `fallback`), `observed` a number →
   `observed < lo or observed > hi`, else `"a gate that compared observed a number outside its band"`.

Rules 2, 3 and 5 go in a new module-level helper `_check_band_record(record: GateRecord) -> None`
in E/combine/evidence.py. `_check` calls it after rule 1, and runs rule 4 only when
`branch != "band"`. WHY a helper: part 5 erratum E3 says the gate checks are at the lint
complexity limit (PLR0912, C901); three more rules inside `_check` would fail the lint gate.

`CombineEvidence._check_gate` gets GB-I4 FIRST, before GR-I3 (message `"in_band goes with a gate
that abstained inside its band, and only with it"`), and GR-I4 reads `gate.branch is not None`
instead of `gate.passed is not None`. GB-I4 is a new small helper
`_band_reason_holds(gate: GateRecord | None, result: ResultRecord) -> bool` (the twin of
`_gate_reason_holds`, E/combine/evidence.py:168-174): `(result.reason == "in_band") == (gate is
not None and gate.branch == "band")`. `_check_gate` calls it on its first line, then the
existing GR-I3 check.

**Delta (SDK).**

- `S/answer.py`: `in_band` after `gate_not_met` in `AbstainReason` and in `AnswerReason`.
- `S/combine_evidence.py`: `GateBranch` gains `"band"`. `CombineGate` gets the last field
  `abstain_band: tuple[float, float] | None = None`; `__post_init__` checks it (two finite numbers,
  `lo <= hi`; a list is stored as a tuple of floats) and runs the same rules 3–5 with the prefix
  `"Combine gate"` (for example `"Combine gate in its band made no comparison"`). The band rules
  go in a module-level helper `_check_band_gate(gate: CombineGate) -> None` that `__post_init__`
  calls (the same lint reason as the Engine helper). `to_dict()` writes `"abstain_band": [lo, hi]`
  after `"otherwise"`, only when set. `_check_gate` reads `branch is not None` for GR-I4.
  `_gate_reason` checks GB-I4 FIRST (the same message as the Engine), then GR-I3. WHY this order:
  `CombineEvidence.__init__` calls `_gate_reason` before `_check_gate` (part 5 erratum E3); with
  GR-I3 first, a `band` gate with the reason `gate_not_met` (the second AB-E3 input) fails with
  the GR-I3 message, and AB-E3 expects the `in_band` message.
- `S/_evaluation/combine_evidence.py`: `_gate` accepts the exact key set `_GATE_KEYS` or
  `_GATE_KEYS | {"abstain_band"}`; the band value is a list of two numbers (not bool).

## 3. Scenarios and acceptance criteria

Fixture B: `builtin_vote_spec(3)` and the texts `["The answer is 9", "So 9", "I get 12"]` (the
part 5 `_GATE_TEXTS`, ET/test_combine_evidence_contract_fixture.py:380). The tally is
`[{"value": "9", "score": 2.0, "holders": ["member_1", "member_2"]}, {"value": "12", "score": 1.0,
"holders": ["member_3"]}]`, the chosen member is member_1, `agreement == 0.6666666666666666`.
`band(lo, hi, threshold, otherwise)` below is the gate `{"observe": "agreement", "cmp": ">=",
"threshold": threshold, "otherwise": otherwise, "abstain_band": [lo, hi]}`.

### 3.1 Happy path

- **AB-1** Given a vote spec with `band(0.6, 0.7, 0.7, "abstain")`, then `parse_spec` gives
  `gate.abstain_band == [0.6, 0.7]`. [stated ans:Q2]
- **AB-2** Given fixture B and `band(0.6, 0.7, 0.7, "abstain")`, then the output is `""`, and the
  evidence has `chosen == []`, `built is False`, the fixture B tally and agreement, `tie is False`,
  `gate == {"observe": "agreement", "observed": 0.6666666666666666, "cmp": ">=", "threshold":
  0.7, "passed": None, "branch": "band", "otherwise": "abstain", "abstain_band": [0.6, 0.7]}` in
  this key order, and `result == {"member_id": None, "value": None, "status": "abstain",
  "reason": "in_band"}`. [stated ans:Q2]
- **AB-3** Given fixture B and `band(0.7, 0.9, 0.6, "abstain")` (the number is below the band),
  then `passed is True`, `branch == "majority"`, the output is `"The answer is 9"`, and the evidence
  equals the contract case `vote_gate_majority` except that its gate record ends with
  `"abstain_band": [0.7, 0.9]`. [stated ans:Q2 "outside, the gate compares as today"]
- **AB-4** Given fixture B and `band(0.1, 0.5, 0.7, "abstain")` (the number is above the band),
  then `passed is False`, `branch == "fallback"`, and the result abstains with `gate_not_met`.
  [stated ans:Q2]

### 3.2 Error paths

- **AB-E1** Given a vote spec with each of these gates, then `parse_spec` raises `SpecInvalid`,
  and the message holds none of `0.75`, `1.5`, `0.7`: `"abstain_band": null`; `[0.75, 0.7]`;
  `[0.6]`; `[0.1, 0.2, 0.3]`; `["a", 0.7]`; `[true, 0.7]`; an agreement gate with `[0.5, 1.5]`;
  an agreement gate with `[-0.1, 0.5]`. A `chosen:<name>` gate with `[-5.0, 1.5]` is valid.
  [proposed] P7
- **AB-E2** Given an Engine `GateRecord` with `branch="band"` and `passed=False`; or
  `branch="band"` and no band; or `branch="band"`, band `[0.6, 0.7]` and `observed=0.8`; or
  `branch="majority"`, `passed=True`, band `[0.6, 0.7]` and `observed=0.65`; or band `[0.7, 0.6]`,
  then a `ValidationError` with the message of §2.1. The part 5 inputs (`passed=True,
  branch="fallback"`, `passed=None, branch="majority"`, `passed=None, observed=0.5`) still fail
  with their part 5 messages. [proposed] P10
- **AB-E3** Given a `CombineEvidence` with `result.reason == "in_band"` and a gate on the
  `fallback` branch, or with a gate on the `band` branch and `result.reason == "gate_not_met"`,
  then a `ValidationError` (Engine) and a `ValueError` (SDK) with `"in_band goes with a gate that
  abstained inside its band, and only with it"`. [proposed] P12

### 3.3 Derived scenarios (risk-ordered)

- **AB-D1** (H×H) [proposed] P8 The band is closed: `band(0.6666666666666666, 0.8, 0.7,
  "abstain")` abstains with `in_band`; `band(0.6, 0.6666666666666665, 0.7, "abstain")` and
  `band(0.6666666666666667, 0.9, 0.7, "abstain")` do not, and take the fallback with
  `gate_not_met` (`observed` 0.6666666666666666 is outside both).
- **AB-D2** (H×H) [proposed] P9, FB-I1 The band wins over a judge or a writer fallback, and the band
  branch reads no fallback reply: `band(0.6, 0.7, 0.7, "judge")` with the context signal
  `{"fallback_judge": "member_3"}` and with no context signal give the same evidence bytes:
  `in_band`, `judge` null, `presentation_order` null. The same for `"writer"` with
  `{"fallback_writer": "It is 10"}` and with no signal.
- **AB-D3** (H×M) [stated ans:Q2]; [existing part 5 P10] A missing number skips the band: a vote with
  `signals={"conf": verbalized "Confidence: ([0-9]+)"}`, fixture B texts (no `Confidence:` line)
  and the gate `{"observe": "chosen:conf", "cmp": ">=", "threshold": 80, "otherwise": "abstain",
  "abstain_band": [50.0, 90.0]}` gives `observed None`, `passed False`, `branch "fallback"`,
  `gate_not_met`.
- **AB-D4** (H×M) [existing part 5 GR-I1] A vote with no answer (texts `["none", "no number",
  "nothing"]`) and `band(0.6, 0.7, 0.6, "abstain")` gives `observed/passed/branch` null, the
  record keeps `"abstain_band": [0.6, 0.7]`, and the result keeps `no_votes`.
- **AB-D5** (H×M) [implied] No part 5 record changes bytes: the five `vote_gate_*` cases of list L37
  have exactly the seven part 5 keys, and the four part 5 gate specs in list L47 parse with
  `abstain_band is None`.
- **AB-D6** (M×M) [existing E/benchmarks/operation_outputs.py:94-111] An operation whose evidence is
  the AB-2 evidence is final-abstained: `final_operation_abstained("$synthesis_1", [op]) is True`
  (exemplar: `ET/test_combine_gate.py:540-557`, which builds the `OperationOutput` and asserts
  `final_operation_abstained(expression, operations) is True` for `gate_not_met`).
- **AB-D7** (M×M) [existing P20 of part 5] The combine log line of AB-2 ends with
  `outcome=abstain_in_band`.
- **AB-D8** (M×M) [proposed] P12 The Engine `ABSTAIN_REASONS` is
  `("no_votes", "cut_not_met", "output_missing", "gate_not_met", "in_band")`;
  `NoVotes(reason="in_band")` is accepted; the SDK `ANSWER_REASONS` equals the Engine
  `AnswerRecord.reason` enum words (14 words).

## 4. Non-functional requirements

- The band adds at most about 40 bytes to one gate record. [proposed]
- `E/combine/gate.py` keeps its import rule (standard library, `combine.ports`, `combine.spec`).
  [existing part 5 C9]

## 5. Out of scope

- The SDK keyword and the url4 round trip ([band-api](band-api.md)); the display
  ([sum-band-display](sum-band-display.md)).
- A band on a reducer other than `sf.Vote` (part 5 D3).
- Skipping the fallback call on the band branch (E4c).

## 6. Open questions

None.

## 7. TDD plan

New test files: `ET/test_combine_band.py` (rows 1–11), `ST/test_band_words.py` (rows 12–14).
Row 16 inserts one scenario builder `_vote_gate_band` and the line
`SCENARIOS["vote_gate_band"] = _vote_gate_band` into `ET/test_combine_evidence_contract_fixture.py`
directly after the unit 1 `pick_sum_min` block, which is after line 418 (the part 5 gate block) and
before `def canonical_evidence` (line 421 on base). Do NOT append it at the end of the file: the
file ends with `if __name__ == "__main__": write_fixture()` (lines 491-492), so a line after it is
not run when the file runs as a script, and `@pytest.mark.parametrize("name", sorted(SCENARIOS))`
(line 442) reads `SCENARIOS` when the decorator runs, so a later scenario gets no byte test. Row 16
also appends one `_EXPECTED_NAMES |=` line to `ST/test_combine_evidence_contract.py` after line 61
(after the unit 1 line). The append-only check does not flag these two files: a new module-level
statement between protected ranges is not inside a range.

Units (plan §2): rows 1–3 and the spec v1 half of row 15 are unit 3 (band-spec); rows 4–14, the
evidence v1 and answer.v1 half of row 15, and rows 16–18 are unit 4 (band-record). The SDK mirror
stays in unit 4 with the contract case, because the SDK tests loop over every Engine case.

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| 1 | CHAR `part_5_gate_records_and_specs_have_no_band` (the five `vote_gate_*` names of list L37 have exactly the seven part 5 gate keys; the four `gate_*_vote_candidate.url4` of list L47 parse with `getattr(spec.gate, "abstain_band", None) is None`, so the row passes on base) | unit | AB-D5 | H×M | passes today |
| 2 | `engine_parses_a_gate_band` | unit | AB-1 | H×M | `GateSpec.abstain_band` |
| 3 | `engine_refuses_bad_bands_without_echo` (parametrized, AB-E1) | unit | AB-E1 | H×M | `_check_band` |
| 4 | `a_number_inside_the_band_abstains_with_in_band` (the full AB-2 evidence) | unit | AB-2 | H×H | `in_band`, `_gated`, `_gate_record` |
| 5 | `band_edges_are_closed` (AB-D1, three bands) | unit | AB-D1 | H×H | — |
| 6 | `outside_the_band_the_gate_compares_as_today` (AB-3, AB-4) | unit | AB-3, AB-4 | H×H | — |
| 7 | `the_band_wins_over_a_fallback_and_reads_no_fallback_reply` (AB-D2, four runs, two equal pairs) | unit | AB-D2 | H×H | — |
| 8 | `a_missing_number_skips_the_band` | unit | AB-D3 | H×M | — |
| 9 | `a_vote_with_no_answer_records_the_band_and_does_not_run` | unit | AB-D4 | H×M | `_not_run` |
| 10 | `gate_record_band_invariants_refuse_mismatches` (AB-E2) and `in_band_needs_the_band_branch` (AB-E3, Engine) | unit | AB-E2, AB-E3 | H×M | `GateRecord._check`, `_check_gate` |
| 11 | `in_band_is_a_final_abstain_and_logs_its_outcome` (AB-D6, AB-D7) and `in_band_is_an_abstain_word` (AB-D8, Engine half) | unit | AB-D6–D8 | M×M | ports |
| 12 | `sdk_decodes_and_round_trips_a_band_record` (the AB-2 wire; `CombineGate.abstain_band == (0.6, 0.7)`; `to_dict() == wire`) | unit | AB-2 | H×M | `_gate`, `CombineGate` |
| 13 | `sdk_refuses_bad_band_records` (AB-E2 and AB-E3 twins, an extra gate key, `"abstain_band": [0.6]`, `[true, 0.7]`) | unit | AB-E2, AB-E3 | M×M | `__post_init__`, `_gate_reason` |
| 14 | `sdk_reason_words_equal_the_engine_enum_with_in_band` (AB-D8, 14 words) | unit | AB-D8 | H×M | `S/answer.py` |
| 15 | PIN, two test functions. Unit 3: `spec_schema_snapshot_holds_the_band` (spec v1: `GateSpec.abstain_band`, not required); regenerate the spec v1 snapshot. Unit 4: `evidence_and_answer_snapshots_hold_the_band` (evidence v1: `GateRecord.abstain_band`, not required, `branch` enum `["majority", "fallback", "band"]`, `in_band` last in the two reason enums; answer.v1 holds `in_band` in both lists); regenerate the evidence v1 and answer.v1 snapshots, and make the pinned test edits of plan §6 unit 4. Two functions, so unit 4 adds a test and does not edit the unit 3 test | unit | erd §7 | H×M | delete, `UPDATE_SCHEMA_SNAPSHOT=1`, plain run (test-plan §2) |
| 16 | PIN `contract_case_vote_gate_band_is_byte_equal_on_both_sides` (new scenario `vote_gate_band` = AB-2). Regenerate `evidence_cases.json` (38 → 39; the 38 keep their bytes); `ST/test_frozen_record_fields.py:184` 38 → 39 | unit | AB-2 | H×M | `write_fixture` |
| 17 | `the_majority_branch_record_with_a_band_is_the_part_5_record_plus_the_band` (AB-3 bytes against the `vote_gate_majority` case) | unit | AB-3, AB-D5 | H×M | key order |
| 18 | PIN `public_surface_holds_the_combine_gate_band` (`ST/public_surface_snapshot.json`: `CombineGate` gains the field and the `__init__` keyword `abstain_band`) | unit | AB-2 | M×M | `UPDATE_SURFACE_SNAPSHOT=1`, then a plain run |
