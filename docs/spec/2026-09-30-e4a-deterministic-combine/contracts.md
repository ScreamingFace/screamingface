# Contracts — E4a deterministic combine (OME-1289)

One section for each connection. PRD test ids (for example `FW-14`) point to the TDD tables in
`prd/`.

## K1 Operator catalog — SDK → Engine, sync, HTTP `GET /v1/operators`

- **Shape** `[proposed]`:

```json
{"object": "list",
 "data": [{"id": "last_number@1", "name": "last_number", "version": 1,
           "stage": "extract", "args_schema": {}, "summary": "Last number token."}]}
```

- **Policies.** `Cache-Control: public, max-age=300, must-revalidate`, a strong `ETag`, and 304 on
  `If-None-Match`. This copies `GET /v1/benchmarks`
  `[existing apps/screamingface-engine/src/screamingface_engine/rest/benchmarks.py:18]`. It has the
  same auth as `GET /v1/benchmarks`. It is replay-safe, so the SDK may retry it like other
  `_REPLAY_SAFE` reads `[existing packages/screamingface/src/screamingface/_engine/transport.py]`.
- **Failure behavior.** 404 → the SDK raises `EngineCapabilityError` for reducer candidates only.
  A transport error → `EngineUnavailableError`. On the engine side, the registry is built at start,
  so the route cannot fail after start except through the framework's 5xx.
- **Contract tests.** operator-framework FW-14, FW-15; reducer-slot SL-8, SL-9, SL-14.

## K2 Model parameter contract — SDK → Engine, sync, HTTP `GET /v1/model-parameters?model=…`

- **Shape.** Existing `[existing apps/screamingface-engine/src/screamingface_engine/rest/catalog.py:177]`.
  samples() reads only whether `seed` is supported.
- **Policies.** One lookup for each model and each client session (cached) `[proposed]`.
- **Failure behavior.** A lookup failure → `EngineUnavailableError`. The SDK never assumes support
  `[proposed]`.
- **Contract tests.** samples SM-3, SM-8.

## K3 Reducer compile — SDK compiler → url4 expression, data

- **Shape** `[proposed]`:

```text
RelExpr(path="/ensemble/combine/v1",
        context=<canonical JSON {"input": $input, "outputs": {"member_1": $model_1, …},
                                 "signals": {"judge": $judge_1} | absent}>,
        intent=<canonical JSON screamingface.combine-spec.v1>,
        params={"binding": "synthesis_N"})
```

- **Policies.** Canonical JSON (sorted keys, compact separators), so url4 text is byte-stable.
  Operator ids are pinned. The binding names match `^(?:model|synthesis|judge|writer)_\d+$` in the
  SDK and the engine.
- **Failure behavior.** Compile errors are `ValueError` or `TypeError` raised in the SDK before any
  submit.
- **Contract tests.** reducer-slot SL-4, SL-5, SL-6, SL-10, SL-12.

## K4 Combine call — url4 executor → combine endpoint, sync, in-process url4 route

- **Shape.** `Request(path, context, intent, params)` →
  `str` `[existing packages/url4/src/url4/peer/_dispatch.py:52]`. The returned text is:
  - `kind = answer`, not built: the chosen member's text, byte for byte;
  - `kind = answer`, built: canonical JSON (merge) or a canonical number (median value);
  - `kind = selection`: the selection JSON (rank) or the joined text (concat);
  - `kind = projection`: `{"member_i": <field value>}` JSON (merge with a model field).
- **Policies.** Pure and idempotent, so a retry is always safe. No timeout of its own: it finishes
  inside the url4 step budget (p99 ≤ 50 ms at the cap). Ordering: the endpoint reads `outputs` in
  the order of `spec.members`, never in dict order.
- **Failure behavior (callee).** `ResolutionError(permanent=True)` with one of:
  `combine_spec_invalid`, `combine_operator_unknown`, `combine_no_votes`,
  `combine_input_too_large` (new), or `judge_reply_invalid` (existing). The messages never echo
  member text.
- **Failure behavior (caller).** The url4 executor treats it like any route failure. The candidate
  invocation fails, and the case is a failure with that code
  `[existing apps/screamingface-engine/src/screamingface_engine/benchmarks/aggregation.py:153]`.
- **Contract tests.** operator-framework FW-3 … FW-10, FW-16; majority-vote VT-5.

## K5 Operator resolution — combine endpoint → operator registry, dependency (in-process)

- **Layering rule.** `combine/endpoint.py`, `combine/registry.py`, `combine/spec.py`, and
  `combine/evidence.py` import no module under `combine/operators/`. Only `combine/builtins.py`
  imports plugins, and `world/factory.py` passes the built registry in. `combine/` is a shared leaf
  and does not import `world` `[proposed]`, under the rule at
  `[existing .claude/scripts/check_layering.py:94]`.
- **Enforcement.** Add a `COMBINE_CORE` rule to `check_layering.py`, with synthetic-tree fixtures
  that copy `test_layering_world.py`
  `[existing apps/screamingface-engine/tests/unit/test_layering_world.py]`.
- **Contract tests.** operator-framework FW-13.

## K6 Evidence record — combine endpoint → operation-call recorder → attribution, data (task-local)

- **Shape.** `OperationCall(path="/ensemble/combine/v1", params=(("binding","synthesis_N"),), output, finish_reason="stop", accounting=None, combine=CombineEvidence)`
  `[proposed]`, recorded into the active `capture_operation_calls` scope
  `[existing apps/screamingface-engine/src/screamingface_engine/operation_calls.py]`.
- **Policies.** The last call wins for each fingerprint, which is the existing rule
  `[existing apps/screamingface-engine/src/screamingface_engine/benchmarks/operation_outputs.py]`.
  The `binding` param makes the fingerprints unique.
- **Failure behavior.** No record on a failure (EV-E1). An ambiguous fingerprint gives null
  evidence, never a guess.
- **Contract tests.** combine-evidence EV-3, EV-4, EV-6, EV-10.

## K7 Evidence on the wire — Engine → SDK, async (run event stream → WS → Report)

- **Shape.** `OperationOutput.combine: CombineEvidence | None`, left out when null. See
  [erd.md](erd.md) §5 for `screamingface.combine-evidence.v1`.
- **Policies.** It goes with the existing per-case envelope. There is no new event type and no new
  subject `[proposed]`. Delivery and ordering are the same as the case envelope today.
- **Failure behavior.** The SDK decodes strictly. An unknown key or schema is an error. Old SDKs
  never see the field, because they cannot compile reducers `[implied]`.
- **Contract tests.** combine-evidence EV-1, EV-5, EV-7, EV-8, EV-12.

## K8 Judge and writer calls — url4 executor → model route → aigateway, sync, existing

- **Shape.** Ordinary model calls with bindings `judge_N` and `writer_N`. The judge intent is the
  versioned template `judge-template@1` plus the rubric `[proposed]`.
- **Policies.** Existing retry and timeout behavior of the connector
  `[existing apps/screamingface-engine/src/screamingface_engine/world/connector.py:616]`. The
  calls are cached by the gateway like any model call. They are answering calls, so the run seed
  applies when the call sets no seed `[existing apps/screamingface-engine/src/screamingface_engine/world/request_parameters.py:86]`.
- **Failure behavior.** Existing model error codes (`provider_refusal`, `aigateway_*`). A reply
  that cannot be parsed fails in K4 with `judge_reply_invalid`.
- **Contract tests.** judge-pick JG-6, JG-9, JG-10; pick-and-merge PM-7, PM-8.

## K9 Sample members — SDK → model route → aigateway cache, existing

- **Shape.** `Model(params={"seed": "<i>"})`. The call seed wins over the run seed, and the gateway
  cache key includes it `[existing apps/aigateway/src/aigateway/core/request_cache/global_keys.py:128]`.
- **Policies.** Allowed only for seed-capable models `[stated ans:Q13]`.
- **Failure behavior.** A gateway rejection → `model_parameter_invalid` (existing code).
- **Contract tests.** samples SM-1, SM-4, SM-9.
