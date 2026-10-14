# PRD: Reducer slot in the SDK Fusion (component)

**Source:** prompt (OME-1289), ans:Q2, ans:Q3, ans:Q5 · **Priority:** P1, build third
**Lifecycle:** existing (Fusion, compiler) — characterize, then delta
**Owner:** unassigned
**Landing:** `packages/screamingface`

## 1. Summary and the flows it serves

The author writes `Fusion(members, synthesizer=<Reducer>)`. The compiler turns the reducer into
one url4 call to `/ensemble/combine/v1`, with the spec as data. This component owns the generic
part: the slot, the compile path, operator pinning against the catalog, binding names, and
rebuilding the recipe from url4. Each reducer class and its own compile checks are in the flow
PRDs.

## 2. Background and constraints

- The deterministic join goes in the Fusion synthesizer slot `[stated ans:Q2]`.
- The SDK checks operator names with `GET /v1/operators` before a run `[stated ans:Q3]`.
- Studio is out of scope `[stated ans:Q5]`.

### 2.1 Current behavior

- `Fusion.__init__` accepts `synthesizer: str | Recipe` and checks it with `_recipe()`
  `[existing packages/screamingface/src/screamingface/fusion.py:20]`.
- The compiler picks the compile path with an `isinstance` chain over Model, Fusion, Pipeline,
  CorrectiveLoop, and SelfCorrective. Any other type raises `TypeError`
  `[existing packages/screamingface/src/screamingface/_evaluation/candidate.py:156]`.
- `_fusion` compiles a `Model` synthesizer into one `synthesis_N` source with the context
  `{"input", "outputs": {"member_1", …}}`
  `[existing packages/screamingface/src/screamingface/_evaluation/candidate.py:248]`, `[…:394]`.
  A synthesizer that is not a Model compiles recursively `[…:315]`.
- Operations are named `op_<binding>`. Kinds are `model`, `synthesis`, and `answer`
  `[existing packages/screamingface/src/screamingface/_evaluation/model.py:100]`.
- `_RecipeTopology.kind` is one of `model|fusion|pipeline|corrective_loop|self_corrective`
  `[existing packages/screamingface/src/screamingface/_evaluation/topology.py:22]`.
- The SDK can rebuild a topology from a url4 expression (round-trip tests)
  `[existing packages/screamingface/tests/test_url4.py:120]`.

**Delta.**
1. Add `Reducer` (an abstract base, not a `Recipe`). `Fusion` accepts `Model | Recipe | Reducer`
   in the synthesizer slot `[stated ans:Q2]`.
2. `_fusion` gets a third branch: a `Reducer` compiles to
   `RelExpr(path="/ensemble/combine/v1", context=<fusion context>, intent=<canonical spec JSON>, params={"binding": "synthesis_N"})`
   `[proposed]`. The `binding` param makes the attribution fingerprint unique (see
   combine-evidence.md).
3. Operator pinning: the compiler resolves each short operator name (`"last_number"`) to the
   newest `name@version` in the catalog, and it writes the pinned id into the spec. A pinned id
   (`"last_number@1"`) must exist in the catalog `[proposed]`.
4. A new topology kind `reducer` with role `synthesis`. Url4 → topology recovery recognizes the
   combine route `[implied]`.
5. The binding pattern grows to `model|synthesis|judge|writer`, in the same change on the SDK and
   the engine `[proposed]`.
6. Public exports: `Vote`, `Median`, `Judge`, `Pick`, `Merge`, `FieldRule`, `Rank`, `Concat`,
   `samples` `[stated prompt]`.

## 3. Scenarios and acceptance criteria

### 3.1 Happy path

**SL-H1 A reducer compiles to one combine call.** `[stated ans:Q2]`
Given `Fusion([m1, m2, m3], synthesizer=Vote(extract="last_number", normalize="numeric"))`,
When the candidate compiles,
Then the url4 has three model sources and one `synthesis_1` source with the path
`/ensemble/combine/v1`, the context `{"input": $input, "outputs": {"member_1": $model_1, …}}`,
params `{"binding": "synthesis_1"}`, and an intent that is the canonical spec with pinned ids.

**SL-H2 Same recipe, same url4.** `[stated prompt]`
Given one recipe,
When it compiles twice, also in separate processes,
Then the url4 text is byte-identical.

**SL-H3 Reducer inside other recipes.** `[implied]`
Given a reducer Fusion as a Pipeline stage, as a member of another Fusion (answer kinds only;
Rank and Concat may not be members, see rank-keep-k.md), and inside a CorrectiveLoop,
When each compiles,
Then each compiles, and binding numbers stay unique across the candidate.

**SL-H4 Round trip.** `[implied]`
Given compiled url4 with a reducer,
When the SDK rebuilds the topology from url4,
Then it gets a `reducer` node with the same spec.

### 3.2 Error paths

**SL-E1 Unknown operator.** `[stated ans:Q3]`
Given `Vote(extract="last_numbr")`,
When the candidate compiles against the catalog,
Then the SDK raises `ValueError` before any submit. The message names the bad value and lists the
known names for that stage.

**SL-E2 Engine without the catalog.** `[proposed — gap §per-connection/sync]`
Given an engine that answers `GET /v1/operators` with 404,
When a candidate with a reducer compiles,
Then the SDK raises `EngineCapabilityError("this SF Engine does not support reducers")`. A
candidate without a reducer still compiles and runs.

**SL-E3 Catalog unreachable.** `[proposed — gap §per-connection/sync]`
Given a transport error on `GET /v1/operators`,
When a candidate with a reducer compiles,
Then the SDK raises `EngineUnavailableError` (the same type that the benchmark catalog uses).
There is no fallback to unpinned names.

### 3.3 Derived scenarios (risk order)

| ID | Title | Tag | I×L | Given / When / Then |
|---|---|---|---|---|
| SL-D1 | Binding pattern in lock-step | [proposed] | H×M | Given the SDK and the engine patterns, when a shared fixture lists `model_1, synthesis_2, judge_3, writer_4, answer_5`, then both accept the first four and reject `answer_5`. |
| SL-D2 | Model synthesizer unchanged | [implied] | H×M | Given a Fusion with a Model synthesizer, when it compiles, then the url4 is byte-identical to the output of today's compiler (characterization). |
| SL-D3 | Catalog is cached for each client | [proposed] | L×M | Given 10 compiles in one client, when they run, then `GET /v1/operators` runs once, and a 304 is used on refresh. |
| SL-D4 | A reducer is not a Recipe | [proposed] | M×L | Given `Pipeline([Vote(...)])`, when it is built, then `TypeError` says that a reducer must be a Fusion synthesizer. |
| SL-D5 | Pinned id that is no longer in the catalog | [proposed] | M×L | Given `extract="last_number@1"` and a catalog without it, when the candidate compiles, then `ValueError` names the id. |

## 4. Non-functional requirements

- Compile adds at most one catalog request for each client session (cached by ETag) `[proposed]`.
- Spec JSON is canonical: sorted keys, separators `(",", ":")`, UTF-8 `[proposed]`.

## 5. Out of scope

- Studio editor and Studio url4 parsing `[stated ans:Q5]`.
- A standalone `Combine` type `[stated ans:Q2]`.

## 6. Open questions

None.

## 7. TDD plan (outside-in from the public API)

Characterization tests come first and pass on today's code.

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| SL-1 | CHAR `model_synthesizer_url4_is_unchanged` (golden url4) | unit | [existing packages/screamingface/src/screamingface/_evaluation/candidate.py:248] | H×M | passes today |
| SL-2 | CHAR `binding_pattern_today_is_model_or_synthesis` | unit | [existing apps/screamingface-engine/src/screamingface_engine/benchmarks/operation_outputs.py:45] | M×M | passes today |
| SL-3 | `fusion_accepts_a_reducer_in_the_synthesizer_slot` | unit | [stated ans:Q2] | H×M | widen `_recipe()` check |
| SL-4 | `reducer_compiles_to_one_combine_call_with_binding_param` | unit | [proposed] | H×M | third branch in `_fusion` |
| SL-5 | `spec_is_canonical_and_url4_is_byte_stable_across_processes` | unit | [stated prompt] | H×M | canonical JSON |
| SL-6 | `short_operator_names_pin_to_newest_catalog_version` | unit | [proposed] | H×M | resolve against a catalog fake |
| SL-7 | `unknown_operator_name_raises_before_submit` | unit | [stated ans:Q3] | M×M | stage-aware lookup |
| SL-8 | `engine_without_catalog_raises_capability_error_only_for_reducers` | integration | [proposed] | M×M | 404 mapping |
| SL-9 | `catalog_transport_error_raises_engine_unavailable` | unit | [proposed] | M×L | reuse the error type |
| SL-10 | `binding_pattern_fixture_matches_sdk_and_engine` | unit (both packages) | [proposed] | H×M | shared fixture file |
| SL-11 | `reducer_fusion_compiles_inside_pipeline_fusion_and_corrective_loop` | unit | [implied] | M×M | recursive path |
| SL-12 | `url4_round_trip_recovers_reducer_topology` | unit | [implied] | M×M | recognize the combine route |
| SL-13 | `reducer_outside_a_fusion_slot_raises_type_error` | unit | [proposed] | M×L | reducer is not a Recipe |
| SL-14 | `catalog_is_fetched_once_per_client_and_revalidated_with_etag` | unit | [proposed] | L×M | cache in the client |
