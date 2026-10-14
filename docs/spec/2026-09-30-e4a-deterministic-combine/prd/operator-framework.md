# PRD: Operator framework and combine endpoint (component)

**Source:** prompt (OME-1289), ans:Q2, ans:Q3, ans:Q9 · **Priority:** P1, build first
**Lifecycle:** planned (new engine module); existing world wiring is characterized in §2.1
**Owner:** unassigned
**Landing:** `apps/screamingface-engine`

## 1. Summary and the flows it serves

This component is the generic part of E4a. It has one url4 endpoint (`/ensemble/combine/v1`), one
operator registry, one spec parser, and one evidence recorder. It runs a reducer spec over member
outputs with pure functions. It never calls a model.

It serves these flow PRDs: majority-vote-and-median, weighted-vote, judge-pick, pick-and-merge,
rank-keep-k, and concatenate. The samples flow does not use it, because samples only makes members. The operators themselves are
in [answer-operators.md](answer-operators.md). The SDK side is in
[reducer-slot.md](reducer-slot.md). The evidence wire path is in
[combine-evidence.md](combine-evidence.md).

## 2. Background and constraints

- "The function sees the member texts and, when stated, declared signals. It does not call a
  model." `[stated prompt]`
- "The same inputs produce the same output." `[stated prompt]`
- "It returns either one member's original text, unchanged, or a new object built only by
  field-level rules." `[stated prompt]`
- The operator plugins live in the engine. The SDK reads `GET /v1/operators` to check names
  before a run `[stated ans:Q3]`.
- When no member gives a usable value, the step fails and the case fails with a declared code
  `[stated ans:Q9]`.
- Hexagonal rule: the core defines ports, plugins implement them, and the core never imports the
  plugins. Wiring goes through a registry (CLAUDE.md).

### 2.1 Current behavior

- The world installs its endpoints in `build_world()`: candidate invocation, then corrective
  routes, then benchmarks `[existing apps/screamingface-engine/src/screamingface_engine/world/factory.py:244]`.
- `install_corrective_runtime` registers each route only when `node.processor_routes()` does not
  hold it yet `[existing apps/screamingface-engine/src/screamingface_engine/world/corrective.py:74]`.
- An endpoint handler receives `Request(path, context, intent, params)` and returns `str`
  `[existing packages/url4/src/url4/peer/_dispatch.py:52]`.
- A handler signals a failure with `ResolutionError(message, code=…, permanent=…)`
  `[existing packages/url4/src/url4/core/errors.py:106]`. The code must be in
  `DECLARED_FAILURE_CODES` `[existing apps/screamingface-engine/src/screamingface_engine/benchmarks/contract.py:54]`.
- A Fusion synthesizer today is always a model call
  `[existing packages/screamingface/src/screamingface/_evaluation/candidate.py:261]`.
- The layering gate keeps `world` as its own category. Modules that no list names are shared
  leaves, and both halves can import them `[existing .claude/scripts/check_layering.py:94]`.

**Delta.** Add a shared-leaf package `screamingface_engine/combine/` `[proposed]`:

| Module | Role |
|---|---|
| `combine/ports.py` | `Extractor`, `Normalizer`, `ReduceOp`, `SelectOp` protocols, `OperatorId` |
| `combine/registry.py` | `OperatorRegistry` (register, resolve, describe) |
| `combine/spec.py` | strict parse of `screamingface.combine-spec.v1` |
| `combine/evidence.py` | `CombineEvidence` model and the task-local recorder |
| `combine/endpoint.py` | `CombineEndpoint` handler and `install_combine_runtime(node, registry)` |
| `combine/builtins.py` | the one place that lists built-in operator modules (wiring) |
| `combine/operators/*` | plugins (see answer-operators.md) |
| `rest/operators.py` | `GET /v1/operators` |

`world/factory.py` calls `install_combine_runtime(node, BUILTIN_OPERATORS)` right after
`install_corrective_runtime` `[proposed]`.

## 3. Scenarios and acceptance criteria

### 3.1 Happy path

**FW-H1 Run a valid spec.** `[stated prompt]`
Given a world with the combine endpoint, and a valid vote spec over three outputs,
When url4 calls `/ensemble/combine/v1`,
Then the handler returns the chosen member's text, and it records one `CombineEvidence` with
`kind = answer`.

**FW-H2 No model call.** `[stated prompt]`
Given any valid spec,
When the endpoint runs,
Then it makes no HTTP call and records no `OperationCall` with provider accounting.

**FW-H3 Same inputs, same output.** `[stated prompt]`
Given the same spec and context,
When the endpoint runs 100 times, also in new processes with different `PYTHONHASHSEED` values,
Then the output text and the evidence JSON are byte-identical each time.

**FW-H4 Operator catalog.** `[stated ans:Q3]`
Given the engine started,
When a client sends `GET /v1/operators`,
Then the response is `{"object": "list", "data": [OperatorDescriptor…]}`, sorted by `id`, with
an `ETag`, and `If-None-Match` with the same tag returns 304. This copies `GET /v1/benchmarks`
`[existing apps/screamingface-engine/src/screamingface_engine/rest/benchmarks.py:43]`.

**FW-H5 The endpoint is installed once.** `[implied]`
Given `build_world()` runs twice on one node,
When the second call reaches `install_combine_runtime`,
Then the route is registered once, and the second call changes nothing.

### 3.2 Error paths

**FW-E1 No usable value.** `[stated ans:Q9]`
Given a vote where every member reading has a status other than `voted`,
When the endpoint runs,
Then it raises `ResolutionError(code="combine_no_votes", permanent=True)`, and the case is a
failure with that code.

**FW-E2 Unknown operator.** `[proposed — gap §per-connection/sync]`
Given a spec that names `last_number@9`, which is not registered,
When the endpoint runs,
Then it raises `combine_operator_unknown` (permanent). The message names the unknown id and does
not echo member text.

**FW-E3 Malformed spec.** `[proposed — gap §per-flow/boundary]`
Given an intent that is not valid JSON, has the wrong `schema`, has unknown keys, or has a
`members` list that differs from the context keys,
When the endpoint runs,
Then it raises `combine_spec_invalid` (permanent).

### 3.3 Derived scenarios (risk order)

| ID | Title | Tag | I×L | Given / When / Then |
|---|---|---|---|---|
| FW-D1 | Ties never depend on hash order | [proposed — gap §per-flow/ordering] | H×M | Given two answers with equal score, when the vote runs under 20 hash seeds, then the chosen member is always the first holder in author order. |
| FW-D2 | Context too large | [proposed — gap §cross-cutting/security] | M×L | Given a context larger than 64 MiB, or more than 256 members, when the endpoint runs, then it raises `combine_input_too_large` before it reads any output. |
| FW-D3 | Output text exceeds the read cap | [proposed — gap §per-flow/boundary] | M×L | Given one member output of 2 MiB, when the vote runs, then that member gets the status `too_large`, the other members vote, and the evidence shows the status. |
| FW-D4 | Params beyond `binding` | [proposed] | L×M | Given a combine call with params other than `binding`, when it runs, then it raises `combine_spec_invalid`. |
| FW-D5 | Duplicate operator registration | [proposed — gap §per-element/store] | H×L | Given two plugins that register the same `id`, when the registry is built, then the process stops at start with a clear error. |
| FW-D6 | Core does not import plugins | [stated prompt — CLAUDE.md] | M×M | Given the layering gate, when `combine/endpoint.py` or `combine/registry.py` imports from `combine/operators/`, then the gate fails. |
| FW-D7 | Catalog and endpoint agree | [implied] | M×M | Given the registry, when the catalog is served, then each `id` that the endpoint can resolve is listed, and no other `id` is listed. |
| FW-D8 | Corrective re-run | [implied] | M×M | Given a CorrectiveLoop whose member is a Fusion with a Vote, when round 2 runs, then a second combine call runs and records its own evidence. Attribution keeps the last one (see combine-evidence.md). |
| FW-D9 | Cancel during a run | [implied] | L×L | Given a run is cancelled, when the combine call is in progress, then nothing persists, because the endpoint has no side effects other than the task-local record. N/A for retry: the step is pure, so a retry is safe. |

## 4. Non-functional requirements

- **Latency.** p99 ≤ 5 ms for 5 members of 4 KiB; p99 ≤ 50 ms for 64 members of 64 KiB, on one
  worker CPU `[proposed]`. The step is O(total text length).
- **Memory.** At most 2× the context size `[proposed]`.
- **Caps.** Context ≤ 64 MiB, ≤ 256 members, 1 MiB read for each output, step output ≤ 8 MiB
  (the WebSocket frame limit), spec ≤ 64 KiB `[proposed]`. A cap breach raises
  `combine_input_too_large`, except the per-output read cap (status `too_large`).
- **Security.** All member text and all judge text is untrusted. Regular expressions run in linear
  time (no nested quantifiers). JSON parsing has a depth cap of 64 `[proposed]`. Error messages
  never include member text `[proposed]`.
- **Observability.** Each call writes one structured log line:
  `combine binding=<b> reducer=<r> voters=<v>/<n> agreement=<a> tie=<t> outcome=<ok|code>`
  `[proposed]`. Failures appear as case failures with the declared codes.
- **Failure codes to add** to `DECLARED_FAILURE_CODES`: `combine_spec_invalid`,
  `combine_operator_unknown`, `combine_no_votes`, `combine_input_too_large` `[proposed]`.

## 5. Out of scope

- Operators that the user uploads (E4e).
- Weights measured during the run (E4b).
- Skipping members (E4c).
- Studio support `[stated ans:Q5]`.
- Moving existing graders to the new operators `[stated ans:Q7]`.

## 6. Open questions

None.

## 7. TDD plan (core-out)

Order: core-out. The registry and the spec parser come first, because every flow depends on them.
Then the endpoint. Then wiring and the catalog. Write each test RED first, and see it fail on the
missing behavior.

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| FW-1 | `registry_rejects_a_duplicate_operator_id` | unit | [proposed] | H×L | `OperatorRegistry.register` raises on a known id |
| FW-2 | `spec_parse_rejects_unknown_keys_wrong_schema_and_member_mismatch` | unit | [proposed] | H×M | strict pydantic model, `extra="forbid"` |
| FW-3 | `endpoint_output_and_evidence_are_identical_across_hash_seeds` (property, subprocess) | unit | [stated prompt] | H×M | sorted keys; ordered lists only |
| FW-4 | `endpoint_returns_first_holder_text_byte_for_byte` | unit | [stated prompt] | H×M | select returns the member's original string |
| FW-5 | `endpoint_raises_combine_no_votes_when_no_member_votes` | unit | [stated ans:Q9] | H×M | count voters before reduce |
| FW-6 | `endpoint_raises_combine_operator_unknown_for_unregistered_id` | unit | [proposed] | M×M | registry `resolve` raises a typed error |
| FW-7 | `new_failure_codes_are_declared` | unit | [proposed] | M×M | add codes to `DECLARED_FAILURE_CODES` |
| FW-8 | `endpoint_makes_no_network_call` (httpx transport that fails on use) | unit | [stated prompt] | H×L | no client in the handler |
| FW-9 | `oversize_context_raises_before_parsing_outputs` | unit | [proposed] | M×L | size check first |
| FW-10 | `oversize_member_output_gets_too_large_status` | unit | [proposed] | M×L | per-output cap |
| FW-11 | `install_combine_runtime_is_idempotent` | unit | [implied] | L×M | check `processor_routes()` |
| FW-12 | `build_world_installs_the_combine_route` | integration | [implied] | M×M | call in `factory.py` after corrective |
| FW-13 | `layering_gate_fails_when_core_imports_a_plugin` (synthetic tree) | unit | [stated prompt] | M×M | add a `combine` rule to `check_layering.py` |
| FW-14 | `get_v1_operators_lists_registry_sorted_with_etag_and_304` | integration | [stated ans:Q3] | M×M | copy `rest/benchmarks.py` |
| FW-15 | `catalog_ids_equal_resolvable_ids` | unit | [implied] | M×M | one source: the registry |
| FW-16 | `endpoint_rejects_params_other_than_binding` | unit | [proposed] | L×M | param allow-list |
| FW-17 | `combine_log_line_has_the_documented_fields` | unit | [proposed] | L×M | one logger call |
