# Contracts: E4b part 2 — evidence completeness

One section per connection that part 2 changes. The connections that part 2 does not change keep
their contracts: url4 → gateway, gateway → provider, the selection envelope of part 1, and the
combine spec (SDK compile → `/ensemble/combine/v1` intent), which keeps its bytes for every recipe,
judge recipes included. [stated ans:Q4] See
`docs/spec/2026-10-13-e4b-combine-extensions/contracts.md` and
`docs/spec/2026-10-02-e4a-gap-closure/contracts.md`.

## C1 Combine evidence — combine call → operation-call record → Case result, sync

- **Shape.** `screamingface.combine-evidence.v1`, with these additive edits (the key order of each
  record is its pinned field order, not sorted):
  ```json
  {"members": [
     {"member_id": "member_1", "raw": null, "value": null, "status": "answered", "reason": null,
      "signals": {"cost_usd": 0.03}, "weight": null, "score": 0.03, "rank": 3},
     {"member_id": "member_3", "raw": null, "value": null,
      "status": "excluded", "reason": "no_signal",
      "signals": {"cost_usd": null}, "weight": null, "score": null}],
   "signal": {"key": "cost_usd", "order": "min"},
   "cut": {"k": 2, "order": "min"}}
  ```
  (member_2 and member_4, with ranks 1 and 2, are not shown.) `rank` and `cut` are absent when
  not set. `"excluded"`, `"no_signal"` and `"no_weight"` are new
  enum values. [stated prompt] [stated ans:Q3]
- **Policies.** The field order of each record stays pinned; each new key goes after its nearest
  neighbor (`rank` after `score`, `cut` after `signal`). The evidence of a step with no new value
  keeps its v1 bytes. [proposed]
- **Failure behavior.** A record that breaks AR-I1..I5 or CE-I1..I3 is a plugin bug: the engine
  raises and records nothing, as today. [existing E/world/combine.py:15-17]
- **Contract tests.** ES#1–9, EX#3–17, RK#2–12.

## C2 Case result — engine → SDK decoder, sync (results JSON)

- **Shape.** The evidence of C1, inside each Case operation's `combine` key.
  [existing E/benchmarks/contract.py:353-363]
- **Policies.** The SDK decoder checks exact key sets. Part 2 adds `rank` as an optional member key
  and `cut` as an optional evidence key, next to `mean`.
  [existing S/_evaluation/combine_evidence.py:60-63,80]
- **Failure behavior.** An SDK from before part 2 refuses an evidence with a new key or an
  `"excluded"` row. The engine and the SDK ship together. [implied]
- **Contract tests.** ES#5, ES#8, ES#10–11 (the SDK decodes every case of `evidence_cases.json`).

## C3 Case view — SDK evidence and graph → `sf.Answer` and the trace, in process

- **Shape.**
  - `case.answers()` makes one `sf.Answer` per evidence row. An excluded row gives
    `sf.Answer(status="excluded", reason="no_signal" | "no_weight", value=<its value>)`. The trace
    `extract` entry copies the same status and reason. [stated ans:Q3]
    [existing S/_case_views.py:37-55,137-150]
  - The trace `reduce` entry gets `judge_operation_id` and `judge_model`. The SDK finds the one
    graph dependency of kind `"judge"` of the combine operation, and reads that operation's
    `accounting.request_model`. [stated ans:Q4] [existing S/_case_views.py:68-72,180-200]
- **Policies.** `answer.v1` adds words; its field set does not change. `report-trace.v1` adds the
  two keys to the `reduce` kind. Both are owner-approved snapshot edits. [proposed]
- **Failure behavior.** No graph, no unique judge dependency, or no accounting on the judge call:
  the keys are null. The view never guesses and never raises. [proposed]
- **Contract tests.** ES#12–14, EX#18, JM#3–12.

## C4 Layering — dependency

- `E/combine/evidence.py` imports only pydantic and `combine.ports` (unchanged rule). The cut type
  follows it: `Cut` in `ports.py`, `CutRecord` in `evidence.py`. Enforcement: the module docstring
  rule and the engine layering gate. [existing E/combine/evidence.py:10-12]
- The operators do not change and do not import the endpoint. The exclusion and the rank are read
  by the endpoint through descriptor flags and hooks, as `signal_read` and `envelope` are.
  [existing E/combine/ports.py:355-384]
- The judge link is SDK-only: the engine never sees the judge route. [stated ans:Q4]
