# Contracts: E4b part 2 — evidence completeness

One section per connection that part 2 changes. The connections that part 2 does not change (url4
→ gateway, gateway → provider, the selection envelope of part 1) keep their contracts. See
`docs/spec/2026-10-13-e4b-combine-extensions/contracts.md` and
`docs/spec/2026-10-02-e4a-gap-closure/contracts.md`.

## C1 Combine spec — SDK compile → `/ensemble/combine/v1` intent, sync

- **Shape.** The spec of a judge step gets one optional key. Keys are sorted (canonical JSON).
  [existing S/_evaluation/combine_spec.py:63-73]
  ```json
  {"schema": "screamingface.combine-spec.v1",
   "reducer": "rank",
   "judge_model": "<the route of the judge call>",
   "members": ["member_1", "member_2", "member_3"],
   "extract": null, "normalize": null,
   "reduce": {"op": "scores@1", "args": {"source": "judge"}},
   "select": {"op": "top_k@1", "args": {"k": 2}},
   "weights": null}
  ```
  The shape of the other keys does not change. A spec with no judge has no `judge_model` key.
  [stated ans:Q2] The other keys are those of `ET/data/combine_contract/recipe_s10.url4` today.
- **Policies.** Pure and deterministic. The key is display data: the engine never routes, calls or
  logs by it. [proposed]
- **Failure behavior.** Callee: `judge_model` on a step that reads no judge, or a bad value, gives
  `combine_spec_invalid` (permanent). A judge spec without the key runs as before. Caller: no
  change. [proposed]
- **Contract tests.** JM#2–8, JM#10.

## C2 Combine evidence — combine call → operation-call record → Case result, sync

- **Shape.** `screamingface.combine-evidence.v1`, with these additive edits:
  ```json
  {"members": [
     {"member_id": "member_3", "raw": "B", "value": "B",
      "status": "excluded", "reason": "no_weight",
      "signals": {"field:confidence": null}, "weight": null, "score": null},
     {"member_id": "member_1", "...": "...", "score": 0.03, "rank": 4}],
   "signal": {"key": "cost_usd", "order": "min"},
   "cut": {"k": 2, "order": "min"},
   "judge_model": "<route>"}
  ```
  `rank`, `cut` and `judge_model` are absent when not set. `"excluded"`, `"no_signal"` and
  `"no_weight"` are new enum values. [stated ans:Q1] [stated ans:Q2] [stated ans:Q3]
- **Policies.** The field order of each record stays pinned; each new key goes after its nearest
  neighbor (ES §4). The evidence of a step with no new value keeps its v1 bytes. [proposed]
- **Failure behavior.** A record that breaks AR-I1..I4 or CE-I1..I3 is a plugin bug: the engine
  raises and records nothing, as today. [existing E/world/combine.py:15-17]
- **Contract tests.** ES#1–9, EX#3–17, RK#2–12, JM#5.

## C3 Case result — engine → SDK decoder, sync (results JSON)

- **Shape.** The evidence of C2, inside each Case operation's `combine` key.
  [existing E/benchmarks/contract.py:353-363]
- **Policies.** The SDK decoder checks exact key sets. Part 2 adds `rank` as an optional member key,
  and `cut` and `judge_model` as optional evidence keys, next to `mean`.
  [existing S/_evaluation/combine_evidence.py:60-63,80]
- **Failure behavior.** An SDK from before part 2 refuses an evidence with a new key or an
  `"excluded"` row. The engine and the SDK ship together. [implied]
- **Contract tests.** ES#5, ES#10–11 (the SDK decodes every case of `evidence_cases.json`).

## C4 Case view — SDK evidence → `sf.Answer` and the trace, in process

- **Shape.** `case.answers()` makes one `sf.Answer` per evidence row, with the row's status and
  reason. An excluded row gives `sf.Answer(status="excluded", reason="no_signal" | "no_weight",
  value=<its value>)`. The trace "extract" entry copies the same status and reason.
  [existing S/_case_views.py:37-55,137-150] [stated ans:Q3]
- **Policies.** `answer.v1` adds the words; its field set does not change. [proposed]
- **Failure behavior.** None new: the values are checked at decode time (C3).
- **Contract tests.** ES#12–14, EX#18.

## C5 Layering — dependency

- `E/combine/evidence.py` imports only pydantic and `combine.ports` (unchanged rule).
  Enforcement: the module docstring rule and the engine layering gate.
  [existing E/combine/evidence.py:10-12]
- The operators do not change and do not import the endpoint. The exclusion and the rank are read
  by the endpoint through descriptor hooks, as `signal_read` and `envelope` are.
  [existing E/combine/ports.py:355-384]
