# Contracts — E4a gap closure (OME-1289)

One section per connection that the gap closure adds or changes. Record shapes are in
[erd.md](erd.md); paths use its prefixes. Test numbers are `<prefix>#<n>` (for example `AB#11` =
[abstain](prd/abstain.md) TDD row 11; prefixes AR, SG, BK, AB, RX, GP, SR, FL, FR, RT). Base
contracts K1–K12 are in
[../2026-09-30-e4a-deterministic-combine/contracts.md](../2026-09-30-e4a-deterministic-combine/contracts.md);
this file gives only the deltas (G1–G10).

## G1 Combine call — SDK compile → url4 → engine `/ensemble/combine/v1`, sync, url4

- **Shape.** Intent = canonical `screamingface.combine-spec.v1` (erd §5). Context adds optional
  `sources` (erd §6), present only when the spec reads an accounting signal. Params stay exactly
  `{"binding": "synthesis_N"}`.
- **Policies.** Pure and deterministic; `CombineError` stays permanent `[existing E/world/combine.py:49]`;
  idempotent by construction.
- **Failure behavior.** Callee: bad `sources`, a banned regex, an unknown op → `combine_spec_invalid`
  / `combine_operator_unknown`; the Case fails. No usable value → **no error**: output `""`, evidence
  `result.status="abstain"` (G5). Caller (SDK): validates the same rules at construction, before spend.
- **Contract tests.** SG#5–7, RX#1–3, SR#4–5, FL#3, AB#2, AB#7; the shared evidence fixture (I-E5).

## G2 Signal accounting — engine world → `OperationCall`, in-process

- **Shape.** `SignalAccounting(cost_usd, latency_ms, tokens_in, tokens_out)` per recorded call: live
  values of the final successful attempt on a miss; on a hit,
  `_aigw.usage_accounting.cache.reference.{direct_cost, latency, usage}`
  (erd §4.3) `[existing apps/aigateway/src/aigateway/plugins/taxonomy/usage_accounting.schema.json:246]`.
- **Policies.** Computed per round in `_observed_round_trip` `[existing E/world/connector.py:170]`,
  combined at both `record_operation_call` sites `[existing E/world/connector.py:879]`
  `[existing E/world/connector.py:932]`; never on the wire; `OperationAccounting`
  unchanged (`cost_usd="0"` on a hit stays) `[existing E/world/accounting.py:431]`.
- **Failure behavior.** Malformed, absent or unpriceable reference → `None` per field; never raises
  (like `avoided_usd_from_aigw`).
- **Contract tests.** SG#1–3, SG#15.

## G3 Accounting lookup — `world/combine.py` → per-Case operation recorder, data, in-process

- **Shape.** For each `sources[member_k]` entry, find the recorded `OperationCall` with the same
  `(path, params)` fingerprint, by the one-claimant rule of `attribute_operation_outputs`
  `[existing E/benchmarks/operation_outputs.py:61]`; sum `SignalAccounting` per member, absence
  contagious → `CombineInput.accounting`.
- **Policies.** Read-only; task-local (`ContextVar`) `[existing E/operation_calls.py:63]`; member
  calls resolve before the combine node `[existing E/world/combine.py:45]`.
- **Failure behavior.** Claimants are counted over the whole expression in the SDK; an ambiguous
  fingerprint is not sent (I-C2). In the adapter, zero or several recorded calls for a fingerprint →
  `None` and one warning; no active recorder → every accounting signal `None` and one warning
  (I-C2b). Never raises.
- **Contract tests.** SG#8–11, SG#18.

## G4 Core ↔ operator plugins — dependency

- **Rule.** Plugins import `combine.ports`, the standard library, and sibling plugin pure functions;
  the core imports no plugin; nothing under `combine/` imports url4
  `[existing .claude/scripts/check_layering.py:102]`. Two pure parsers move into `ports.py` (the
  field-path walk and `parse_scores`), so the core can resolve signals. The vendored
  `combine/operators/_inspect_vendor.py` is a sibling module with no `OPERATORS`, stdlib +
  `unicodedata` only, and no `random`/`logging` `[existing .claude/scripts/check_layering.py:118]`.
- **Enforcement.** The COMBINE_CORE check (repo gate) and GP#7.

## G5 Abstain — combine → invocation record → Case-result build → `CaseResult` wire → SDK

- **Shape.** Candidate invocation record: optional `abstained: true` when the expression's final
  node is a combine with `result.status == "abstain"`, set in `[existing E/benchmarks/invocation.py:72]`
  and carried through the invocation decoder `[existing E/benchmarks/contract.py:644]`,
  `CandidateAnswer`, the Case records and `CandidateFields`.
  `CaseResult`: `status="scored"`, the grader's grade with `score` replaced by `0.0` (method, metrics,
  checks kept), optional `abstained: true`; output `""`.
- **Policies.** Graders still run `[stated ans:Q10]`; the score is replaced in one shared hook,
  `BenchmarkAggregation` `[existing E/benchmarks/shared_grading/benchmark_aggregation.py:495]`, which
  every family uses (Inspect too `[existing EI/single_shot.py:175]`). Detection only from
  `result.status` (I-E2 is one-way).
- **Failure behavior.** A grader error on an abstained Case is ignored (its grade is replaced) and
  logged with the Case id. A non-abstained Case is byte-identical (AB-D6).
- **Contract tests.** AB#9–14, AB#17–18, AB#21–22.

## G6 Failure-code vocabulary — engine `DECLARED_FAILURE_CODES` ↔ SDK mirror

- **Change.** Remove `combine_no_votes` from both `[existing E/benchmarks/contract.py:124]`
  `[existing S/_report_primitives.py:90]`; the twin conformance test keeps them equal.
- **Contract tests.** AB#16.

## G7 Evidence wire — engine `OperationOutput.combine` → SDK `CaseOperation.combine`, JSON

- **Shape.** `screamingface.combine-evidence.v1` with Answer rows, `result`, `dropped`, `signal`
  (erd §3); the key is omitted for non-combine operations `[existing E/benchmarks/contract.py:262]`.
- **Policies.** Frozen after the fold: an engine `model_json_schema()` snapshot and the shared fixture
  (RT-D1, I-E5).
- **Failure behavior.** The SDK decoder rejects an unknown `status` or `reason` with an error that
  names the field.
- **Contract tests.** AR#8–9, RT#2–3.

## G8 Benchmark catalog — engine `GET /v1/benchmarks` → SDK catalog client, REST JSON

- **Shape.** Optional `answer_rule = {"extract": {"op","args"}, "normalize": {"op","args"} | null,
  "grader": "<dotted name>@<version>"}`, emitted only when set `[existing E/benchmarks/definition.py:270]`.
- **Policies.** ETag + 304 unchanged `[existing E/rest/benchmarks.py:31]`; the SDK resolves
  `extract="benchmark"` before spend and pins the ops into the url4 `[stated ans:Q12]`.
- **Failure behavior.** No `answer_rule` → `ValueError` before spend (GP-E1). An Engine whose operator
  catalog lacks `inspect_number@1` → `EngineCapabilityError` (GP-E3) `[existing S/_engine/catalog.py:427]`.
- **Contract tests.** GP#8–12, GP#16.

## G9 Operator catalog — engine `GET /v1/operators` → SDK, REST JSON

- **Change.** New ids (`regex@1`, `set@1`, `inspect_number@1`, `inspect_aime@1`,
  `inspect_numeric@1`, `by_signal@1`, `filter@1`, `best_holder@1`, `kept@1`) listed with
  `args_schema`; the ETag changes. The SDK pins each id before spend (the existing check).
- **Contract tests.** RX#10 and the existing catalog tests.

## G10 Fusion rewrite — SDK recipe → url4 text, compile time

- **Shape.** `Pipeline([Fusion(m, Reduce("context")), S, *rest])` → `Pipeline([Fusion(m, S), *rest])`
  (or `Fusion(m, S)` when `rest` is empty and the Pipeline has no name), before compile
  ([fusion-recipe](prd/fusion-recipe.md)).
- **Policies.** No engine change; the goldens are the contract.
- **Contract tests.** FR#1–8, FR#13.
