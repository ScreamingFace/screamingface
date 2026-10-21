# PRD: Gate API (`sf.Gate`, `sf.Vote(gate=...)`, compile, rebuild)

**Source:** ans:Q1–Q3 · **Priority:** P0
**Lifecycle:** existing (characterize + delta)
**Owner:** unassigned
Paths: [erd §1–§3](../erd.md) · contracts: C1, C2, C7 · component: [gate-record](gate-record.md) ·
uses: [gate-decision](gate-decision.md) (the Engine runs the compiled fixtures)

## 1. Summary and user story

As a benchmark author, I want to write the gate in Python as data
(`sf.Vote(gate=sf.Gate("agreement", ">=", 0.7, otherwise=sf.Judge(...)))`), have it checked before
any spend, compiled to the url4 the Engine runs, and written back by `Url4.to_python()`, so that I can
share, replay and edit a gated recipe like any other recipe.

## 2. Background and constraints

- The gate is a comparison against a named number, data and not Python code (OME-1291: "It is not a
  Python function ... nobody else could replay it"). [stated E4c constraint]
- "The threshold is a number in the recipe." [stated epic]
- Fallbacks: "Abstain", "Judge that copies", "Writing model". [stated ans:Q3]
- A rule that reads a name that the Fusion does not declare fails before any member call.
  [existing part 3 ans:Q1, S/fusion.py:165-181]

### 2.1 Current behavior

- `sf.Vote(*, extract, normalize, weights, judge)` (S/reducer.py:458-557). `_plan()` builds
  `_vote_plan(...)` (:389-413) with `signal_calls = (judge._signal_call(),)` for a judge-weighted vote.
  `_rebuild(spec, signals)` (:516-526) reads only a `judge` signal.
- `_ReducerPlan` (S/reducer.py:65-85) has no gate.
- `combine_spec_text` (S/_evaluation/combine_spec.py:45-82) writes the eight keys and `signals`.
- `_compile_signals` (S/_evaluation/reducer_signals.py:98-167) compiles each `_ModelSignal` to one
  source and one operation; `_signal_call_role` (:170-184) needs `field is not None` exactly for the
  `writer` role.
- `_signal_role` (S/_evaluation/topology.py:503-508) knows `judge` and `writer_<field>`;
  `_decode_signal` (:511-525) needs a `projection` exactly for the `writer` role;
  `_operation_shape` (:91-105) gives `("judge", "judge")` and `("writer", f"write {field}")`.
- `_model_signal` (S/url4.py:558-575) gives a `judge` key its outputs-form prompt;
  `_rebuilt_reducer` (:538-555) falls back to `sf.Reduce` when a named class refuses.
- `sf.Fusion` checks the reads of its reducer against `signals=` in `_declared` (S/fusion.py:107-119).

**Delta.**

New module `S/gate.py` (exported as `sf.Gate`):

```python
type GateCmp = Literal[">=", ">", "<=", "<"]

@dataclass(frozen=True, slots=True, init=False)
class Gate:
    """Keep the majority when ``observe cmp threshold`` holds; else run ``otherwise``.

    ``observe``: "agreement", "chosen:<name>" or "mean:<name>" (a name the Fusion declares).
    ``otherwise``: "abstain" (the Case abstains with gate_not_met), an sf.Judge(returns="label")
    that names a member whose text is the answer, or an sf.Model that writes the answer.
    In this version the fallback call runs on every Case; the gate chooses and records.
    """
    observe: str
    cmp: GateCmp
    threshold: float
    otherwise: Literal["abstain"] | Judge | Model

    def __init__(self, observe: str, cmp: GateCmp, threshold: float, *,
                 otherwise: Literal["abstain"] | Judge | Model = "abstain") -> None: ...
    def _spec(self) -> dict[str, object]:
        """{"cmp", "observe", "otherwise": "abstain" | "judge" | "writer", "threshold": float}."""
    def _signal_call(self) -> _ModelSignal | None:
        """None for abstain. For a Judge: dataclasses.replace(self.otherwise._signal_call(),
        key="fallback_judge") (reuse Judge._signal_call, S/judge.py:190-196; never rebuild the
        prompt by hand). For a Model: _ModelSignal("fallback_writer", model.model,
        model.prompt or DEFAULT_SYNTHESIS_PROMPT, model.params).
        Unit 3 (plan §2): the Judge and Model branches raise NotImplementedError; unit 4 fills them."""
    def _declared_name(self) -> str | None:
        """<name> of chosen:<name> / mean:<name>; None for agreement."""
    def __repr__(self) -> str:   # Gate('agreement', '>=', 0.7) [+ ", otherwise=" + repr]
    def _python(self) -> str:    # sf.Gate(...), with sf.Judge(...) / sf.Model(...) inside
```

Constructor errors (each message never echoes a rubric or a prompt):

| Input | Error |
|---|---|
| `observe` not `str` | `TypeError("Gate observe must be text")` |
| `observe` not `agreement`, `chosen:<name>`, `mean:<name>` with the declared-name rule | `ValueError("Gate observe must be 'agreement', 'chosen:<name>' or 'mean:<name>', where <name> is a declared signal name")` |
| `observe` names an E4a key (`chosen:cost_usd`) | the same `ValueError`, plus `"; an E4a key such as cost_usd is not a gate input"` |
| `cmp` not in the four | `ValueError("Gate cmp must be '>=', '>', '<=' or '<'")` |
| `threshold` a `bool` or not `int`/`float` | `TypeError("Gate threshold must be a number")` |
| `threshold` not finite | `ValueError("Gate threshold must be finite")` |
| `agreement` with `<=` or `<` | `ValueError("an agreement gate keeps the majority when the agreement is high; use '>=' or '>'")` |
| `agreement` with threshold outside `[0, 1]` | `ValueError("an agreement gate threshold must be between 0 and 1")` |
| `otherwise` a `str` other than `"abstain"` | `ValueError("Gate otherwise must be 'abstain', an sf.Judge or an sf.Model")` |
| `otherwise` an `sf.Judge` with `returns="scores"` | `ValueError("a gate fallback judge needs sf.Judge(..., returns='label'): it names one member")` |
| `otherwise` an `sf.Model` with `name=` or `optional=True` | `ValueError("a gate fallback sf.Model takes no name= and is never optional")` |
| `otherwise` any other object (an `sf.Fusion`, a route string) | `TypeError("Gate otherwise must be 'abstain', an sf.Judge or an sf.Model")` |

Changes to existing code:

- `S/reducer.py`: `_ReducerPlan.gate: Gate | None = None`. `Vote.__init__(..., judge=None,
  gate=None, verify=None)`: `gate` must be `None` or an `sf.Gate` (`TypeError("Vote gate must be an
  sf.Gate")`, lazy import of `screamingface.gate`, the judge precedent :365-366); `verify` per
  [verifier-slot](verifier-slot.md). `_vote_plan(..., judge=..., gate=...)`: `signal_calls` = the
  judge call (if any), then the gate fallback call (if any); `gate=gate`. `_render` appends
  `, gate={show(self.gate)}` after the judge. `_rebuild` and `_from_spec_parts` take the gate (C7).
- `S/fusion.py`: in `_declared`, after `_check_reads`, check the gate name: a Vote gate whose
  `_declared_name()` is not in the declaration raises `ValueError(f"the gate reads {observe!r}, but
  this Fusion does not declare {name!r} (declared: {listed})")`, before any call.
- `S/_evaluation/combine_spec.py`: `combine_spec_text` writes `spec["gate"] = plan.gate._spec()`
  when the plan has a gate.
- `S/_evaluation/topology.py`: `_signal_role` maps `fallback_judge → "judge"` and
  `fallback_writer → "writer"`. `_decode_signal` needs a `projection` exactly when
  `_writer_field(key) is not None`. `_operation_shape(node, signal)` gives
  `("judge", "fallback judge")` for `fallback_judge` and `("writer", "fallback write")` for
  `fallback_writer`.
- `S/_evaluation/reducer_signals.py`: `_signal_call_role` checks "a projection field exactly for a
  `writer_<field>` key" (FC-I3) instead of "exactly for the writer role".
- `S/reducer.py` `Vote._rebuild` (unit 4): a `fallback_judge` signal becomes the gate's judge with
  `judge_from_signals((dataclasses.replace(signal, key="judge"),), "label")`. The signature of
  `judge_from_signals` does not change (C7).
- `S/url4.py`: `_model_signal` gives `fallback_judge` the outputs-form prompt like `judge`.
  `_rebuilt_reducer`: a spec with `gate` rebuilds only through `sf.Vote._rebuild` (no `sf.Reduce`
  fallback); a `gate` on another reducer raises the "cannot rebuild" error of that reducer.
- `S/__init__.py`: export `Gate`.

**Build split (plan §2, spec review 2026-10-16).** This PRD is built in two units:

- Unit 3 (gate-api-core): `S/gate.py` with the full constructor and its checks, `repr` and
  `_python`; `_signal_call` returns None for abstain and raises `NotImplementedError` for a Judge
  or a Model (the test-plan §2 stub rule); `Vote(gate=, verify=)`; `_ReducerPlan.gate`;
  `_render`; `Vote._rebuild` and `_from_spec_parts` for a gate with no fallback call; the Fusion
  name check; `combine_spec_text` writes `gate`; `S/__init__.py`; the fixtures
  `gate_abstain_vote_candidate.url4` and `gate_verbalized_vote_candidate.url4`. Rows 1, 2, 5, 6,
  7, 8, 9, 12a, 17a, 18a, 19, 20; verifier-slot rows 4–6.
- Unit 4 (gate-api-fallback): the judge and writer fallback calls: `Gate._signal_call` for a Judge
  and a Model; `_vote_plan` signal order; topology `_signal_role`, `_decode_signal`,
  `_operation_shape`; `_signal_call_role`; url4 `_model_signal`, `_rebuilt_reducer`; the
  `Vote._rebuild` signal split; the fixtures `gate_judge_vote_candidate.url4` and
  `gate_writer_vote_candidate.url4`. Rows 3, 4, 10, 11, 12b, 13, 14, 15, 16, 17b, 18b.

`ST/public_surface_snapshot.json` is pinned in unit 3 only; unit 4 adds no public name.

## 3. Scenarios and acceptance criteria

Fixture F (used below): `sf.Fusion(["prov/alpha", "prov/beta", "prov/gamma"], name="vote",
synthesizer=sf.Vote(gate=...))`, compiled with the Engine operator catalog
(`compile_candidate(recipe, operators=engine_operators())`).

### 3.1 Happy path

- **GA-1** Given F with `gate=sf.Gate("agreement", ">=", 0.7)`, then the combine spec holds
  `"gate":{"cmp":">=","observe":"agreement","otherwise":"abstain","threshold":0.7}`, the url4 has
  exactly four sources besides the recipe rider (`model_1`..`model_3`, `synthesis_1`), and the
  combine context has no `signals` key. [stated ans:Q3]
- **GA-2** Given F with `gate=sf.Gate("agreement", ">=", 0.7, otherwise=sf.Judge("prov/judge",
  returns="label", rubric="Pick the best answer."))`, then the url4 has one more source `judge_1` on
  route `/prov/judge` whose decoded `_Call.prompt` (Python form, newlines as `\n`; the url4 text
  holds U+2028 for each newline, S/_evaluation/candidate.py:969-980) starts with
  `judge-template@1 returns=label\n` and ends with `Rubric:\nPick the best answer.`; its params are `binding=judge_1`; the combine context has
  `signals: {fallback_judge: '$judge_1'}`; the operations hold
  `{"id": "op_judge_1", "kind": "judge", "label": "vote fallback judge", "depends_on":
  ["op_model_1", "op_model_2", "op_model_3"]}` and the combine operation depends on `op_judge_1`
  last; the recipe rider's reducer node has `signals: [{"key": "fallback_judge", "source":
  {"binding": "judge_1", "kind": "model", "name": "judge", "named": false, "role": "judge"}}]`.
  [stated ans:Q3]; [proposed] P5
- **GA-3** Given F with `otherwise=sf.Model("prov/writer", prompt="Write one answer.")`, then the
  source is `writer_1` on `/prov/writer` with the intent `Write one answer.`, the context has
  `signals: {fallback_writer: '$writer_1'}`, the operation is `{"id": "op_writer_1", "kind":
  "writer", "label": "vote fallback write", ...}`, and the rider signal has no `projection`.
  [stated ans:Q3]; [proposed] P7
- **GA-4** Given `sf.Fusion([...], name="vote", signals={"conf": sf.Verbalized("Confidence:
  ([0-9]+)")}, synthesizer=sf.Vote(gate=sf.Gate("chosen:conf", ">=", 80)))`, then the spec holds
  both `"signals":{"conf":{...}}` and `"gate":{"cmp":">=","observe":"chosen:conf","otherwise":
  "abstain","threshold":80.0}`. [stated ans:Q2]
- **GA-5** Given each Candidate of GA-1 to GA-4, then `Url4(url4).to_python()` gives Python that
  rebuilds a recipe whose `repr` equals the original's, and which compiles to the same url4 bytes.
  [proposed] P17
- **GA-6** Given `sf.Vote()` and every existing url4 fixture under `ET/data/combine_contract/`,
  then nothing changes: the bytes, the `repr` and the rebuild are as today. [implied]

### 3.2 Error paths

- **GA-E1** Given each bad input of the constructor table, then that exact error type, and the
  message holds the table's text. [proposed]
- **GA-E2** Given `sf.Fusion([...], synthesizer=sf.Vote(gate=sf.Gate("mean:lp", ">=", 0.5)))` with
  no `signals=`, or with `signals={"conf": ...}`, then `ValueError` naming `'mean:lp'`, `'lp'` and
  the declared names (`none`, or `conf`). No member is called. [stated part 3 ans:Q1]
- **GA-E3** Given `sf.Vote(gate="agreement >= 0.7")`, then `TypeError("Vote gate must be an
  sf.Gate")`. [proposed]
- **GA-E4** Given a hand-edited url4 (C7): a `gate` on a `median` spec; a `fallback_judge` call with
  no `gate` in the spec; a gate `otherwise: "judge"` whose `fallback_judge` call is missing; a gate
  `otherwise: "writer"` with a `fallback_judge` call, then `to_python()` raises the "cannot rebuild"
  `ValueError` (or the topology `_REDUCER_INVALID` error). [proposed] P17

### 3.3 Derived scenarios (risk-ordered)

- **GA-D1** (H×M) [existing S/_evaluation/reducer_signals.py:130,152] Given F with `quorum=2` and a
  judge fallback, then the judge call's context is the panel (`panel: '$panel_1'`) and its intent
  starts with `judge-template@1 returns=label input=panel\n`; a writer fallback reads the panel too.
- **GA-D2** (H×M) [existing S/_evaluation/reducer_signals.py:250] Given a judge fallback with
  `params={"temperature": 0}`, then the compiled candidate's `parameter_assignments` hold one entry
  for `op_judge_1` on `prov/judge` with that param, so the preflight checks it before any spend.
- **GA-D3** (M×M) [existing S/url4.py:284 rule] Given a writer fallback `sf.Model("prov/writer")`
  (no prompt), then the url4 intent is `DEFAULT_SYNTHESIS_PROMPT`, and the rebuild gives
  `sf.Model('prov/writer')` (no `prompt=`).
- **GA-D4** (M×M) [proposed] Given a Vote `judge=sf.Judge("prov/scorer", returns="scores",
  rubric="Score.")`, `weights=sf.signal("score:judge")` and a judge fallback on `prov/judge`, then
  the url4 has `judge_1` (key `judge`) and `judge_2` (key `fallback_judge`), in that order, and the
  context has `signals: {judge: '$judge_1', fallback_judge: '$judge_2'}`. It round-trips (GA-5).
- **GA-D5** (H×M) [existing ST/unit/test_signal_key_conformance.py:115-158] Given the Engine
  `_SIGNAL` pattern read with `ast`, then it matches `fallback_judge` and `fallback_writer`, and the
  SDK `_signal_role` maps them to `judge` and `writer`; `fallback_`, `fallback_x` and
  `Fallback_judge` are refused by both.
- **GA-D6** (H×M) [proposed] P19 Four SDK-compiled url4 fixtures (new files, each with a drift guard
  that compares the file to the compile): `gate_abstain_vote_candidate.url4` (GA-1 with
  `>= 0.7`) and `gate_verbalized_vote_candidate.url4` (GA-4) in unit 3;
  `gate_judge_vote_candidate.url4` (GA-2) and `gate_writer_vote_candidate.url4` (GA-3) in unit 4.
  Unit 4 appends its two builders to the builder table of unit 3 with a `|=` line.
- **GA-D7** (H×H) [stated ans:Q1] Given each GA-D6 fixture run offline in the Engine world with the
  member replies `prov/alpha "A"`, `prov/beta "A"`, `prov/gamma "B"` (and, for GA-4, the texts
  `"Confidence: 90\nA"`, `"Confidence: 60\nA"`, `"Confidence: 30\nB"`), the judge reply
  `"member_3"` and the writer reply `"C written"`: then the outputs are `""` (abstain, the Case
  abstained), `"B"`, `"C written"`, and `"Confidence: 90\nA"` (chosen conf 90 >= 80); the gateway
  gets exactly four requests for the judge and writer fixtures and three for the others (the
  fallback call runs, cost spent); the run record's combine evidence holds the gate record of
  [gate-decision](gate-decision.md).
- **GA-D8** (M×L) [proposed] Given `sf.Gate("agreement", ">=", 0.7, otherwise=sf.Model("prov/w",
  prompt="Write."))`, then `repr` is `Gate('agreement', '>=', 0.7, otherwise=Model('prov/w',
  prompt='Write.'))` and `_python()` is `sf.Gate('agreement', '>=', 0.7, otherwise=sf.Model('prov/w',
  prompt='Write.'))`; `sf.Gate("agreement", ">=", 1)` stores `threshold == 1.0` and reprs `1.0`;
  `otherwise="abstain"` is left out of both.
- **GA-D9** (M×M) [existing ST/test_public_surface.py] The public surface lists `sf.Gate` and the
  `Vote.__init__` signature with `gate: 'Gate | None' = None` and `verify: 'None' = None`.

## 4. Non-functional requirements

- All checks run at construction, before any spend. [stated part 3 ans:Q1 precedent]
- No import cycle: `S/reducer.py` imports `screamingface.gate` lazily; `S/gate.py` imports
  `screamingface.judge` and `screamingface.model` at the top. [proposed]

## 5. Out of scope

- A gate on another reducer or on a block form (D3). A scores judge fallback (D2). The skip (D1).

## 6. Open questions

None.

## 7. TDD plan

Order: characterize the ungated vote, then the constructor, then the compile, then the rebuild,
then the fixtures and the Engine runs. New test files: `ST/test_gate_api.py` (rows 1–16, 19, and
verifier-slot rows 4–6), `ST/test_gate_contract_fixtures.py` (row 17), `ET/test_combine_gate_run.py`
(row 18). Row 20 is the pinned public surface. Unit 3 builds rows 1, 2, 5–9, 12a, 17a, 18a, 19,
20; unit 4 builds rows 3, 4, 10, 11, 12b, 13–16, 17b, 18b (test-plan §2, the `a` / `b` rule).

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| 1 | CHAR `vote_without_gate_keeps_its_bytes_repr_and_rebuild` (each of the 43 url4 files of list L43 recompiles byte-equal; `repr(sf.Vote())` unchanged). A fixed list, never a glob, so later units cannot turn it red (test-plan §6) | unit | GA-6 | H×M | passes today |
| 2 | `gate_abstain_compiles_the_spec_gate_and_no_extra_call` | unit | GA-1 | H×H | `_ReducerPlan.gate`, `combine_spec_text` |
| 3 | `judge_fallback_compiles_one_label_judge_call` | unit | GA-2 | H×H | `Gate._signal_call`, topology |
| 4 | `writer_fallback_compiles_one_writer_call_without_projection` | unit | GA-3 | H×H | `_signal_call_role`, `_operation_shape` |
| 5 | `gate_reads_a_declared_signal` | unit | GA-4 | H×M | — |
| 6 | `gate_constructor_refuses_bad_observe_cmp_and_threshold` | unit | GA-E1 | H×M | `S/gate.py` |
| 7 | `gate_otherwise_refuses_a_scores_judge_a_named_model_and_a_recipe` | unit | GA-E1 | H×M | — |
| 8 | `fusion_refuses_a_gate_that_reads_an_undeclared_name` | unit | GA-E2 | H×H | `S/fusion.py` |
| 9 | `vote_refuses_a_gate_that_is_not_a_gate` | unit | GA-E3 | M×L | — |
| 10 | `quorum_panel_gives_the_fallback_the_panel` | unit | GA-D1 | H×M | existing panel rule |
| 11 | `fallback_params_go_to_the_preflight` | unit | GA-D2 | H×M | existing assignment |
| 12a | `gated_votes_round_trip_through_to_python` (GA-1, GA-4: abstain and verbalized) | unit | GA-5 | H×H | `Vote._rebuild`, url4 |
| 12b | `gated_votes_with_a_fallback_call_round_trip_through_to_python` (GA-2, GA-3, GA-D4) | unit | GA-5 | H×H | the `_rebuild` signal split |
| 13 | `hand_edited_gate_urls_cannot_rebuild` | unit | GA-E4 | H×M | `_rebuilt_reducer` |
| 14 | `writer_default_prompt_rebuilds_without_prompt` | unit | GA-D3 | M×M | — |
| 15 | `judge_weighted_vote_with_a_judge_fallback_has_two_judge_calls` | unit | GA-D4 | M×M | signal order |
| 16 | `signal_key_bind_accepts_the_fallback_keys` | unit | GA-D5 | H×M | Engine `_SIGNAL` (unit 2), SDK `_signal_role` |
| 17a | `gate_url4_fixtures_match_the_sdk_compile` (abstain, verbalized: 2 new fixture files) | unit | GA-D6 | H×M | `write_fixtures()` |
| 17b | `gate_fallback_url4_fixtures_match_the_sdk_compile` (judge, writer: 2 new fixture files) | unit | GA-D6 | H×M | `write_fixtures()` |
| 18a | `engine_runs_each_gated_fixture_offline` (abstain, verbalized: three requests each) | integration (Engine world, fake gateway) | GA-D7 | H×H | no Engine change expected |
| 18b | `engine_runs_each_fallback_fixture_offline` (judge, writer: four requests each) | integration (Engine world, fake gateway) | GA-D7 | H×H | no Engine change expected |
| 19 | `gate_repr_and_python_form` | unit | GA-D8 | M×L | `__repr__`, `_python` |
| 20 | PIN `public_surface_lists_gate_and_the_vote_parameters` (regenerate `ST/public_surface_snapshot.json`) | unit | GA-D9 | M×M | pinned edit |
