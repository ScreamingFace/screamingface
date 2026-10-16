# PRD: `sf.Gate(..., abstain_band=(lo, hi))` in the SDK (keyword, compile, rebuild, run)

**Source:** ans:Q2 ("the abstain band is ON sf.Gate: sf.Gate(..., abstain_band=(lo, hi))") ·
**Priority:** P0
**Lifecycle:** existing (`sf.Gate`, part 5) + delta
**Owner:** unassigned
Paths: [erd §3](../erd.md) · contracts: C4, C6 · uses: [abstain-band](abstain-band.md),
[sum-api](sum-api.md)

## 1. Summary and user story

As a benchmark author, I write `sf.Gate("mean:risk", "<=", 3.0, abstain_band=(2.5, 3.5))`. A bad
band fails at construction. The recipe compiles the band into the spec `gate` object, rebuilds
from its url4, and runs in the Engine: inside the band the Case abstains with `in_band`.

## 2. Background and constraints

- The gate is data, never Python code (part 5 P3). The band is two numbers in the recipe.
  [existing part 5]
- A gate without a band keeps its part 5 bytes (spec, url4, repr). [implied]

### 2.1 Current behavior

- `Gate.__init__(observe, cmp, threshold, *, otherwise="abstain")` (S/gate.py:51-66); `_spec`
  (:68-75) writes four keys; `_render` (:107-110) writes `otherwise=` only when it is not
  `"abstain"`; `_check_agreement` (:148-157).
- `_rebuilt_gate` (S/reducer.py:513-537) accepts exactly the keys
  `{"cmp", "observe", "otherwise", "threshold"}` and calls `Gate(observe, cmp, threshold,
  otherwise=...)` through `_decoded`, so a constructor error becomes the vote's "cannot rebuild"
  error.

**Delta (SDK).**

```python
# S/gate.py
@dataclass(frozen=True, slots=True, init=False)
class Gate:
    observe: str
    cmp: GateCmp
    threshold: float
    otherwise: Literal["abstain"] | Judge | Model
    abstain_band: tuple[float, float] | None  # new, last

    def __init__(self, observe, cmp, threshold, *, otherwise="abstain",
                 abstain_band: tuple[float, float] | None = None) -> None: ...
    # _spec: adds "abstain_band": [lo, hi] only when set.
    # _render: adds ", abstain_band=(lo, hi)" after otherwise, only when set.

# S/reducer.py _rebuilt_gate: the key set is the four part 5 keys, or those four plus
#   "abstain_band"; with the key, pass abstain_band=tuple(raw["abstain_band"]) when it is a list,
#   else pass the raw value (the constructor refuses it, and _decoded turns that into the
#   "cannot rebuild" error).
```

Band rules in the constructor, checked after `_check_agreement` (exact messages):

| Input | Error |
|---|---|
| not a `tuple` or `list` of exactly two items | `TypeError("Gate abstain_band must be a pair (lo, hi) of numbers")` |
| an item that is a bool or not `int`/`float` | the same `TypeError` |
| an int too large for a float, NaN or an infinity | `ValueError("Gate abstain_band must be finite")` |
| `lo > hi` | `ValueError("Gate abstain_band needs lo <= hi")` |
| `observe == "agreement"` and not `0 <= lo <= hi <= 1` | `ValueError("an agreement gate abstain_band must be between 0 and 1")` |

The stored value is `(float(lo), float(hi))`.

## 3. Scenarios and acceptance criteria

Recipe G (used below; signals as recipe R of [sum-api](sum-api.md)):

```python
sf.Fusion(
    ["prov/alpha", "prov/beta", "prov/gamma"],
    name="vote",
    signals={
        "risk": sf.Sum({"sev_a": 0.5, "sev_b": 0.3}),
        "sev_a": sf.Verbalized("A: ([0-9]+)"),
        "sev_b": sf.Verbalized("B: ([0-9]+)"),
    },
    synthesizer=sf.Vote(gate=sf.Gate("mean:risk", "<=", 3.0, abstain_band=(2.5, 3.5))),
)
```

### 3.1 Happy path

- **BA-1** Given `sf.Gate("agreement", ">=", 0.7, abstain_band=[0.6, 0.7])`, then `abstain_band ==
  (0.6, 0.7)`, `repr` is `"Gate('agreement', '>=', 0.7, abstain_band=(0.6, 0.7))"`, and `_spec()`
  is `{"cmp": ">=", "observe": "agreement", "otherwise": "abstain", "threshold": 0.7,
  "abstain_band": [0.6, 0.7]}`. `sf.Gate("chosen:x", "<", 1, abstain_band=(0, 2))` stores
  `(0.0, 2.0)`. [stated ans:Q2]
- **BA-2** Given recipe G, then `decode_combine_spec(<its intent>)["gate"] == {"abstain_band":
  [2.5, 3.5], "cmp": "<=", "observe": "mean:risk", "otherwise": "abstain", "threshold": 3.0}`.
  [stated ans:Q2]
- **BA-3** Given the url4 of recipe G, then `Url4(url4).to_python()` holds
  `sf.Gate('mean:risk', '<=', 3.0, abstain_band=(2.5, 3.5))`, and the Python it returns compiles to
  the same url4. With a judge fallback (`otherwise=sf.Judge("prov/judge", returns="label")`) the
  text is `sf.Gate('mean:risk', '<=', 3.0, otherwise=sf.Judge(...), abstain_band=(2.5, 3.5))`
  (the judge text as part 5 writes it). [proposed] P15
- **BA-4** Given the url4 fixture `gate_band_vote_candidate.url4` (the compile of recipe G), then
  the Engine world runs it offline twice, each with exactly three model calls:
  - run 1, replies `"A: 4\nB: 10\nyes"`, `"A: 2\nB: 5\nyes"`, `"A: 1\nB: 5\nno"` (risk 5.0, 2.5,
    2.0; `mean:risk` = `math.fsum([5.0, 2.5, 2.0]) / 3` = `3.1666666666666665`, inside the band):
    the Case abstains, the output is `""`, the gate record is `{"observe": "mean:risk",
    "observed": 3.1666666666666665, "cmp": "<=", "threshold": 3.0, "passed": None, "branch":
    "band", "otherwise": "abstain", "abstain_band": [2.5, 3.5]}`, the result reason is `in_band`;
  - run 2, replies `"A: 2\nB: 0\nyes"`, `"A: 2\nB: 0\nyes"`, `"A: 4\nB: 0\nno"` (risk 1.0, 1.0,
    2.0; mean `1.3333333333333333`, below the band, `<= 3.0` holds): `passed True`, `branch
    "majority"`, the output is `"A: 2\nB: 0\nyes"`. [stated ans:Q1, ans:Q2]

### 3.2 Error paths

- **BA-E1** Given each input of the §2.1 table, then the listed error: `abstain_band=0.5`;
  `(0.5,)`; `(0.1, 0.2, 0.3)`; `"ab"`; `(True, 0.7)`; `("0.6", 0.7)`; `(10**400, 0.7)`;
  `(float("nan"), 0.7)`; `(0.7, 0.6)`; an agreement gate with `(0.5, 1.5)`; an agreement gate with
  `(-0.1, 0.5)`. [proposed] P7
- **BA-E2** Given the url4 of recipe G with its spec `gate.abstain_band` hand-edited to `null`,
  `[2.5]`, `[2.5, 3.5, 4.5]`, `["a", 3.5]` or `[3.5, 2.5]`, or with an extra gate key `"note"`,
  then `Url4(...).to_python()` raises `ValueError("URL4 Candidate has a vote spec this SDK version
  cannot rebuild")`. [existing S/reducer.py:185-186 error]; [proposed]

### 3.3 Derived scenarios (risk-ordered)

- **BA-D1** (H×M) [implied] A gate without a band keeps its part 5 bytes: `sf.Gate("agreement",
  ">=", 0.7)._spec()` has exactly the four part 5 keys, its `repr` is `"Gate('agreement', '>=',
  0.7)"`, and the four part 5 gate fixtures still equal their builders
  (`ST/test_gate_contract_fixtures.py` `BUILDERS`, the four fixed names).
- **BA-D2** (M×M) [proposed] A band of one point (`(0.7, 0.7)`) is valid (closed interval).
- **BA-D3** (M×M) [existing part 5 GA-E2] A band does not change the declared-name rule: a gate
  `"mean:zzz"` with a band on a Fusion that does not declare `zzz` fails with the part 5 message.

## 4. Non-functional requirements

- No new dependency. [existing]

## 5. Out of scope

- The Engine decision and the record ([abstain-band](abstain-band.md)), the display.

## 6. Open questions

None.

## 7. TDD plan

New test file: `ST/test_band_api.py` (rows 1–6, 9). Row 7 appends one builder function and one
`BUILDERS |= {...}` line to `ST/test_sum_contract_fixtures.py` (new in unit 2); row 8 appends one
test function to `ET/test_combine_sum_run.py` (new in unit 2). New data file
`ET/data/combine_contract/gate_band_vote_candidate.url4`.

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| 1 | CHAR `a_gate_without_a_band_keeps_its_part_5_form` (BA-D1) | unit | BA-D1 | H×M | passes today |
| 2 | `gate_takes_a_closed_band` (BA-1, BA-D2) | unit | BA-1 | H×M | `Gate.abstain_band` |
| 3 | `gate_refuses_bad_bands` (parametrized, BA-E1, exact messages) | unit | BA-E1 | H×M | `_band` |
| 4 | `compile_writes_the_band` | unit | BA-2 | H×M | `_spec` |
| 5 | `url4_rebuilds_a_band_with_and_without_a_fallback_judge` | unit | BA-3 | H×M | `_rebuilt_gate`, `_render` |
| 6 | `rebuild_refuses_a_hand_edited_band` | unit | BA-E2, BA-D3 | M×M | `_rebuilt_gate` |
| 7 | `gate_band_fixture_matches_the_sdk_compile` (drift guard) | unit | BA-2 | H×M | new data file |
| 8 | `engine_runs_the_band_fixture_offline` (run 1 and run 2 of BA-4) | world | BA-4 | H×H | — |
| 9 | PIN public surface snapshot (`Gate`: field and `__init__` keyword `abstain_band`) | unit | BA-1 | H×M | `UPDATE_SURFACE_SNAPSHOT=1`, then a plain run |
