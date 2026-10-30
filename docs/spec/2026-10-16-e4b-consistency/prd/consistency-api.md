# PRD: Consistency API and compile (`sf.Consistency`, the sample calls)

**Source:** epic sources table ("N extra calls per member. Uses E4a's sampler and normalizer."),
ans:Q3 (`sf.Consistency(n=5, temperature=1.0)`), ans:Q4 (a sample failure does not fail the Case)
· **Priority:** P0
**Lifecycle:** existing (characterize + delta)
**Owner:** unassigned
Paths: [erd §1, §2, §3, §4, §7](../erd.md) · contracts: C1, C2, C3, C5, C6 · uses:
[consistency-record](consistency-record.md), [consistency-value](consistency-value.md) · used by:
[consistency-rebuild](consistency-rebuild.md), [docs](docs.md)

## 1. Summary and user story

As a benchmark author, I write
`sf.Fusion(members, signals={"cons": sf.Consistency(n=5)}, synthesizer=sf.Pick(by_signal=sf.signal("cons")))`.
The SDK compiles n extra calls for each member, with distinct seeds and the temperature that I
state, and checks them in the free preflight before any spend. Each member's samples reach the
combine step as one panel that never fails, so a failed sample costs a sample, not the Case.

## 2. Background and constraints

- "Call that member N more times with different seeds." [stated epic]
- "sf.Consistency(n=5, temperature=1.0): the extra calls use distinct seeds and the stated
  temperature (default 1.0), the member's other params unchanged. Explicit and reproducible."
  [stated ans:Q3]
- "the count of failed samples is recorded; if all fail, the value is missing ... the Case does not
  fail." [stated ans:Q4]
- `sf.samples()` makes n Models of one route that differ in an integer `seed`
  (S/_samples.py:21-52; seeds 0..n-1 by default, n at most 256). [existing]
- The SDK preflight refuses a model whose catalog marks a param unsupported, before any spend
  (S/_evaluation/model_parameters.py:153-225); part 3 P12 puts injected params into
  `parameter_assignments` for this reason. [existing]
- The url4 broadcast panel leaves out a failed optional slot and gates only on `quorum`
  (packages/url4/src/url4/dag/nodes/broadcast_result.py:19-55, `_shared.py:256-262`). [existing]
- The Engine attributes a model operation by `(path, sorted params)` inside every root `panel_N`
  (E/benchmarks/operation_outputs.py:165-209); the binding vocabulary is
  `(model|synthesis|judge|writer)_N` (S/_operation_bindings.py:5-9, pinned by
  `ET/data/combine_contract/binding_names.json`). [existing]
- Accounting maps an operation kind to a stage (`_ACCOUNTED_STAGES`, S/accounting.py:40-42); an
  unknown kind gets no row. [existing]

### 2.1 Current behavior

- `S/signal_sources.py` has `Verbalized`, `Logprob`, `Entropy` and `_SOURCES` (:188-190). There is
  no `Consistency`.
- `Fusion.__init__` (S/fusion.py:53-76) checks the declaration (`_declared`, :108-121) and the
  logprob members (`_check_logprob_sources`, :201-219). `_declaration` (:124-142) holds the
  one-`sf.Entropy` rule (:137-141).
- `_CandidateCompiler._reducer_synthesizer` (S/_evaluation/candidate.py:588-676) compiles the spec,
  the accounting `sources`, the signal calls, then the combine call; `_fusion_context` (:804-836)
  writes `input`, `outputs` or `panel`, `signals`, `sources`.
- `combine_spec_text` (S/_evaluation/combine_spec.py:45-82) writes each declared entry as
  `source._spec()`.
- `_own_seed_calls` (S/_evaluation/runner.py:642-649) lists every compiled call with a `seed` for
  the `FixedSeedSittingWarning`.

**Delta.**

1. `S/signal_sources.py`: new `Consistency(SignalSource)`, `source = "consistency"`:

   ```python
   @dataclass(frozen=True, slots=True, init=False)
   class Consistency(SignalSource):
       """How often the member gives the same answer again (E4b part 7).

       Each member makes ``n`` more calls with distinct seeds at ``temperature``; its other
       params do not change. The value is the fraction of the successful samples whose answer,
       read with the step's own extract and normalize, equals the member's answer. A failed
       sample does not count; when every sample fails, the value is missing.
       """
       n: int
       temperature: float
       def __init__(self, n: int, *, temperature: float = 1.0) -> None: ...
       def __repr__(self) -> str:  # "Consistency(n=5, temperature=1.0)", always both
       def _spec(self) -> dict[str, object]:  # {"source": "consistency", "n": n, "temperature": t}
       def _entry(self, match: Mapping[str, object]) -> dict[str, object]:
           # the full wire entry: {**self._spec(), "match": dict(match)}
       # _from_spec: consistency-rebuild (it rebuilds an equal source from the _entry(...) dict)
   ```

   `n`: an int from 1 to 32, else `ValueError("sf.Consistency n must be an int from 1 to 32, not
   {n!r}")` (a bool is refused). `temperature`: an int or a float, finite, `>= 0`, stored as
   `float(t) + 0.0`, else `ValueError("sf.Consistency temperature must be a finite number of at
   least 0, not {t!r}")` (a bool is refused). `__all__` and `S/__init__.py` export `Consistency`
   (`sf.Consistency`). New helper `consistency_seed(k: int, j: int) -> int` (erd §2 formula).
   The module text changes with it (else it is false): line 1 names `sf.Consistency` too; the
   INVARIANT (S/signal_sources.py:6-7) becomes "a source compiles to one entry of the combine
   spec ``signals`` map, and ``_from_spec`` rebuilds an equal source from that entry (url4 →
   Python). ``sf.Consistency`` is the one source whose entry also holds the step's ``match``:
   the compile gives it to ``_entry(match)``, and ``_spec()`` is the entry without
   ``match``."; the `source` ClassVar comment of `SignalSource` lists `"consistency"`.
2. `S/fusion.py`:
   - in `_declaration`, directly after the one-`sf.Entropy` rule (the same place for the same
     kind of rule): `sum(source.source == "consistency" for source in value.values()) > 1` →
     `ValueError("a Fusion declares at most one sf.Consistency source: every member gets one set
     of samples")`;
   - new `_check_consistency_source(declared, members)` after `_check_logprob_sources` holds the
     three member-aware rules below:
   - a member that is not an `sf.Model` → `ValueError(f"sf.Consistency needs each Fusion member to
     be one sf.Model call; member {position} ({member.name!r}) is a nested Fusion or Pipeline")`;
   - `len(members) * n > 1024` → `ValueError(f"sf.Consistency(n={n}) on {count} members makes
     {count * n} extra calls; the limit is 1024 per Fusion")`;
   - a member `seed` param equal to `consistency_seed(k, j)` for ANY member position k and any j
     in 1..n (erd CN-I5) → `ValueError(f"member {position} ({member.name!r}) sets seed={seed},
     which is the seed of consistency sample {j} of member {k}; choose another seed")`.
3. `S/_evaluation/combine_spec.py` `combine_spec_text`: one `isinstance(source, Consistency)`
   branch writes `source._entry({"extract": <pinned step>, "normalize": <pinned step or None>})`
   (every other source keeps `source._spec()`): the plan's
   extract and normalize (after `resolve_benchmark_rule`) when the plan has an extract, else
   `_pinned_step("extract", _Step("last_line"), operators)` and
   `_pinned_step("normalize", _Step("text"), operators)`.
4. `S/_evaluation/candidate.py`:
   - thread `input_dependencies` from `_compile_fusion` through `_fusion` into
     `_reducer_synthesizer`;
   - in `_reducer_synthesizer`, after `_claim_accounting_sources` and BEFORE `_compile_signals`,
     `samples = self._sample_panels(fusion, input_context, input_dependencies)` when the Fusion
     declares a `Consistency`. For each member k (1-based) and j in 1..n: `binding =
     f"model_{self._model_count + 1}"` (increment the counter); `call = RelExpr(path=<member
     route>, context=input_context, intent=Text(_url4_text(member.prompt or
     DEFAULT_ANSWER_PROMPT)), params=((OPERATION_BINDING_PARAM, binding), *resolved_params(
     <member params without seed and temperature, author order>), ("temperature", str(t)),
     ("seed", str(consistency_seed(k, j)))))`; the slot and the panel of erd §3; the operation
     `_compiled_operation(id=f"op_{binding}", kind="sample", label=f"{member.name} sample",
     depends_on=input_dependencies)`; `self._record_parameter_assignment(f"op_{binding}", route,
     {<member params without seed and temperature>, "temperature": t, "seed": s})`. The sample
     call is NOT passed to `_count_call` (never a claimant). The panel name takes the next
     `self._panel_count`;
   - the combine context: `_fusion_context(..., samples={member_k: "$panel_M"})`; `_fusion_context`
     writes `samples` after `outputs` or `panel` and before `signals`. Its docstring says "Key
     order is input, outputs (or panel), samples, signals, sources", and the comment at
     S/url4.py:83-85 says the context is "{input, outputs or panel, samples, signals, sources}"
     (the samples precede the signals, so `_CONTEXT_SIGNALS` still finds `signals` at the end);
   - the combine `depends_on` becomes `(*dependencies, *signals.operation_ids,
     *sample_operation_ids)`. WHY the samples go last: S/_case_views.py:41-45 and :277 take
     `depends_on[:len(members)]` as the member producers (overview P7);
   - the reducer topology node gets `samples=tuple(_SampleTopology(f"member_{k}", nodes))`;
   - a corrective loop (`_compile_corrective`, S/_evaluation/corrective.py:124-141) refuses a
     Recipe in which any Fusion declares `sf.Consistency`: `ValueError("sf.Consistency is not
     supported inside a corrective loop in this version")`.
5. `S/_evaluation/topology.py` (encode side only; decode is consistency-rebuild): `_OperationRole`
   adds `"sample"`; new `_SampleTopology(member: str, sources: tuple[_RecipeTopology, ...])`;
   `_RecipeTopology.samples: tuple[_SampleTopology, ...] = ()`; `_encode_reducer` writes
   `"samples": [{"member": ..., "sources": [_encode_model(node), ...]}, ...]` only when present;
   `_operation_shape` returns `("sample", "sample")` for `role == "sample"`.
6. `S/accounting.py`: `_ACCOUNTED_STAGES` adds `"sample": "generation"`.
7. `S/_evaluation/runner.py` `_own_seed_calls`: skip an assignment whose operation kind is
   `sample` (the sample seeds are part of the method, and the author cannot drop them).

## 3. Scenarios and acceptance criteria

Recipe F1 (fixture `consistency_pick_candidate.url4`):
`sf.Fusion(["prov/alpha", "prov/beta", "prov/gamma"], name="pick", signals={"cons":
sf.Consistency(n=3)}, synthesizer=sf.Pick(by_signal=sf.signal("cons")))`.
Recipe F2 (fixture `consistency_median_candidate.url4`): the same members, `name="median"`,
`signals={"cons": sf.Consistency(n=2, temperature=0.7)}`, `synthesizer=sf.Median()`.

### 3.1 Happy path

- **CA-1** Given `sf.Consistency(n=5)`, then `n == 5`, `temperature == 1.0`, `repr ==
  "Consistency(n=5, temperature=1.0)"`, `_spec() == {"source": "consistency", "n": 5,
  "temperature": 1.0}` (the entry without `match`), and `_entry(M) == {"source": "consistency",
  "n": 5, "temperature": 1.0, "match": M}` with M the F1 match of CA-3;
  `sf.Consistency(3, temperature=0)` has `temperature == 0.0`. [stated
  ans:Q3]
- **CA-2** Given F1 compiled with the Engine catalog, then the url4 has the member calls
  `model_1`..`model_3` (no new param), then the sample calls `model_4`..`model_12` (alpha j=1..3,
  beta j=1..3, gamma j=1..3), each in a slot `sample_j` with `optional` of the panels `panel_1`
  (alpha), `panel_2` (beta), `panel_3` (gamma), each panel with `quorum=0`; the params of
  `model_4` are `(("binding", "model_4"), ("temperature", "1.0"), ("seed", "2063835758"))`; the
  seeds of `model_5`..`model_12` are 10968804, 1079774124, 966517312, 107840383, 1732381022,
  1073252422, 137802004, 992611152. [stated ans:Q3]; [proposed] P5
- **CA-3** Given F1, then the combine context is `{input: '$input', outputs: {member_1:
  '$model_1', member_2: '$model_2', member_3: '$model_3'}, samples: {member_1: '$panel_1',
  member_2: '$panel_2', member_3: '$panel_3'}}`, and the spec entry is `"cons": {"match":
  {"extract": {"args": {}, "op": "last_line@1"}, "normalize": {"args": {}, "op": "text@1"}},
  "n": 3, "source": "consistency", "temperature": 1.0}`. Given F2, the entry has `"match":
  {"extract": {"args": {}, "op": "last_number@1"}, "normalize": {"args": {}, "op":
  "numeric@1"}}` (the median's own steps) and `"temperature": 0.7`. [proposed] P3
- **CA-4** Given F1, then the operations are, in order: `op_model_1`..`op_model_3` (kind `model`),
  `op_model_4`..`op_model_12` (kind `sample`, labels `"alpha sample"` ×3, `"beta sample"` ×3,
  `"gamma sample"` ×3, `depends_on == ()`), `op_synthesis_1` (kind `combine`, `depends_on ==
  ("op_model_1", ..., "op_model_12")`); the `parameter_assignments` hold one entry per sample
  operation with the params `{"temperature": 1.0, "seed": <s>}`. [proposed] P7
- **CA-5** Given F1, then the reducer topology node is `{"binding": "synthesis_1", "kind":
  "reducer", "name": "pick", "samples": [{"member": "member_1", "sources": [{"binding":
  "model_4", "kind": "model", "name": "alpha", "named": false, "role": "sample"}, <model_5>,
  <model_6>]}, <member_2: model_7..9>, <member_3: model_10..12>]}`. [proposed] P8
- **CA-6** Given the F1 fixture run offline in the Engine world, with a gateway that answers the
  member calls alpha `"B"`, beta `"C"`, gamma `"A"` and the sample calls by seed with the
  consistency-value fixture W texts (alpha `"A"`, `"B"`, `"b"`; beta `"A"`, `"A"`, `"c d"`;
  gamma `"a"`, `"A."`, `"A"`), then the Case output is `"A"`, the combine evidence is the fixture W
  evidence (chosen `member_3`; values 0.6666666666666666, 0.0, 1.0), the gateway got 12
  requests, and each sample request body has `"temperature": 1.0`, its `"seed"`, and no
  `"binding"`. When the gamma sample with seed 137802004 gets HTTP 400, the Case output is still
  `"A"`, it is not failed, and the gamma record is `{"member_id": "member_3", "matched": 2,
  "succeeded": 2, "failed": 1}`. [stated ans:Q4]
- **CA-7** Given a member `sf.Model("prov/alpha", params={"temperature": 0.2, "seed": 7,
  "max_tokens": 64})` at position 1 and `sf.Consistency(n=1, temperature=0.9)`, then its sample
  call params are `(("binding", "model_4"), ("max_tokens", "64"), ("temperature", "0.9"),
  ("seed", "2063835758"))`, and the member call keeps `temperature=0.2` and `seed=7`. [stated
  ans:Q3 "the member's other params unchanged"]

### 3.2 Error paths

- **CA-E1** `sf.Consistency(0)`, `(33)`, `(True)`, `(2.5)`, `(n=3, temperature=-0.1)`,
  `(n=3, temperature=float("nan"))`, `(n=3, temperature=True)`, `(n=3, temperature="1")` raise
  `ValueError` with the texts of delta 1. [proposed]
- **CA-E2** A Fusion with two `sf.Consistency` names; a Fusion whose member 2 is an `sf.Fusion`;
  33 members with `sf.Consistency(n=32)`; a member 1 with `params={"seed": 2063835758}` and
  `sf.Consistency(n=1)` ("member 1 ('alpha') sets seed=2063835758, which is the seed of
  consistency sample 1 of member 1; choose another seed"); a member 2 with `params={"seed":
  2063835758}` and `sf.Consistency(n=1)` ("member 2 ('beta') sets seed=2063835758, which is the
  seed of consistency sample 1 of member 1; choose another seed"); a Fusion with a model synthesizer and `signals={"cons":
  sf.Consistency(n=2)}` — each raises `ValueError` at construction, before any call, with the
  texts of delta 2 (the last one with the existing DS-I3 text). [proposed]
- **CA-E3** Given F1 and a model catalog whose `prov/alpha` row marks `seed` with
  `provider_support == "unsupported"`, then the preflight raises
  `PlanningError(code="unsupported_model_parameter")` before any model call; the same for
  `temperature`. [existing S/_evaluation/model_parameters.py:153-225]; [proposed] P17
- **CA-E4** A `sf.CorrectiveLoop` whose member is an F1-shaped Fusion fails at compile with
  `ValueError("sf.Consistency is not supported inside a corrective loop in this version")`.
  [proposed] P19

### 3.3 Derived scenarios (risk-ordered)

- **CA-D1** (H×M) [implied] A Fusion without `sf.Consistency` compiles to the same bytes as
  before: each of the 47 url4 files of list L47 equals its builder's compile (the existing drift
  guards stay green; this unit adds no edit to them).
- **CA-D2** (H×M) [proposed] P6 The sample fingerprints never equal a member fingerprint: for F1,
  the set of `(path, sorted params)` of the samples and the set of the members do not meet, and no
  two samples share one.
- **CA-D3** (H×M) [proposed] P18 Given F1 compiled into a Candidate and a run seed, then
  `_own_seed_calls(candidate) == ()` (no `FixedSeedSittingWarning` for the samples); a member
  with its own `seed` param is still listed.
- **CA-D4** (M×M) [proposed] P7 Given F1, the accounting breakdown of a Case with an accounting
  record on `op_model_4` has a `generation` row for `op_model_4` with `member_id None`.
- **CA-D5** (M×M) [implied] A quorum Fusion (`quorum=2`) with `sf.Consistency(n=1)`: the member
  panel is `panel_1`, the sample panels are `panel_2`..`panel_4`, the context has `panel:
  '$panel_1'` and `samples: {member_1: '$panel_2', ...}`.
- **CA-D6** (M×M) [implied] Two stages: `sf.Pipeline([sf.Model("prov/delta"), F1])`: the sample
  calls read `'$model_1'` as their context and their operations `depends_on == ("op_model_1",)`.
- **CA-D7** (M×L) [implied] `sf.samples("prov/alpha", 3)` members with `sf.Consistency(n=2)`
  compile: the member seeds 0, 1, 2 stay on the member calls; the sample seeds are `s(k, j)`.
- **CA-D8** (M×L) [proposed] The `"logprobs"` param that an `sf.Logprob` declaration adds to the
  member calls is not on the sample calls.

## 4. Non-functional requirements

- Cost: each member makes n extra calls on every Case: a Fusion of M members makes M × n extra
  calls (at most 1024). They run in parallel with the members (they read the input, not the
  member answer). The README states it (docs). [stated epic "N extra calls per member"]
- url4 size: about 300 bytes per sample call; at the limit about 300 KB. [proposed]

## 5. Out of scope

- The url4 → Python rebuild and the replay of a consistency url4 (consistency-rebuild).
- A sample seed that follows the run seed (overview D1). A paid live run (D6).

## 6. Open questions

None.

## 7. TDD plan

This PRD is built in two units (plan §2). Unit 3 (`consistency-api-source`): rows 2, 3, 14 (the
source, `_entry`, the seed helper, the Fusion rules, the exports, the public surface PIN). No
compile path reads a `Consistency` in unit 3, and no test compiles one, so the gates stay
green. Unit 4 (`consistency-api-compile`): rows 1, 4–13 (the compile, the topology encode,
accounting, the runner, the corrective refusal, the fixtures, the Engine run).

New test files: `ST/test_consistency_api.py` (rows 1–5, 8–13; unit 3 creates it, unit 4 appends
to it), `ST/test_consistency_contract_fixtures.py`
(row 6, the drift guard with a `BUILDERS` map and `write_fixture`, as in
`ST/test_gate_contract_fixtures.py`), `ET/test_combine_consistency_run.py` (row 7; its own
`httpx.MockTransport` responder keyed by model and seed, built like
`ET/test_world_combine_quorum.py:58-117`; it does not edit `ET/_signal_world.py`). New data files:
`ET/data/combine_contract/consistency_pick_candidate.url4`,
`ET/data/combine_contract/consistency_median_candidate.url4`.

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| 1 | CHAR `recipes_without_consistency_compile_to_the_same_url4` (the builders of a fixed list of five existing fixtures from L47: `vote_candidate.url4`, `quorum_vote_candidate.url4`, `logprob_pick_mean_candidate.url4`, `gate_judge_vote_candidate.url4`, `samples_vote_candidate.url4`, by name, compared with the file) | unit | CA-D1 | H×M | passes today |
| 2 | `consistency_holds_n_and_the_temperature` and `consistency_refuses_bad_values` | unit | CA-1, CA-E1 | H×M | `Consistency`, `_entry`, the module text |
| 3 | `fusion_refuses_a_bad_consistency_declaration_before_any_call` (parametrized, CA-E2) | unit | CA-E2 | H×H | the `_declaration` rule, `_check_consistency_source` |
| 4 | `the_sample_calls_have_distinct_seeds_and_the_stated_temperature` (F1 bindings, panels, params; CA-7 params) | unit | CA-2, CA-7 | H×H | `_sample_panels` |
| 5 | `the_context_and_the_spec_carry_samples_and_the_match` (F1, F2) | unit | CA-3 | H×H | `_fusion_context`, `combine_spec_text` |
| 6 | `consistency_url4_fixtures_match_the_sdk_compile` (F1, F2; a fixed tuple `_FIXTURES`) | contract | CA-2, CA-3 | H×M | write the two files with `write_fixture` |
| 7 | `the_engine_runs_the_consistency_pick_and_a_failed_sample_does_not_fail_the_case` (two runs, CA-6) | engine world | CA-6 | H×H | — (units 1–2 and this unit) |
| 8 | `the_operations_and_the_preflight_assignments_list_every_sample` (also: the combine `depends_on` starts with the member operations, P7 WHY) | unit | CA-4 | H×M | `_compiled_operation`, `_record_parameter_assignment` |
| 9 | `the_reducer_topology_lists_the_samples` | unit | CA-5 | M×M | `_encode_reducer`, `_SampleTopology` |
| 10 | `the_preflight_refuses_a_model_without_seed_or_temperature_before_any_call` | unit | CA-E3 | H×M | — (uses `preflight_sync` with a fake details loader, as the `sf.samples` preflight tests do) |
| 11 | `sample_fingerprints_never_meet_member_fingerprints` and `the_logprob_params_stay_on_the_members` | unit | CA-D2, CA-D8 | H×M | — |
| 12 | `samples_are_not_fixed_seed_calls` and `sample_operations_are_generation_accounting_rows` | unit | CA-D3, CA-D4 | M×M | `_own_seed_calls`, `_ACCOUNTED_STAGES` |
| 13 | `quorum_pipeline_and_samples_members_compile_samples` (CA-D5, CA-D6, CA-D7) and `a_corrective_loop_refuses_consistency` (CA-E4) | unit | CA-D5–D7, CA-E4 | M×M | panel counter; corrective check |
| 14 | PIN `public_surface_has_sf_consistency` (regenerate `ST/public_surface_snapshot.json` with `UPDATE_SURFACE_SNAPSHOT=1`: `sf.Consistency`, its `__init__`, its fields) | unit | §2 delta 1 | M×M | test-plan §2 |

Pinned edits of this PRD (owner approval, plan §6): `ST/public_surface_snapshot.json`.
