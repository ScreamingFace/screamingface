# PRD: `sf.Sum` in the SDK (constructor, Fusion rules, compile, rebuild)

**Source:** ans:Q1 (`signals={"risk": sf.Sum({"sev_a": 0.5, "sev_b": 0.3})}`) · **Priority:** P0
**Lifecycle:** planned (new public type) on existing code (`sf.Fusion`, `Url4.to_python`)
**Owner:** unassigned
Paths: [erd §1](../erd.md) · contracts: C1, C3, C6 · uses: [signal-sum](signal-sum.md)

## 1. Summary and user story

As a benchmark author, I write `sf.Sum({"sev_a": 0.5, "sev_b": 0.3})` in a Fusion `signals=` map
and read it with `sf.signal("risk")` in `sf.Pick`, `sf.Rank`, `sf.Filter`, a vote weight, or a
gate `chosen:risk` / `mean:risk`. A mistake (an undeclared component, a sum of a sum, a sum that
cannot be a weight) fails at construction, before any member call. The url4 of the recipe rebuilds
the same Python.

## 2. Background and constraints

- "An undeclared name fails before any call." [stated epic, DB-1]
- Part 3 Q11 (owner): `sf.Logprob("mean")`, `sf.Logprob("sum")` and `sf.Entropy` cannot be a vote
  weight; the refusal lives in the `sf.Fusion` constructor (part 3 P14). [stated part 3 ans:Q11]
- A sum is a declared name: it counts toward the 8 names of a Fusion (S/fusion.py:131-134). [existing]

### 2.1 Current behavior

- `SignalSource` (S/signal_sources.py:21-38) has `_spec()`, `_from_spec()` and `_python()`.
  `Verbalized`, `Logprob`, `Entropy` are frozen dataclasses with `init=False` (:40-162).
  `_SOURCES` maps the wire word to the class (:188-190); `declared_from_spec` rebuilds a
  declaration (:193-209); `python_signals` writes the `signals=` text of `Url4.to_python`
  (:212-216).
- `sf.Fusion._declaration` (S/fusion.py:124-142) checks each name and source, refuses a second
  `sf.Entropy`, and returns the map sorted by name.
- `_check_logprob_sources` (:201-219) runs `_check_weight_source` (:222-237) only when the
  declaration has a `Logprob` or an `Entropy`.
- `_check_reads` (:167-183) and `_check_gate_name` (:186-198) accept any declared name.
- `combine_spec_text` writes `{name: source._spec()}` (S/_evaluation/combine_spec.py:77-78).
- `injected_member_params` (S/signal_sources.py:169-183) reads only `Logprob` and `Entropy`.

**Delta (SDK).**

```python
# S/signal_sources.py
_MAX_SUM_TERMS = 7  # MAX_DECLARED_SIGNALS - 1: a sum and its components share the 8 names

@dataclass(frozen=True, slots=True, init=False)
class Sum(SignalSource):
    """A fixed linear sum of other declared signals of the same member (E4b part 6, ans:Q1).

    ``sf.Sum({"sev_a": 0.5, "sev_b": 0.3})`` gives each member 0.5 x sev_a + 0.3 x sev_b. Each key
    is another name of the same Fusion ``signals=``, never another sf.Sum. The value is missing
    when a component is missing. The Engine adds the exact products and rounds once.
    """

    source: ClassVar[str] = "sum"
    coefficients: Mapping[str, float]  # MappingProxyType, sorted by name, float values

    def __init__(self, coefficients: Mapping[str, float]) -> None: ...
    def __repr__(self) -> str:  # "Sum({'sev_a': 0.5, 'sev_b': 0.3})"
    def _spec(self) -> dict[str, object]:  # {"source": "sum", "coefficients": {...}}
    @classmethod
    def _from_spec(cls, entry: Mapping[str, object]) -> Sum: ...
    __hash__: ClassVar[Any] = None  # WHY: it holds a mapping (the sf.Gate precedent)

_SOURCES = {"verbalized": Verbalized, "logprob": Logprob, "entropy": Entropy, "sum": Sum}
__all__ = [..., "Sum", ...]
```

Constructor rules, checked in this order (the messages are exact):

| Input | Error |
|---|---|
| not a `Mapping` | `TypeError("sf.Sum takes a mapping of declared names to numbers, such as {'sev_a': 0.5}")` |
| 0 or more than 7 entries | `ValueError(f"sf.Sum adds 1 to 7 declared names, not {count}")` |
| a key that is not `str` | `TypeError("sf.Sum names must be text")` |
| a key for which `is_signal_name` is false | `ValueError(f"sf.Sum adds {name!r}, which is not a declared signal name; an E4a key such as cost_usd cannot be a sum component")` |
| a bool, or a value that is not `int` or `float` | `TypeError(f"sf.Sum coefficient of {name!r} must be a number")` |
| an int too large for a float, NaN or an infinity | `ValueError(f"sf.Sum coefficient of {name!r} must be finite")` |
| `0`, `0.0` or `-0.0` | `ValueError(f"sf.Sum coefficient of {name!r} must not be zero")` |

`_from_spec` accepts exactly the keys `{"source", "coefficients"}`, `source == "sum"`, and a
`Mapping` of `str` to `int`/`float` (not bool); then it calls the constructor. Any other entry, or a
constructor error, raises `ValueError(_CANNOT_REBUILD)`.

```python
# S/fusion.py
# _declaration: after the entropy rule, call _check_sums(value) (the map before sorting).
def _check_sums(declared: Mapping[str, SignalSource]) -> None: ...
# _check_weight_source: when declared[weights.key] is a Sum, refuse it when any component is a
#   Logprob whose form is not "prob", or an Entropy.
# S/__init__.py: export Sum ("Sum" in __all__, after "Signal...", in the sorted list).
```

`_check_sums` walks the sums in name order and their components in name order. Messages (exact):

| Rule | Error |
|---|---|
| a component is not a key of `signals=` | `ValueError(f"sf.Sum {name!r} adds {component!r}, which this Fusion does not declare (declared: {listed})")`, `listed` = the declared names joined by `", "` |
| a component is an `sf.Sum` (also the sum itself) | `ValueError(f"sf.Sum {name!r} adds {component!r}, which is an sf.Sum; a sum adds only other sources, not sums")` |
| a vote weight reads a sum with a raw logprob or entropy component | `ValueError(f"sf.Sum {key!r} cannot be a vote weight: it adds {component!r} ({source!r}), and a weight must be greater than 0; read sf.signal({key!r}) with sf.Pick, sf.Rank or sf.Filter instead")` |

## 3. Scenarios and acceptance criteria

The recipe R (used by the rows below):

```python
sf.Fusion(
    ["prov/alpha", "prov/beta", "prov/gamma"],
    name="pick",
    signals={
        "risk": sf.Sum({"sev_a": 0.5, "sev_b": 0.3}),
        "sev_a": sf.Verbalized("A: ([0-9]+)"),
        "sev_b": sf.Verbalized("B: ([0-9]+)"),
    },
    synthesizer=sf.Pick(by_signal=sf.signal("risk"), order="min"),
)
```

### 3.1 Happy path

- **SA-1** Given `sf.Sum({"sev_b": 0.3, "sev_a": 1})`, then `coefficients == {"sev_a": 1.0,
  "sev_b": 0.3}` with the keys in this order, each value is a `float`, and `repr` is
  `"Sum({'sev_a': 1.0, 'sev_b': 0.3})"`. `sf.Sum` is a `SignalSource` and is in `sf.__all__`.
  [stated ans:Q1]; [proposed] P2
- **SA-2** Given recipe R, then it constructs, and `decode_combine_spec(<its combine intent>)
  ["signals"]` equals `{"risk": {"coefficients": {"sev_a": 0.5, "sev_b": 0.3}, "source": "sum"},
  "sev_a": {"pattern": "A: ([0-9]+)", "source": "verbalized"}, "sev_b": {"pattern": "B: ([0-9]+)",
  "source": "verbalized"}}`, and the intent text holds
  `"risk":{"coefficients":{"sev_a":0.5,"sev_b":0.3},"source":"sum"}` (canonical JSON, sorted keys).
  [stated ans:Q1]
- **SA-3** Given the declaration of R, then each of these synthesizers constructs: `sf.Rank(1,
  by_signal=sf.signal("risk"), order="min")`, `sf.Filter(where=sf.signal("risk") <= 3.0)`,
  `sf.Vote(weights=sf.signal("risk"))`, `sf.Vote(gate=sf.Gate("chosen:risk", "<=", 3.0))`,
  `sf.Vote(gate=sf.Gate("mean:risk", "<=", 3.0))`. [stated ans:Q1 "any rule or gate reads it by
  name"]
- **SA-4** Given the url4 of recipe R, then `Url4(url4).to_python()` holds the line
  `signals={'risk': sf.Sum({'sev_a': 0.5, 'sev_b': 0.3}), 'sev_a': sf.Verbalized('A: ([0-9]+)'),
  'sev_b': sf.Verbalized('B: ([0-9]+)')},`, and the Python it returns compiles to the same url4.
  [proposed] P15
- **SA-5** Given the url4 fixture `sum_pick_candidate.url4` (the compile of recipe R) and the
  fixture S texts of [signal-sum](signal-sum.md) §3 as the three member replies, then the Engine
  world runs it offline: exactly three model calls (the members), the Case output is
  `"A: 2\nB: 5\nSo 9"`, the evidence `members[].signals` are the SM-2 maps, member_3 is
  `excluded` / `no_signal`. [stated ans:Q1]

### 3.2 Error paths

- **SA-E1** Given each constructor input of the table in §2, then the listed error. Inputs:
  `[("a", 1.0)]`; `{}`; eight valid names; `{1: 0.5}`; `{"cost_usd": 0.5}`; `{"Sev": 0.5}`;
  `{"logprob_x": 0.5}`; `{"a": True}`; `{"a": "0.5"}`; `{"a": 10**400}`; `{"a": float("inf")}`;
  `{"a": float("nan")}`; `{"a": 0}`; `{"a": -0.0}`. [proposed] P2, P4
- **SA-E2** Given `signals={"risk": sf.Sum({"sev_a": 0.5, "zzz": 1.0}), "sev_a":
  sf.Verbalized("A: ([0-9]+)")}`, then `sf.Fusion(...)` raises `ValueError("sf.Sum 'risk' adds
  'zzz', which this Fusion does not declare (declared: risk, sev_a)")`. [proposed] P3
- **SA-E3** Given `signals={"a": sf.Verbalized("A: ([0-9]+)"), "r1": sf.Sum({"a": 1.0}), "r2":
  sf.Sum({"r1": 1.0})}`, then `ValueError("sf.Sum 'r2' adds 'r1', which is an sf.Sum; a sum adds
  only other sources, not sums")`. A sum that names itself (`{"r": sf.Sum({"r": 1.0})}`) gives
  the same message with `'r'` twice. [proposed] P3
- **SA-E4** Given a weighted vote `sf.Vote(weights=sf.signal("w"))` over the three members
  `["openrouter/acme/alpha", "openrouter/acme/beta", "openrouter/acme/gamma"]` with `"w": sf.Sum({"lp": 1.0, "conf": 0.01})` and `"lp"` = `sf.Logprob("mean")`, then
  `ValueError("sf.Sum 'w' cannot be a vote weight: it adds 'lp' (Logprob('mean')), and a weight
  must be greater than 0; read sf.signal('w') with sf.Pick, sf.Rank or sf.Filter instead")`. The
  same with `sf.Logprob("sum")` and with `sf.Entropy()` (`(Entropy(top_logprobs=5))`). With
  `sf.Logprob("prob")` the Fusion constructs. A `sf.Pick` that reads the same `w` constructs.
  [stated part 3 ans:Q11]; [proposed] P13

### 3.3 Derived scenarios (risk-ordered)

- **SA-D1** (H×M) [implied] A Fusion without an `sf.Sum` compiles to the same url4 bytes: the
  builders `verbalized_vote_url4` (ST/test_verbalized_contract_fixture.py:26) and
  `gate_verbalized_vote_url4` (ST/test_gate_contract_fixtures.py:39) still equal their files.
- **SA-D2** (H×M) [proposed] P15 Given a url4 whose sum entry is hand-edited (an extra key
  `"note"`, `coefficients` as a list, a bool coefficient, a zero coefficient, `"source": "sums"`),
  then `Url4(...).to_python()` raises `ValueError` with the existing
  `"URL4 Candidate has a signals declaration this SDK version cannot rebuild"`.
- **SA-D3** (M×M) [implied] A sum adds no member call param: `injected_member_params({"risk":
  sf.Sum({"a": 1.0}), "a": sf.Verbalized("A: ([0-9]+)")})` is `{}`; with `"a"` =
  `sf.Logprob("prob")` (OpenRouter members) it is `{"logprobs": True}`.
- **SA-D4** (M×M) [existing S/fusion.py:131-134] Eight names that include a sum are accepted; nine
  are refused with the existing count message.
- **SA-D5** (M×L) [proposed] `sf.Sum` is unhashable (`hash(...)` raises `TypeError`), and two sums
  with the same terms are equal.

## 4. Non-functional requirements

- No new dependency. [existing]
- The messages name only the author's own names and sources, never a member text. [existing]

## 5. Out of scope

- The Engine computation ([signal-sum](signal-sum.md)), the display ([sum-band-display](sum-band-display.md)).
- E4a keys as components (D1); sums across members (D2).

## 6. Open questions

None.

## 7. TDD plan

New test files: `ST/test_signal_sum_api.py` (rows 1–11), `ST/test_sum_contract_fixtures.py`
(row 12: drift guard, a `BUILDERS` dict as in `ST/test_gate_contract_fixtures.py`),
`ET/test_combine_sum_run.py` (row 13, exemplar `ET/test_combine_gate_run.py`), new data file
`ET/data/combine_contract/sum_pick_candidate.url4`.

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| 1 | CHAR `fusions_without_a_sum_compile_unchanged` (SA-D1, the two named builders only) | unit | SA-D1 | H×M | passes today |
| 2 | `sum_keeps_sorted_float_coefficients_and_a_short_repr` | unit | SA-1, SA-D5 | H×M | `Sum` |
| 3 | `sum_refuses_bad_terms` (parametrized, SA-E1 with the exact messages) | unit | SA-E1 | H×M | constructor |
| 4 | `fusion_refuses_a_sum_of_an_undeclared_name` | unit | SA-E2 | H×M | `_check_sums` |
| 5 | `fusion_refuses_a_sum_of_a_sum_and_a_sum_of_itself` | unit | SA-E3 | H×M | `_check_sums` |
| 6 | `fusion_refuses_a_vote_weight_sum_with_a_raw_logprob_or_entropy` | unit | SA-E4 | H×M | `_check_weight_source` |
| 7 | `rules_and_gates_read_a_sum_by_name` | unit | SA-3, SA-D4 | H×M | — |
| 8 | `compile_writes_the_sum_entry` | unit | SA-2 | H×M | `_spec` |
| 9 | `a_sum_adds_no_member_param` | unit | SA-D3 | M×M | — |
| 10 | `url4_rebuilds_a_sum` | unit | SA-4 | H×M | `_SOURCES`, `_from_spec` |
| 11 | `rebuild_refuses_a_hand_edited_sum_entry` | unit | SA-D2 | M×M | `_from_spec` |
| 12 | `sum_pick_fixture_matches_the_sdk_compile` (drift guard; regenerate with `write_fixture`) | unit | SA-2 | H×M | new data file |
| 13 | `engine_runs_the_sum_pick_fixture_offline` (exactly three calls; output; evidence) | world | SA-5 | H×M | — |
| 14 | PIN public surface snapshot holds `Sum` (`ST/public_surface_snapshot.json`) | unit | SA-1 | H×M | `UPDATE_SURFACE_SNAPSHOT=1`, then a plain run (test-plan §2) |
