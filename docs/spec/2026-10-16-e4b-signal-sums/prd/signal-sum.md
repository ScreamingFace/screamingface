# PRD: Signal sum in the Engine (spec entry, member value, evidence)

**Source:** ans:Q1 ("each member gets risk = sum of coefficient x component ... recorded like any
declared signal") · **Priority:** P0 (sum-api, sum-band-display and docs use it)
**Lifecycle:** existing (characterize + delta)
**Owner:** unassigned
Paths: [erd §1, §2](../erd.md) · contracts: C1, C2 · used by: [sum-api](sum-api.md),
[sum-band-display](sum-band-display.md)

## 1. Summary and user story

As a benchmark author, I declare `signals={"risk": sf.Sum({"sev_a": 0.5, "sev_b": 0.3}), ...}`, so
that each member carries one number `risk = 0.5 × sev_a + 0.3 × sev_b`, and any rule or gate reads
it by name, the same way it reads a declared `sf.Verbalized` or `sf.Logprob` name.

This PRD owns the Engine side: the spec entry `{"source": "sum", "coefficients": {...}}`, its
checks, the value per member, the evidence, and one contract case. The SDK constructor and the url4
round trip are [sum-api](sum-api.md).

## 2. Background and constraints

- "Each member gets a value for each declared name, or an explicit missing. Missing is not zero."
  [stated epic OME-1290 "Where a number is allowed to come from"]
- "The weight formula is fixed and documented, not an arbitrary function upload (that would be
  E4e)." [stated epic]
- A rule reads ONE signal (`_signal_read`, E/combine/endpoint.py:732-750: "a combine step reads at
  most one signal"). This part does not change that rule: the sum is one name (decision (c), P6).
- The core stays pure: no I/O, no clock; it imports no plugin (E/combine/endpoint.py:11-14,
  `check_layering.py` `COMBINE_CORE_FORBIDDEN`). [existing]
- Part 7 (`consistency@N`) is built in parallel and also adds a member to the `signals` union and
  touches `_declared`. This part keeps its edits additive: one new union member, one new branch in
  `_declared`, one new pure module. [stated brief]

### 2.1 Current behavior

- `DeclaredSource` is the tagged union `VerbalizedSource | LogprobSource | EntropySource`
  (E/combine/spec.py:166-169). `CombineSpec.signals: dict[str, DeclaredSource] | None`
  (:196). A nested error is quieted to `"signals must map declared names to known sources"`
  (:199-206).
- `_check_signals` (:227-235): 1 to `MAX_DECLARED_SIGNALS` (8) names, each a declared name.
- `_declared` (E/combine/endpoint.py:710-729): a logprob or entropy entry becomes a
  `_ReplyDeclared`; any other entry is resolved through `registry.source(source.source)` and
  becomes a `_Declared`.
- `_signal_values` (:292-309) computes one column per recorded key with `_column` (:339-351), in
  any order: no column reads another column.
- `_recorded_keys` (:354-356): the read key first, then every declared name in spec order.
- `_declared_record` (:985-991) writes each spec entry with `model_dump(mode="json",
  exclude_unset=True)`.
- `finite_float` (E/combine/ports.py:519-526) gives None for a value that a float cannot hold.

**Delta (Engine).**

```python
# E/combine/spec.py
class SumSource(_SpecModel):
    """``{"source": "sum", "coefficients": {name: number}}`` (E4b part 6, ans:Q1).

    The value is sum(coefficient x value) over the components, per member; the core computes it
    (E/combine/signal_sum.py), so it has no source plugin.
    """

    source: Literal["sum"]
    coefficients: dict[str, float] = Field(min_length=1, max_length=MAX_DECLARED_SIGNALS - 1)

DeclaredSource = Annotated[
    VerbalizedSource | LogprobSource | EntropySource | SumSource, Field(discriminator="source")
]

# _check_signals: after the count and name checks, for each SumSource entry, call _check_sum.
def _check_sum(entry: SumSource, signals: Mapping[str, DeclaredSource]) -> None: ...
```

`_check_sum` failures (each a `ValueError` with a fixed text; pydantic turns it into
`combine_spec_invalid`; no message holds a name or a number):

| Rule | Message |
|---|---|
| a component is not a key of `signals` | `"a sum adds only names the spec declares"` |
| a component is a `SumSource` | `"a sum does not add another sum"` |
| a coefficient is `0` or `-0.0` | `"a sum coefficient is not zero"` |

An empty map, more than 7 entries, a bool, a string or a null coefficient, or an extra key fail
inside the union and give the existing quiet message `"signals must map declared names to known
sources"`. NaN and Infinity cannot reach the model: `loads_bounded` refuses them
(E/combine/spec.py:9-10).

```python
# E/combine/signal_sum.py (new, pure, standard library only)
def sum_value(terms: Sequence[tuple[str, float]], values: Mapping[str, float | None]) -> float | None:
    """The exact sum of coefficient x value over ``terms``, rounded once to a float (SU-I4).

    None when a component value is None (SU-I3), or when the exact sum is outside the float range.
    """
    # float(sum(Fraction(c) * Fraction(values[name]) for name, c in terms)); OverflowError -> None
```

```python
# E/combine/endpoint.py
@dataclass(frozen=True, slots=True)
class _Summed:
    """One declared sum: its name and its (component, coefficient) terms in spec order."""
    name: str
    terms: tuple[tuple[str, float], ...]

# _Plan.declared: tuple[_Declared | _ReplyDeclared | _Summed, ...]
# _declared: a SumSource entry -> _Summed(name, tuple(entry.coefficients.items())), BEFORE the
#   registry lookup (a sum has no source plugin).
```

`_signal_values` after the change (the exact shape; the early returns stay as they are):

```python
    keys = _recorded_keys(plan)
    ...  # the two early returns of today, unchanged
    sums = {item.name: item for item in plan.declared if isinstance(item, _Summed)}
    by_name = {
        item.name: item for item in plan.declared if not isinstance(item, _Summed)
    }  # the same Mapping[str, _Declared | _ReplyDeclared] as today
    plain = tuple(key for key in keys if key not in sums)
    looked = _reader_numbers(plain, by_name, context, accounting)
    columns: dict[str, Mapping[str, float | None]] = {
        key: _column(key, by_name.get(key), spec, context, looked) for key in plain
    }
    for name, item in sums.items():
        columns[name] = {
            member: sum_value(item.terms, {c: columns[c][member] for c, _ in item.terms})
            for member in spec.members
        }
    return {member: {key: columns[key][member] for key in keys} for member in spec.members}
```

Rules for this shape:

- `_reader_numbers` and `_column` get only `plain` keys and the non-sum `by_name`, so their types
  (`_Declared | _ReplyDeclared`) do not change. WHY: a sum key that reaches `_column` falls through
  to `_signal_numbers`, which calls `_field_numbers(key[6:])` and gives quiet, wrong values with no
  error.
- Every component of a sum is a declared non-sum name (SM-E1), and `_recorded_keys` holds every
  declared name, so `columns[c]` exists for each component.
- The returned map keeps the key order of `keys` (SM-2 checks it).

`_reader_numbers`, `_column`, `_signal_read`, `_exclusion`, `_weight`, `_read_members` and
`_recorded_keys` do not change. A sum of logprob names gets its reader call through the logprob
names (`declares_reply_sources` already sees them).

Exports: add `"SumSource"` to `E/combine/spec.py` `__all__` (:495-515, after `"StepSpec"`, before
`"VerbalizedSource"`), and `__all__ = ["sum_value"]` to the new `E/combine/signal_sum.py`.

## 3. Scenarios and acceptance criteria

Fixture S (three member texts, used by every row below that names it):

| Member | Text | `sev_a` | `sev_b` | `risk` = 0.5 × sev_a + 0.3 × sev_b |
|---|---|---|---|---|
| member_1 | `"A: 4\nB: 10\nThe answer is 9"` | 4.0 | 10.0 | 5.0 |
| member_2 | `"A: 2\nB: 5\nSo 9"` | 2.0 | 5.0 | 2.5 |
| member_3 | `"A: 6\nI get 12"` | 6.0 | None | None |

Signals S: `{"risk": {"source": "sum", "coefficients": {"sev_a": 0.5, "sev_b": 0.3}},
"sev_a": {"source": "verbalized", "pattern": "A: ([0-9]+)"}, "sev_b": {"source": "verbalized",
"pattern": "B: ([0-9]+)"}}`.

The exact sums are hand-computed with `fractions.Fraction`: `0.5×4 + 0.3×10` is
`4.99999999999999988898...`, which rounds to `5.0`; `0.5×2 + 0.3×5` is `2.49999999999999994449...`,
which rounds to `2.5`.

### 3.1 Happy path

- **SM-1** Given a spec with signals S, then `parse_spec` returns `signals["risk"] ==
  SumSource(source="sum", coefficients={"sev_a": 0.5, "sev_b": 0.3})`. [stated ans:Q1]
- **SM-2** Given `argmax_spec(3, "risk", "min")` (ET/combine_signal_support.py:18) with signals S
  and fixture S, then `run` gives: `members[i].signals` = `{"risk": 5.0, "sev_a": 4.0, "sev_b":
  10.0}`, `{"risk": 2.5, "sev_a": 2.0, "sev_b": 5.0}`, `{"risk": None, "sev_a": 6.0, "sev_b":
  None}` in this key order; member_3 has `status "excluded"`, `reason "no_signal"`; `chosen ==
  ["member_2"]`; `signal == {"key": "risk", "order": "min"}`; `result.member_id == "member_2"`; the
  output is the member_2 text byte for byte. [stated ans:Q1 "Pick/Rank/Filter"]
- **SM-2b** Given fixture S and signals S, then a Rank and a Filter read the sum by name (helpers
  in `ET/combine_signal_support.py`, with `"signals"` set to signals S as
  `ET/test_combine_declared_exclusion.py:65-71` does):
  - `rank_signal_spec(3, 1, "risk", "min")` gives `chosen == ["member_2"]`, and member_3 has
    `status "excluded"`, `reason "no_signal"`;
  - `filter_spec(3, {"key": "risk", "cmp": "le", "value": 3.0})` keeps member_2 only:
    `chosen == ["member_2"]`, and member_3 has `status "excluded"`, `reason "no_signal"`.
  [stated ans:Q1 "Pick/Rank/Filter"]
- **SM-3** Given a weighted vote (`extract last_number@1`, `normalize numeric@1`, `reduce
  weighted_mode@1`, `select max_weight_holder@1`, `weights {"signal": "risk"}`) with signals S and
  the texts `"A: 4\nB: 10\nThe answer is 9"`, `"A: 2\nB: 5\nI get 12"`, `"A: 0\nB: 0\nSo 12"`,
  then member_3 (`risk` 0.0, not a usable weight) is `excluded` / `no_weight`; the tally is
  `[{"value": "9", "score": 5.0, "holders": ["member_1"]}, {"value": "12", "score": 2.5,
  "holders": ["member_2"]}]`; `chosen == ["member_1"]`; `agreement == 0.6666666666666666`.
  [stated ans:Q1 "weights"]; [existing E/combine/endpoint.py:800-806 weight rule]
- **SM-4** Given a vote (`builtin_vote_spec(3)`) with signals S, fixture S, and the gate
  `{"observe": "chosen:risk", "cmp": "<=", "threshold": 3.0, "otherwise": "abstain"}`, then the
  majority is 9, the chosen member is member_1, `gate.observed == 5.0`, `gate.passed is False`,
  and the result abstains with `gate_not_met`. With the gate `{"observe": "mean:risk", "cmp": "<=",
  "threshold": 4.0, "otherwise": "abstain"}`, `gate.observed == 3.75` (member_3 has no value),
  `passed is True`, and the answer is the member_1 text. [stated ans:Q1 "Gate chosen:/mean:"]
- **SM-5** Given the evidence of SM-2, then `declared == {"risk": {"source": "sum",
  "coefficients": {"sev_a": 0.5, "sev_b": 0.3}}, "sev_a": {"source": "verbalized", "pattern":
  "A: ([0-9]+)"}, "sev_b": {"source": "verbalized", "pattern": "B: ([0-9]+)"}}`. [stated ans:Q1
  "recorded like any declared signal"]

### 3.2 Error paths

- **SM-E1** Given a vote spec whose `signals` has each of these sums, then `parse_spec` raises
  `SpecInvalid`, and the message holds none of `zzz`, `sev_a`, `0.5`, `risk`:
  `{"zzz": 0.5}` (not declared); `{"risk2": 1.0}` where `risk2` is another sum (sum of a sum);
  `{"sev_a": 0.0}`; `{"sev_a": -0.0}`; `{}`; eight coefficients; `{"sev_a": true}`;
  `{"sev_a": "0.5"}`; `{"sev_a": null}`; an extra key `"note": 1` beside `coefficients`; a missing
  `coefficients`. A sum that names itself is refused by the "not a sum" rule. [proposed] P3, P4
- **SM-E2** Given a spec whose `weights` read `risk` and whose reduce args read `sev_a`, then
  `run` raises `SpecInvalid` with `"a combine step reads at most one signal"`. [existing
  E/combine/endpoint.py:748-749]; [proposed] P6

### 3.3 Derived scenarios (risk-ordered)

- **SM-D1** (H×H) [proposed] P5 `sum_value` is the exact rational sum rounded once: terms
  `(("a", 0.1), ("b", 0.1))`, values `{"a": 3.0, "b": 0.1}` give `0.31` (the float sum of the
  rounded products, `math.fsum([0.1 * 3.0, 0.1 * 0.1])`, is `0.31000000000000005`). Terms
  `(("a", 2.0), ("b", -0.5))`, values `{"a": 3.0, "b": 8.0}` give `2.0`. Terms `(("a", 0.5),)`,
  values `{"a": 7.0}` give `3.5`. The reversed term order gives the same float.
- **SM-D2** (H×M) [proposed] P5 A missing component gives None: values `{"a": 3.0, "b": None}`.
  A sum outside the float range gives None: terms `(("a", 1e308), ("b", 1e308))`, values
  `{"a": 10.0, "b": 10.0}`. An exact cancellation stays exact: terms `(("a", 1e308),
  ("b", -1e308))`, values `{"a": 10.0, "b": 10.0}` give `0.0`.
- **SM-D3** (H×M) [implied] A member that a quorum panel left out has None for every component,
  so None for the sum, and no reader call is made for it (OME-1557 rule, E/combine/endpoint.py:302-305).
- **SM-D4** (H×M) [proposed] A sum of a logprob name: signals `{"blend": {"source": "sum",
  "coefficients": {"conf": 0.01, "lp": 1.0}}, "conf": {"source": "verbalized", "pattern":
  "Confidence: ([0-9]+)"}, "lp": {"source": "logprob", "form": "prob"}}`, a pick spec
  `argmax_spec(2, "blend", "max")`, texts `"Confidence: 80\nA"` and `"Confidence: 90\nB"`, and a
  reader stub that returns `{REPLY_TOKENS: 2, REPLY_LOGPROB_SUM: -1.3862943611198906}` for
  member_1 and no row for member_2. Then member_1 has `lp == 0.5`, `conf == 80.0`,
  `blend == 1.3`; member_2 has `lp is None`, `blend is None` and is `excluded` / `no_signal`; the
  reader is called once. Exemplar for the stub: `ET/test_combine_declared_exclusion.py`.
- **SM-D5** (M×M) [implied] A spec without a sum entry gives the same evidence bytes as on base:
  the 37 cases of list L37 (test-plan §6) and the specs of the 47 url4 files of list L47 parse with
  no `SumSource`.
- **SM-D6** (M×L) [proposed] The log line keeps its format: for SM-2, the one combine log line
  ends with `outcome=ok` (exemplar for the log capture: `ET/test_combine_gate.py:523-537`).

## 4. Non-functional requirements

- At most 7 components × 256 members exact rational sums per call: microseconds. [proposed]
- `E/combine/signal_sum.py` imports only `fractions` and `collections.abc`. The layering gate
  enforces the core rule. [existing C9 of part 5]

## 5. Out of scope

- An E4a key (`cost_usd`, `score:judge`, `field:<path>`) as a component (D1).
- A sum across members (D2).
- A non-linear formula (E4e).

## 6. Open questions

None.

## 7. TDD plan

New test files: `ET/test_combine_signal_sum.py` (all rows except 12, 13),
`ET/test_combine_signal_sum_words.py` (rows 1, 13). Row 12 inserts one scenario builder
`_pick_sum_min` and the line `SCENARIOS["pick_sum_min"] = _pick_sum_min` into
`ET/test_combine_evidence_contract_fixture.py` directly after line 418 (the part 5 gate block, the
line `SCENARIOS["vote_gate_not_run"] = ...`) and before `def canonical_evidence` (line 421). Do
NOT append it at the end of the file: the file ends with `if __name__ == "__main__":
write_fixture()` (lines 491-492), so a line after it is not run when the file runs as a script
(test-plan §2), and `@pytest.mark.parametrize("name", sorted(SCENARIOS))` (line 442) reads
`SCENARIOS` when the decorator runs, so a later scenario gets no byte test. Part 5 inserted its
block in the same way (lines 378-418). Row 12 also appends one `_EXPECTED_NAMES |=` line to
`ST/test_combine_evidence_contract.py` after line 61. The append-only check does not flag these
two files: a new module-level statement between protected ranges is not inside a range.

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| 1 | CHAR `existing_specs_and_evidence_have_no_sum_source` (each spec in list L47 parses, and no `signals` entry has `entry.source == "sum"`; no `declared` entry of list L37 has `"source": "sum"`). It reads the `source` word, not the new class, so it passes on base. A fixed list, never a glob (test-plan §6) | unit | SM-D5 | M×M | passes today |
| 2 | `engine_parses_a_sum_source` | unit | SM-1 | H×M | `SumSource`, union |
| 3 | `engine_refuses_bad_sums_without_echo` (parametrized, the SM-E1 list) | unit | SM-E1 | H×M | `_check_sum`, quiet union |
| 4 | `sum_value_is_the_exact_sum_rounded_once` (SM-D1 oracles, both term orders) | unit | SM-D1 | H×H | `signal_sum.sum_value` |
| 5 | `sum_value_is_missing_when_a_component_is_missing_or_out_of_range` (SM-D2) | unit | SM-D2 | H×M | `sum_value` |
| 6 | `every_member_records_the_sum_after_its_components` (SM-2 signal maps, in key order) | unit | SM-2 | H×H | `_Summed`, two-pass `_signal_values` |
| 7 | `a_pick_reads_the_sum_by_name_and_excludes_a_member_with_no_sum` (SM-2 rest) and `a_rank_and_a_filter_read_the_sum_by_name` (SM-2b) | unit | SM-2, SM-2b | H×M | — |
| 8 | `a_vote_weight_reads_the_sum_and_a_zero_sum_has_no_weight` | unit | SM-3 | H×M | — |
| 9 | `a_gate_reads_a_sum_as_chosen_and_as_mean` | unit | SM-4 | H×M | — |
| 10 | `the_evidence_declares_the_sum_entry` | unit | SM-5 | M×M | — |
| 11 | `a_sum_of_a_logprob_name_uses_the_one_reader_call` | unit | SM-D4, SM-D3 | H×M | — |
| 12 | PIN `contract_case_pick_sum_min_is_byte_equal_on_both_sides`: new scenario `pick_sum_min` (SM-2 spec and texts) in the Engine contract fixture; the SDK decodes and round-trips it. Regenerate `evidence_cases.json` (37 → 38 cases; the 37 keep their bytes) and edit `ST/test_frozen_record_fields.py:184` (37 → 38) | unit | SM-2, SM-5 | H×M | run the fixture file as a script (`write_fixture`) |
| 13 | PIN `spec_schema_snapshot_holds_the_sum_source` (`$defs.SumSource`: `required == ["source", "coefficients"]`, `additionalProperties` false; the `signals` union names it). Regenerate the spec v1 snapshot | unit | erd §7 | H×M | delete the pinned file, run the freeze test once with `UPDATE_SCHEMA_SNAPSHOT=1`, then plainly (test-plan §2) |
| 14 | `the_one_signal_rule_is_unchanged_for_a_sum` (SM-E2) and the log line (SM-D6) | unit | SM-E2, SM-D6 | M×M | — |

Pinned edits of this PRD (owner approval, plan §6): the spec v1 schema snapshot,
`ET/data/combine_contract/evidence_cases.json`, `ST/test_frozen_record_fields.py:184`.
