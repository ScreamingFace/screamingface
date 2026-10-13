# Contracts: E4b combine extensions

One section per connection that E4b changes. The connections that E4b does not change (url4 →
gateway, gateway → provider) keep their E4a contracts.
See `docs/spec/2026-10-02-e4a-gap-closure/contracts.md`.

## C1 Combine call — url4 node → `/ensemble/combine/v1`, sync

- **Shape.** No change to the call form:
  `synthesis_N:0.0:/ensemble/combine/v1?binding=synthesis_N&q=({input, outputs|panel, signals?, sources?})!'<spec>'`.
  [existing ET/data/combine_contract/filter_pipeline_candidate.url4] The spec may now carry:
  ```json
  {"schema": "screamingface.combine-spec.v1",
   "reducer": "mean",
   "members": ["member_1", "member_2"],
   "extract": {"op": "json_field@1", "args": {"path": "answer"}},
   "normalize": {"op": "numeric@1", "args": {}},
   "reduce": {"op": "weighted_mean@1", "args": {}},
   "select": {"op": "value@1", "args": {}},
   "weights": {"signal": "field:confidence"}}
  ```
  (The shape follows `ET/data/combine_contract/reducer_specs.json`.) It may also carry
  `weighted_median@1`, and `select.args.output` on `by_field@1` and `best_holder@1`.
  [stated ans:Q1] [stated ans:Q9]
- **Policies.** Pure and deterministic. The same spec and context always give the same bytes. No
  retry inside the call. [existing E/combine/ports.py:3]
- **Failure behavior.** Callee: a bad spec gives `combine_spec_invalid` (permanent). An empty result
  gives an abstain (`no_votes`, `cut_not_met`, `output_missing`), which is not a failure. Caller: the
  url4 node passes the failure or the abstain up unchanged. No new failure code (CS-D2).
- **Contract tests.** MN#7, MN#9, WM#9, WM#12, PO#11, PO#13, CS#3–5.

## C2 Selection envelope — combine call → next Pipeline stage, sync (url4 edge)

- **Shape.** The output text of `top_k@1` and `kept@1`:
  ```json
  {"input": "<the combine context input, verbatim>",
   "selected": [{"id": "member_2", "text": "<original text>"}]}
  ```
  Canonical JSON: sorted keys, no spaces, `ensure_ascii=False`. `join@1` and `all@1` are unchanged.
  [stated ans:Q7] [stated ans:Q13]
- **Policies.** The edge is `($synthesis_N)`, and the bytes are unchanged (SI-4). The connector puts
  the text into the user message as it is. [existing E/world/connector.py:1475-1483]
- **Failure behavior.** An abstained selection makes no envelope. The Case abstains before the
  next stage runs. [existing E/combine/endpoint.py:280-303] An envelope over the 8 MiB result cap
  fails the call like any oversized result. The input is never truncated. [existing E/combine/endpoint.py:97,475]
- **Contract tests.** SI#3, SI#4, SI#7, SI#8, SI#11, RC#1–3.

## C3 Judge call — combine compile → judge model, sync

- **Shape.** The system prompt's first line is
  `judge-template@1 returns=scores[ input=panel][ order=min]`. With `order=min`, the body says "A
  lower number means a better answer". The reply is one JSON object
  `{"member_1": <finite number>, …}`. [stated ans:Q11] [existing S/judge.py:37-69]
- **Policies.** Transport errors retry as today. A bad reply is not retried. [existing packages/screamingface/README.md:440-446]
- **Failure behavior.** `judge_reply_invalid` (permanent) for a reply that is not strict scores.
  [existing E/combine/ports.py:121-125]
- **Contract tests.** JO#3, JO#4, JO#12, FJ#2, FJ#8.

## C4 Operator catalog — SDK → `GET /v1/operators`, sync

- **Shape.** A list of `{id, stage, …}`. It adds `mean@1`, `weighted_mean@1` and `weighted_median@1`.
  [existing E/combine/registry.py:1-10]
- **Policies.** The SDK checks the pinned ids before a run. [existing S/_evaluation/operators.py:47-67]
- **Failure behavior.** A missing id is refused before any model call, and the error names the ids
  (CS-E1).
- **Contract tests.** CS#1, CS#2, CS#6.

## C5 Dependency — SDK vocabulary ↔ engine vocabulary

- **Layering rule.** The SDK lists (`FLOW_OPERATOR_IDS`, `REDUCER_NAMES`, `AbstainReason`) equal the
  engine lists. The engine never imports the SDK. [existing ET/test_sdk_flow_catalog_fixture.py:37]
- **Enforcement.** `test_sdk_flow_catalog_names_exactly_the_builtins`, the failure-code conformance
  test, and the frozen v1 schema snapshots. [existing ST/unit/test_failure_code_conformance.py:70-86]
  [existing ET/test_wire_schema_freeze.py:29-45]
- **Contract tests.** CS#2–5, CS#7–8, CS#11.
