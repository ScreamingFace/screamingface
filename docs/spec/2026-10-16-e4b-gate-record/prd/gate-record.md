# PRD: Gate record (spec key, evidence record, abstain word)

**Source:** ans:Q1 ("records the comparison and the branch"), ans:Q3 (abstain with its own reason)
· **Priority:** P0 (gate-decision, gate-api and gate-display use it)
**Lifecycle:** existing (characterize + delta)
**Owner:** unassigned
Paths: [erd §1, §4, §5](../erd.md) · contracts: C1, C3, C5 · used by: [gate-decision](gate-decision.md),
[gate-api](gate-api.md), [gate-display](gate-display.md)

## 1. Flows served

This is a component PRD. It owns the WORDS and the WIRE KEYS of the gate on both sides: the spec key
`gate`, the evidence record `gate`, the abstain reason `gate_not_met`, and the SDK public type
`sf.report.CombineGate`. No code writes a gate record yet; [gate-decision](gate-decision.md) does
that. The part 2 unit 1 precedent ("words and schema") applies.

## 2. Background and constraints

- "Records the comparison and the branch." [stated ans:Q1]
- "Abstain is a distinct outcome ... Coverage counts it separately." [stated epic]
- New optional keys keep the bytes of every existing evidence when absent. [stated owner order rule,
  part 3 contracts C6]
- E4c's `fail_closed` must not share a status code with abstain. [stated OME-1291]

### 2.1 Current behavior

- `CombineSpec` (E/combine/spec.py:168-196) has the keys `schema` … `weights` and the optional
  `signals`; it forbids any other key (`extra="forbid"`, :106).
- `CombineEvidence` (E/combine/evidence.py:133-192) writes `signal`, the optional `cut` and
  `declared`, then `result`. `ResultRecord.reason` is an `AbstainReason` (:76-90).
- `AbstainReason = Literal["no_votes", "cut_not_met", "output_missing"]` and `ABSTAIN_REASONS`
  (E/combine/ports.py:53,67). `AnswerReason` ends with the same three words (:54-66).
- SDK: `AbstainReason`, `AnswerReason` (S/answer.py:29-45); `CombineEvidence` (S/combine_evidence.py:258-395)
  with `to_dict` that writes the optional keys with `**({} if x is None else {...})`;
  `decode_combine_evidence` with `_OPTIONAL_EVIDENCE_KEYS = {"mean", "cut", "declared"}`
  (S/_evaluation/combine_evidence.py:64,76-86).
- SDK spec decode: `_OPTIONAL_SPEC_KEYS = {"signals"}` (S/_evaluation/combine_spec.py:23).

**Delta (Engine).**

```python
# E/combine/ports.py
AbstainReason = Literal["no_votes", "cut_not_met", "output_missing", "gate_not_met"]
AnswerReason = Literal[..., "no_votes", "cut_not_met", "output_missing", "gate_not_met"]
ABSTAIN_REASONS: tuple[AbstainReason, ...] = ("no_votes", "cut_not_met", "output_missing", "gate_not_met")
GateCmp = Literal[">=", ">", "<=", "<"]
GateOtherwise = Literal["abstain", "judge", "writer"]
GateBranch = Literal["majority", "fallback"]
GATE_OBSERVE = re.compile(r"agreement|(chosen|mean):[a-z][a-z0-9_]{0,31}")  # the declared-name rule

# E/combine/spec.py
class GateSpec(_SpecModel):
    """``gate``: keep the majority when ``observe cmp threshold`` holds (E4b part 5)."""
    observe: str
    cmp: GateCmp
    threshold: float
    otherwise: GateOtherwise

class CombineSpec(_SpecModel):
    ...
    signals: dict[str, DeclaredSource] | None = None
    gate: GateSpec | None = None          # new, optional
    # _check adds _check_gate(self)
```

`_check_gate(spec)` (only when `"gate" in spec.model_fields_set`), each failure a `ValueError` with a
fixed message (pydantic turns it into `combine_spec_invalid`):

| Rule | Message |
|---|---|
| explicit null | `"gate must be an object when present"` |
| reducer is not `vote` | `"only a vote takes a gate"` |
| `GATE_OBSERVE.fullmatch(observe)` is None | `"gate observe must be agreement, chosen:<name> or mean:<name>"` |
| `chosen:`/`mean:` name not in `spec.signals` | `"gate reads a name the spec does not declare"` |
| `agreement` and `cmp` not in (`>=`, `>`) | `"an agreement gate compares with >= or >"` |
| `agreement` and not `0 <= threshold <= 1` | `"an agreement gate threshold is between 0 and 1"` |

`GateSpec` gets the same wrap validator as `signals` (E/combine/spec.py:181-188), so a nested pydantic
error says `"gate must be a valid gate object"` and never echoes a value.

```python
# E/combine/evidence.py
class GateRecord(_EvidenceModel):
    """What the gate compared and which branch the step took (E4b part 5, ans:Q1)."""
    observe: str
    observed: float | None
    cmp: GateCmp
    threshold: float
    passed: bool | None
    branch: GateBranch | None
    otherwise: GateOtherwise
    # _check: GR-I1 (passed None <=> branch None; then observed None), GR-I2

class CombineEvidence(_EvidenceModel):
    ...
    declared: ... = Field(default=None, exclude_if=lambda value: value is None)
    gate: GateRecord | None = Field(default=None, exclude_if=lambda value: value is None)   # new
    verifier: None = Field(default=None, exclude_if=lambda value: value is None)           # new, verifier-slot
    result: ResultRecord
    ...
    # _check adds GR-I3, GR-I4, GR-I5 (erd §4)
```

**Delta (SDK).**

- `S/answer.py`: add `"gate_not_met"` to `AbstainReason` and to `AnswerReason` (after
  `"output_missing"`, before the exclude reasons).
- `S/combine_evidence.py`: new frozen dataclass `CombineGate` with the seven fields in record order,
  `__post_init__` checks (types, the `observe` grammar, GR-I1, GR-I2), and `to_dict()` in record
  order. `CombineEvidence` gets the keyword `gate: CombineGate | None = None`; it checks GR-I3,
  GR-I4, GR-I5 and writes `**({} if self.gate is None else {"gate": self.gate.to_dict()})` after
  `declared` and before `result`.
- `S/report.py`: export `CombineGate` (`sf.report.CombineGate`, beside `CombineCut`, :43, :1107).
- `S/_evaluation/combine_evidence.py`: `_OPTIONAL_EVIDENCE_KEYS` adds `"gate"` (and `"verifier"`,
  [verifier-slot](verifier-slot.md)); `_GATE_KEYS = {"observe", "observed", "cmp", "threshold",
  "passed", "branch", "otherwise"}` exact; a `_gate(raw, label)` decoder.
- `S/_evaluation/combine_spec.py`: `_OPTIONAL_SPEC_KEYS = frozenset({"signals", "gate"})`;
  `_is_spec` accepts `gate` when it is a dict (the rebuild checks it, [gate-api](gate-api.md)).

## 3. Scenarios and acceptance criteria

### 3.1 Happy path

- **GR-1** Given the spec text of an E4a three-member vote plus
  `"gate":{"cmp":">=","observe":"agreement","otherwise":"abstain","threshold":0.7}`, then
  `parse_spec` returns a `CombineSpec` whose `gate` is
  `GateSpec(observe="agreement", cmp=">=", threshold=0.7, otherwise="abstain")`. [stated ans:Q2]
- **GR-2** Given a `CombineEvidence` with
  `gate=GateRecord(observe="agreement", observed=0.6666666666666666, cmp=">=", threshold=0.7,
  passed=False, branch="fallback", otherwise="abstain")` and
  `result=ResultRecord(member_id=None, value=None, status="abstain", reason="gate_not_met")`, then
  `model_dump(mode="json", by_alias=True)` has the top-level keys in this order: `schema`, `kind`,
  `reducer`, `operators`, `members`, `tally`, `judge`, `fields`, `chosen`, `built`, `agreement`,
  `tie`, `median`, `presentation_order`, `separator_collision`, `signal`, `gate`, `result`,
  `dropped`, `finish_reason`; and `gate` has the keys `observe`, `observed`, `cmp`, `threshold`,
  `passed`, `branch`, `otherwise`, in that order. [proposed] P9
- **GR-3** Given that wire (GR-2, `agreement` 0.6666666666666666, `chosen` [], tally
  `[{"value":"a","score":2.0,"holders":["member_1","member_2"]},{"value":"b","score":1.0,"holders":["member_3"]}]`),
  then `decode_combine_evidence(wire, "x")` returns a `CombineEvidence` whose `gate` is a
  `CombineGate` with the same seven values, and `to_dict() == wire`. [proposed]
- **GR-4** Given any of the 32 existing scenarios of `ET/data/combine_contract/evidence_cases.json`,
  then its Engine bytes and its SDK round trip do not change, and no wire has `gate` or
  `verifier`. [implied]
- **GR-5** Given the SDK `sf.Answer(member_id=None, text="", raw=None, value=None, status="abstain",
  reason="gate_not_met", signals={})`, then it is valid; and
  `CombineResult(member_id=None, value=None, status="abstain", reason="gate_not_met")` is valid.
  [proposed] P13

### 3.2 Error paths

- **GR-E1** Given a spec with `gate` and `"reducer": "median"` (or `rank`), or with `"gate": null`,
  then `parse_spec` raises `SpecInvalid` (`combine_spec_invalid`). [proposed] P1
- **GR-E2** Given a vote spec with each of these gates, then `parse_spec` raises `SpecInvalid`, and
  the message holds none of `cost_usd`, `zzz`, `9.5`: `observe: "chosen:zzz"` with no `signals`;
  `observe: "chosen:cost_usd"`; `observe: "consensus"`; `cmp: "=="`; `observe: "agreement"` with
  `cmp: "<"`; `observe: "agreement"` with `threshold: 9.5`; `otherwise: "retry"`; a missing
  `threshold`; an extra key `"note": 1`. [proposed]
- **GR-E3** Given an Engine `GateRecord` with `passed=True, branch="fallback"`, or `passed=None,
  branch="majority"`, or `passed=None, observed=0.5`, then a `ValidationError`. Given a
  `CombineEvidence` with `result.reason == "gate_not_met"` and no gate, or a gate with
  `branch="fallback", otherwise="judge"` and `result.reason == "gate_not_met"`, or an agreement gate
  with `observed=0.5` and `agreement=0.6`, then a `ValidationError`. [proposed] GR-I1..I5
- **GR-E4** Given the GR-3 wire with an extra gate key, a missing gate key, `"passed": "no"`, or
  `"branch": "maybe"`, then `decode_combine_evidence` raises `ExecutionError`. [existing strict decoder]

### 3.3 Derived scenarios (risk-ordered)

- **GR-D1** (H×M) [proposed] Given an evidence with `signal`, `cut`, `declared` and `gate` all set,
  then the keys are in the order `signal`, `cut`, `declared`, `gate`, `result`.
- **GR-D2** (H×M) [implied] The schema ids stay `screamingface.combine-spec.v1` and
  `screamingface.combine-evidence.v1`; the new keys are not in `required`.
- **GR-D3** (M×M) [proposed] The Engine `ABSTAIN_REASONS` is
  `("no_votes", "cut_not_met", "output_missing", "gate_not_met")`, and `NoVotes(reason="gate_not_met")`
  is accepted (the gate does not use it; the word set is one list).
- **GR-D4** (H×M) [existing ST/test_evidence_words.py:361-372] The SDK `ANSWER_REASONS` equals the
  Engine `AnswerRecord.reason` enum words: 13 words, that is the Engine `AnswerReason` (11 with
  `gate_not_met`) and the two exclude words.
- **GR-D5** (M×M) [proposed] A `CombineGate` refuses `observed=float("nan")`, `threshold=True`, an
  `observe` of `"chosen:Cost"`, and `cmp="=>"`, with `TypeError` or `ValueError`.
- **GR-D6** (M×L) [proposed] The SDK spec decoder `decode_combine_spec` accepts a spec with a `gate`
  dict and refuses a spec whose `gate` is a list (the "invalid combine spec" error).

## 4. Non-functional requirements

- The record adds at most about 160 bytes to one evidence. [proposed]
- No new dependency. The Engine record module still imports only pydantic and `combine.ports`
  (E/combine/evidence.py:11-13). [existing]

## 5. Out of scope

- Writing the record (gate-decision), the SDK constructor `sf.Gate` (gate-api), the display
  (gate-display).
- A `verify` spec key (P15).

## 6. Open questions

None.

## 7. TDD plan

Order: characterize the existing bytes, then the words, then the Engine models, then the SDK mirror.
New test files: `ET/test_combine_gate_words.py`, `ST/test_gate_words.py`.

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| 1 | CHAR `existing_evidence_and_specs_have_no_gate_key` (the 32 cases on both sides; every `ET/data/combine_contract/*.url4` spec parses with `gate is None`) | unit | GR-4 | H×M | passes today |
| 2 | `gate_not_met_is_an_abstain_word_on_both_sides` | unit | GR-5, GR-D3 | H×M | ports and S/answer.py |
| 3 | `engine_parses_a_gate_on_a_vote_spec` | unit | GR-1 | H×M | `GateSpec`, `CombineSpec.gate` |
| 4 | `engine_refuses_a_gate_on_another_reducer_and_an_explicit_null` | unit | GR-E1 | H×M | `_check_gate` |
| 5 | `engine_refuses_bad_gate_fields_without_echo` (parametrized, GR-E2 list) | unit | GR-E2 | H×M | wrap validator, fixed messages |
| 6 | `gate_record_serializes_in_the_pinned_key_order` | unit | GR-2 | H×M | field order |
| 7 | `gate_record_and_evidence_invariants_refuse_mismatches` | unit | GR-E3 | H×M | `_check` |
| 8 | `evidence_with_every_optional_key_orders_signal_cut_declared_gate_result` | unit | GR-D1 | H×M | field placement |
| 9 | `sdk_decodes_and_round_trips_a_gate_record` | unit | GR-3 | H×M | `_gate`, `CombineGate.to_dict` |
| 10 | `sdk_decoder_refuses_bad_gate_records` | unit | GR-E4 | M×M | exact keys, words |
| 11 | `sdk_combine_gate_refuses_bad_values` | unit | GR-D5 | M×M | `__post_init__` |
| 12 | `sdk_answer_and_result_accept_gate_not_met` | unit | GR-5 | M×M | words |
| 13 | PIN `schema_snapshots_hold_the_gate_and_gate_not_met` (spec v1: `gate` property, not required; evidence v1: `gate`, `verifier` properties, not required, `GateRecord` def keys; answer.v1: the word in both lists) — regenerate the three snapshots (pinned edits) | unit | GR-D2 | H×M | regenerate with the existing update variable |
| 14 | `sdk_reason_words_equal_the_engine_enum` (13 words; `decode_combine_spec` accepts a gate dict, refuses a gate list) | unit | GR-D4, GR-D6 | H×M | — |

Pinned edits of this PRD (owner approval, plan §6): the three schema snapshots,
`ST/public_surface_snapshot.json` (`CombineGate`, `CombineEvidence.gate`), `ST/test_pick_output.py:250-264`,
`ST/test_evidence_words.py:372` and `:460-475`, `ET/test_combine_pick_output.py:341-352`,
`ET/test_combine_evidence_words.py:310-322`. Each edit adds `gate_not_met` (or the new count) and
changes nothing else.
