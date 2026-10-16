# PRD: Consistency record (spec entry, context key, evidence record)

**Source:** epic sources table ("`consistency@N`"), ans:Q3 (the source sets the temperature), ans:Q4
("the count of failed samples is recorded") · **Priority:** P0 (consistency-value, consistency-api
and consistency-display use it)
**Lifecycle:** existing (characterize + delta)
**Owner:** unassigned
Paths: [erd §1, §4, §6](../erd.md) · contracts: C1, C3, C4 · used by:
[consistency-value](consistency-value.md), [consistency-api](consistency-api.md),
[consistency-display](consistency-display.md)

## 1. Flows served

This is a component PRD. It owns the WORDS and the WIRE KEYS of consistency on both sides: the
spec entry `{"source": "consistency", ...}`, the context key `samples` (its presence and its map
shape), the evidence record `consistency`, and the SDK public type `sf.report.CombineSampleCount`.
No code computes a value yet; [consistency-value](consistency-value.md) does that. The part 5 unit 1
precedent ("words and schema") applies.

## 2. Background and constraints

- "Call that member N more times with different seeds. Extract and normalize each answer the same
  way as E4a. The number is the fraction of those N that match this answer." [stated epic]
- "value = matches / successful samples; the count of failed samples is recorded; if all fail, the
  value is missing." [stated ans:Q4]
- New optional keys keep the bytes of every existing spec and evidence when absent. [existing part 3
  P11, part 5 P9 precedent]
- Two existing tests refuse the bare entry `{"source": "consistency"}`
  (`ET/test_combine_declared_signals.py:135` and `:240`). They must stay green: `n`,
  `temperature` and `match` are REQUIRED in the Engine model. [existing]

### 2.1 Current behavior

- `DeclaredSource` is the tagged union `VerbalizedSource | LogprobSource | EntropySource`
  (E/combine/spec.py:167-169). A `"consistency"` word is refused with `combine_spec_invalid`.
- `_check_signals` (E/combine/spec.py:227-235) checks 1..8 names and the name rule.
- `parse_context` (E/combine/spec.py:363-395) accepts the keys `input`, `outputs`, `panel`,
  `signals`, `sources` (`_CONTEXT_KEYS`, :58). `CombineContext` (:340-351) has no samples.
- `CombineEvidence` (E/combine/evidence.py:177-242) writes `declared`, then `gate`, `verifier`,
  `result`. No sample record.
- SDK: `CombineEvidence` (S/combine_evidence.py:319-460) has no `consistency`;
  `_OPTIONAL_EVIDENCE_KEYS = {"mean", "cut", "declared", "gate", "verifier"}`
  (S/_evaluation/combine_evidence.py:69); `sf.report` exports `CombineGate` (S/report.py:43, :1109).

**Delta (Engine).**

```python
# E/combine/spec.py
class ConsistencyMatch(_SpecModel):
    """How a sample is compared with the member's answer (E4b part 7): the E4a stages."""
    extract: StepSpec
    normalize: StepSpec | None

class ConsistencySource(_SpecModel):
    """``{"source": "consistency", "n": 1..32, "temperature": >= 0, "match": {...}}``."""
    source: Literal["consistency"]
    n: int = Field(ge=1, le=32)
    temperature: float = Field(ge=0)
    match: ConsistencyMatch

DeclaredSource = Annotated[
    VerbalizedSource | LogprobSource | EntropySource | ConsistencySource,
    Field(discriminator="source"),
]

# _check_signals: one more rule, after the name rule
#   more than one ConsistencySource -> "signals declares at most one consistency source"

def declares_consistency(spec: CombineSpec) -> tuple[str, ConsistencySource] | None: ...
#   the name and the one ConsistencySource of spec.signals; None when there is none

@dataclass(frozen=True, slots=True)
class CombineContext:
    ...
    sources: MemberSources | None = None
    samples: Mapping[str, str] | None = None     # new: member -> the rows text of its sample panel

def parse_context(context, members, *, sources_expected=False, samples_expected=False): ...
#   _CONTEXT_KEYS gains "samples".
#   ("samples" in decoded) != samples_expected -> SpecInvalid(
#       "combine context samples are present exactly when the spec declares consistency")
#   samples present: _text_map(...) and set(keys) == set(members), else SpecInvalid(
#       "combine context samples do not match the spec members")
#   The rows text itself is parsed in consistency-value (it needs n).
```

```python
# E/combine/evidence.py
class SampleCountRecord(_EvidenceModel):
    """One member's samples of the declared consistency source (E4b part 7, ans:Q4)."""
    member_id: str
    matched: int | None = Field(ge=0)          # None allowed
    succeeded: int = Field(ge=0)
    failed: int = Field(ge=0)
    # _check: CS-I4 (matched None, or 0 <= matched <= succeeded and succeeded >= 1)

class CombineEvidence(_EvidenceModel):
    ...
    declared: ... = Field(default=None, exclude_if=lambda value: value is None)
    consistency: dict[str, list[SampleCountRecord]] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )                                           # new, between declared and gate
    gate: GateRecord | None = ...
    # _check adds _check_consistency(self): CS-I1, CS-I2, CS-I3, CS-I5 (erd §6)
```

`_check_consistency` messages (fixed text, never a value): `"a consistency record goes with one
declared consistency source"` (CS-I1), `"a consistency record names every member in order"`
(CS-I2), `"succeeded and failed samples add up to n"` (CS-I3), `"a consistency value is matched
over succeeded"` (CS-I5). `SampleCountRecord._check`: `"matched is at most succeeded, and a
match needs a successful sample"` (CS-I4).

**Delta (SDK).**

- `S/combine_evidence.py`: new frozen dataclass `CombineSampleCount(member_id: str, matched: int |
  None, succeeded: int, failed: int)`, `__post_init__` checks (text; non-negative ints; bool
  refused; CS-I4), `to_dict()` in record order. `CombineEvidence.__init__` gets the keyword
  `consistency: Mapping[str, Sequence[CombineSampleCount]] | None = None`; it stores
  `Mapping[str, tuple[CombineSampleCount, ...]]` (read-only), checks CS-I1, CS-I2, CS-I3, CS-I5
  with `ValueError`, and `to_dict` writes
  `**({} if self.consistency is None else {"consistency": {...}})` after `declared` and before
  `gate`.
- `S/report.py`: export `CombineSampleCount` (`sf.report.CombineSampleCount`, beside `CombineGate`).
- `S/_evaluation/combine_evidence.py`: `_OPTIONAL_EVIDENCE_KEYS` adds `"consistency"`;
  `_SAMPLE_COUNT_KEYS = {"member_id", "matched", "succeeded", "failed"}` exact; a
  `_consistency(raw, label)` decoder (a mapping of name to a list of exact-key mappings).

## 3. Scenarios and acceptance criteria

### 3.1 Happy path

- **CR-1** Given the spec text of `builtin_vote_spec(3)` (ET/combine_golden_support.py:145-153)
  plus `"signals": {"cons": {"source": "consistency", "n": 4, "temperature": 1.0, "match":
  {"extract": {"op": "last_number@1", "args": {}}, "normalize": {"op": "numeric@1", "args":
  {}}}}}`, then `parse_spec` returns a spec whose `signals["cons"]` is a `ConsistencySource` with
  `n == 4`, `temperature == 1.0`, `match.extract.op == "last_number@1"`, and
  `declares_consistency(spec) == ("cons", spec.signals["cons"])`. [stated ans:Q3]
- **CR-2** Given that spec's members and the context
  `{"input": "q", "outputs": {"member_1": "a", "member_2": "b", "member_3": "c"}, "samples":
  {"member_1": "[]", "member_2": "[]", "member_3": "[]"}}`, then
  `parse_context(text, members, samples_expected=True).samples == {"member_1": "[]",
  "member_2": "[]", "member_3": "[]"}`. Without `samples` and with `samples_expected=False`,
  `samples is None`. [proposed] P9
- **CR-3** Given a `CombineEvidence` with `declared={"cons": {<the CR-1 entry>}}`, members with
  `signals` `{"cons": 0.5}`, `{"cons": 1.0}`, `{"cons": None}`, and
  `consistency={"cons": [SampleCountRecord("member_1", 2, 4, 0), SampleCountRecord("member_2", 2,
  2, 2), SampleCountRecord("member_3", None, 0, 4)]}`, then `model_dump(mode="json",
  by_alias=True)` has the top-level keys in this order: `schema`, `kind`, `reducer`, `operators`,
  `members`, `tally`, `judge`, `fields`, `chosen`, `built`, `agreement`, `tie`, `median`,
  `presentation_order`, `separator_collision`, `signal`, `declared`, `consistency`, `result`,
  `dropped`, `finish_reason`; and each record has the keys `member_id`, `matched`, `succeeded`,
  `failed`, in that order. [proposed] P13
- **CR-4** Given that wire, then `decode_combine_evidence(wire, "x")` returns a `CombineEvidence`
  whose `consistency["cons"]` is three `CombineSampleCount` values equal to the records, and
  `to_dict() == wire`. [proposed]
- **CR-5** Given any of the 37 evidence cases of list L37 (test-plan §6), then its Engine bytes and
  its SDK round trip do not change, and no wire has `consistency`. [implied]

### 3.2 Error paths

- **CR-E1** Given the CR-1 spec with each of these `signals` values, then `parse_spec` raises
  `SpecInvalid` (`combine_spec_invalid`), and the message holds none of `zq`, `33`, `-0.5`:
  `{"zq": {"source": "consistency"}}`; the CR-1 entry with `n: 0`, `n: 33`, `n: 2.5`, `n: true`;
  with `temperature: -0.5`; without `temperature`; without `match`; with `match.extract: null`;
  with an extra key `"flags": 1`; with `match` holding an extra key; two consistency entries
  (`"cons"` and `"cons2"`). [proposed]
- **CR-E2** Given the CR-2 members, then `parse_context` raises `SpecInvalid` for: `samples`
  present with `samples_expected=False`; `samples` absent with `samples_expected=True`; `samples`
  that leave out `member_3`; `samples` with an extra `member_4`; a `samples` value that is not
  text (`{"member_1": []}`); `samples` that is a list. [proposed]
- **CR-E3** Given an Engine `SampleCountRecord` with `matched=3, succeeded=2`, or `matched=0,
  succeeded=0`, or `failed=-1`, then a `ValidationError`. Given a `CombineEvidence` with a
  `consistency` record and no consistency entry in `declared` (CS-I1); a record list that leaves out
  `member_2` or swaps `member_1` and `member_2` (CS-I2); `succeeded + failed == 5` with `n == 4`
  (CS-I3); `signals["cons"] == 0.4` with `matched=2, succeeded=4` (CS-I5); `signals["cons"] ==
  0.5` with `matched=None` (CS-I5), then a `ValidationError`. [proposed]
- **CR-E4** Given the CR-3 wire with an extra record key, a missing record key, `"matched": "2"`,
  `"succeeded": true`, a record list that is a mapping, or a broken CS rule, then
  `decode_combine_evidence` raises `ExecutionError`. [existing strict decoder]

### 3.3 Derived scenarios (risk-ordered)

- **CR-D1** (H×M) [proposed] Given an evidence with `signal`, `cut`, `declared`, `consistency` and
  `gate` all set, then the keys are in the order `signal`, `cut`, `declared`, `consistency`,
  `gate`, `result`.
- **CR-D2** (M×M) [proposed] A `CombineSampleCount` refuses `matched=True`, `succeeded=-1`,
  `failed=1.0`, `member_id=""`, and `matched=3, succeeded=2`, with `TypeError` or `ValueError`.
- **CR-D3** (H×M) [implied] The schema ids stay `screamingface.combine-spec.v1` and
  `screamingface.combine-evidence.v1`; `consistency` is not in `required`.
- **CR-D4** (M×L) [proposed] The SDK spec decoder `decode_combine_spec` accepts a spec whose
  `signals` holds a consistency entry (the `signals` key is already optional,
  S/_evaluation/combine_spec.py:24). Only the rebuild reads the entry
  ([consistency-rebuild](consistency-rebuild.md)).

## 4. Non-functional requirements

- The record adds about 70 bytes per member to one evidence (256 members: about 18 KB). [proposed]
- No new dependency. The Engine evidence module still imports only pydantic and `combine.ports`
  (E/combine/evidence.py:11-13 INVARIANT). [existing]

## 5. Out of scope

- The computation of the counts and the value (consistency-value), the SDK `sf.Consistency`
  (consistency-api), the display (consistency-display).
- The rows text parse of one sample panel (consistency-value: it needs `n`).

## 6. Open questions

None.

## 7. TDD plan

Order: characterize the existing bytes, then the Engine words, then the Engine models, then the SDK
mirror. New test files: `ET/test_combine_consistency_words.py`, `ST/test_consistency_words.py`.

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| 1 | CHAR `existing_evidence_and_specs_have_no_consistency` (the 37 cases of list L37 on both sides have no `consistency` key; each combine spec in the 47 url4 files of list L47 parses with no consistency entry, and each combine context in them has no `samples` key). Fixed lists, never a glob (test-plan §6) | unit | CR-5 | H×M | passes today |
| 2 | CHAR `a_bare_consistency_entry_is_still_refused` (the existing refusals of `ET/test_combine_declared_signals.py:135`, `:240`, written again as a separate test so that unit 1 cannot make them pass by a default) | unit | §2 | H×M | passes today; stays green because n, temperature and match have no default |
| 3 | `engine_parses_a_consistency_entry` | unit | CR-1 | H×M | `ConsistencySource`, union, `declares_consistency` |
| 4 | `engine_refuses_bad_consistency_entries_without_echo` (parametrized, CR-E1 list) | unit | CR-E1 | H×M | model fields, `_check_signals` |
| 5 | `engine_context_reads_samples_exactly_when_expected` | unit | CR-2 | H×M | `parse_context`, `CombineContext.samples` |
| 6 | `engine_context_refuses_bad_samples_maps` (parametrized, CR-E2 list) | unit | CR-E2 | H×M | `parse_context` |
| 7 | `consistency_record_serializes_in_the_pinned_key_order` | unit | CR-3 | H×M | field order |
| 8 | `sample_count_and_evidence_invariants_refuse_mismatches` (CS-I1..CS-I5) | unit | CR-E3 | H×M | `_check`, `_check_consistency` |
| 9 | `evidence_with_every_optional_key_orders_declared_consistency_gate` | unit | CR-D1 | H×M | field placement |
| 10 | `sdk_decodes_and_round_trips_a_consistency_record` | unit | CR-4 | H×M | `_consistency`, `CombineSampleCount.to_dict` |
| 11 | `sdk_decoder_refuses_bad_consistency_records` | unit | CR-E4 | M×M | exact keys, `CombineEvidence` checks |
| 12 | `sdk_sample_count_refuses_bad_values` | unit | CR-D2 | M×M | `__post_init__` |
| 13 | PIN `schema_snapshots_hold_the_consistency_entry_and_record` (spec v1: the `ConsistencySource` and `ConsistencyMatch` defs are in the `signals` union; evidence v1: the `consistency` property, not required, and the `SampleCountRecord` def keys). Regenerate the two pinned snapshots | unit | CR-D3 | H×M | delete the pinned file, run the freeze test once with `UPDATE_SCHEMA_SNAPSHOT=1` (it writes the file and fails), then run it again without the variable (test-plan §2) |
| 14 | `sdk_report_exports_combine_sample_count` (`sf.report.CombineSampleCount is CombineSampleCount`; `CombineEvidence` has the keyword `consistency`). PIN: regenerate `ST/public_surface_snapshot.json` | unit | §2 delta | M×M | `S/report.py`; `UPDATE_SURFACE_SNAPSHOT=1` (test-plan §2) |
| 15 | `sdk_spec_decoder_accepts_a_consistency_entry` | unit | CR-D4 | M×L | none expected (passes at GREEN of row 3; if it is green at RED, record it as a CHAR row in the ledger) |

Pinned edits of this PRD (owner approval, plan §6): the spec v1 and evidence v1 schema snapshots,
and `ST/public_surface_snapshot.json` (`CombineSampleCount`, `CombineEvidence.consistency`, the
`CombineEvidence.__init__` keyword).
