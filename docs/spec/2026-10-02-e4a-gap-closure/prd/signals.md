# PRD: Signals on member Answers (component)

**Source:** PRD "Signals" and the Reduce ops `weighted` / `argmax` / `filter`, criterion A3 ·
ans:Q4, ans:Q9 · **Priority:** P1
**Lifecycle:** existing (characterize + delta) — accounting and judge readings exist; no signal map
**Owner:** Ionesio (E4a)

Paths: see [erd.md](../erd.md) (`E/`, `EI/`, `S/`, `ET/`, `ST/`).

## 1. Summary and the flows it serves

A signal is a named number on a member Answer (`Answer.signals[key]`). A reducer reads it through
`sf.signal("<key>")`. E4a has three source kinds: per-call accounting (`cost_usd`, `latency_ms`,
`tokens_in`, `tokens_out`), the member's JSON fields (`field:<path>`), and the judge scores of the
same reducer (`score:judge`). `logprob` and the other declared signals come with E4b through the
same seam `[stated ans:Q4]`.

Flows that use it: [signal-reduce](signal-reduce.md), [filter](filter.md),
[report-trace](report-trace.md).

## 2. Background and constraints

- "Seam + E4a sources: … member JSON fields, judge scores, and per-call accounting (cost_usd,
  latency_ms, tokens). logprob etc. plug in with E4b." `[stated ans:Q4]`
- "On a hit, read the cost/latency/tokens the gateway stored with the cache entry … Replays stay
  identical; an unpriced hit gives 'missing'." `[stated ans:Q9]`
- "`missing` is a value, not an absence." `[stated prompt]`
- The combine core is pure: no I/O, no url4, no plugin import
  `[existing .claude/scripts/check_layering.py:102]`.

### 2.1 Current behavior

- A cache hit records `cost_usd="0"`, 0 tokens, 0 latency, 0 attempts
  `[existing E/world/accounting.py:431]`.
- The gateway's cache reference carries the original `usage`, `direct_cost` and `latency`
  `[existing apps/aigateway/src/aigateway/plugins/taxonomy/usage_accounting.schema.json:246]`; the
  engine already prices the stored cost for "saved cost" `[existing E/world/accounting.py:235]`.
- The per-Case recorder is a `ContextVar`, reachable in the combine handler; member calls are
  recorded before the combine node `[existing E/operation_calls.py:63]` `[existing E/world/combine.py:45]`.
- Member **model** calls carry no `binding` param `[existing S/_operation_bindings.py:17]`; the
  engine matches calls by `(path, params)` fingerprint with a one-claimant rule
  `[existing E/benchmarks/operation_outputs.py:83]`.
- A url4 struct cannot hold a list `[existing packages/url4/src/url4/core/builders.py:125]`.
- The field-path walk is in a plugin `[existing E/combine/operators/extract.py:43]`; `parse_scores`
  is in a plugin `[existing E/combine/operators/judge.py:80]`.

**Delta.**
1. Engine world: `SignalAccounting` on `OperationCall` = the final successful attempt's values on a
   miss, the cache reference's values on a hit ([erd.md §4.3](../erd.md)). Computed per round in
   `_observed_round_trip` `[existing E/world/connector.py:170]` and combined at both
   `record_operation_call` sites. `OperationAccounting` does not change.
2. SDK compile: when the spec reads an accounting signal, add `context.sources` =
   `{member_k: {call_key: {"path": …, "params": "<canonical k=v&… string>"}}}` for every model call
   in the member's subtree ([erd.md §6](../erd.md)). The SDK counts fingerprint claimants over the
   **whole compiled expression** and leaves out any fingerprint claimed twice (I-C2). Otherwise no
   `sources` (I-C4).
3. Adapter (`E/world/combine.py`): match each `sources` entry to **exactly one** recorded call with
   the same `(path, params)` fingerprint as `attribute_operation_outputs` (I-C2b); sum per member;
   absence is contagious. A new accessor in `E/operation_calls.py` returns the active recorder's calls. Pass `CombineInput.accounting: Mapping[member_id, Mapping[key, float | None]]`.
4. Core: move the field-path walk and `parse_scores` into `combine/ports.py` (plugins import them
   from there). Before reduce, the core computes **only the keys the spec reads** and writes them
   into each Answer row (I-S3).
5. SDK: `sf.signal(key)` validates I-S1 with the same `_PATH` pattern as the engine.

## 3. Scenarios and acceptance criteria

### 3.1 Happy path

- **SG-1** Given 3 member Models (cache misses) and a reducer that reads `cost_usd`, then each member
  Answer has `signals["cost_usd"]` = its recorded live cost. `[stated ans:Q4]`
- **SG-2** Given members that reply `{"answer": "B", "confidence": 0.8}` and a reducer that reads
  `field:confidence`, then each Answer has `signals["field:confidence"] == 0.8`. `[stated ans:Q4]`
- **SG-3** Given a reducer with a judge (`returns="scores"`) that reads `score:judge`, then each
  member Answer carries its judge score. `[stated ans:Q4]`

### 3.2 Error paths

- **SG-E1** Given a provider that reports no cost, then `signals["cost_usd"] is None` and the run
  does not fail. `[stated prompt]`
- **SG-E2** Given `sf.signal("logprob_mean")`, then `ValueError` at construction lists the E4a keys
  and says `logprob_mean` comes with E4b. `[stated ans:Q4]`

### 3.3 Derived scenarios (risk-ordered)

- **SG-D1** Cached replay `[stated ans:Q9]` (H×H): the same url4 served from cache gives the **same**
  `cost_usd`, `latency_ms`, `tokens_in`, `tokens_out` as the first run (read from the cache
  reference), so an argmax over cost picks the same member.
- **SG-D2** Unpriced hit `[stated ans:Q9]` (M×M): a hit whose stored cost unit the engine cannot
  price gives `cost_usd = None`.
- **SG-D3** Nested member `[proposed]` (M×M): a 2-stage Pipeline member sums both model calls;
  combine, judge and writer calls inside it are left out.
- **SG-D4** Duplicate fingerprints `[proposed]` (H×M): two model calls with the same `(path, params)`
  anywhere in the candidate — duplicate members, or one model reused in two nested Fusions — are left
  out of `sources` by the SDK, so those members get `None` accounting signals on every run (no race
  with calls recorded by other branches). `samples()` members differ by `seed`, so they match
  one-to-one `[existing S/_samples.py:21]`.
- **SG-D5** No match or no recorder `[proposed]` (M×L): a fingerprint with zero or several recorded
  calls → `None` and one warning; no active recorder (a direct `/ensemble/combine` call) → every
  accounting signal `None` and one warning; never an error.
- **SG-D14** Retry before success `[proposed]` (H×M): a call that succeeds on its second attempt gives
  the final attempt's cost and tokens, which equal the cache reference on replay.
- **SG-D15** Param keys with a dot `[existing packages/url4/src/url4/core/_annotations.py:63]` (M×L):
  params travel as one canonical string, so a user param `x.y` compiles.
- **SG-D6** Malformed `sources` `[proposed]` (H×L): keys that differ from `outputs` keys, or a
  missing `path` → `combine_spec_invalid` before any operator runs.
- **SG-D7** No accounting read `[proposed]` (H×M): a spec that reads no accounting signal compiles
  without `sources`; every existing reducer golden and engine fixture stays byte-identical (I-C4).
- **SG-D8** Non-finite values `[proposed]` (M×L): `NaN`/`inf` from a field → `None`; a bool → 1.0/0.0.
- **SG-D9** Determinism `[existing ET/test_combine_determinism.py:73]` (H×M): same inputs and
  accounting → one evidence across 100 in-process runs and 20 processes with different hash seeds.
- **SG-D10** Read set only (I-S3) `[proposed]` (L×M): a reducer that reads no signal writes
  `signals: {}`.
- **SG-D11** Trust boundary `[proposed]` (M×L): member JSON is untrusted; the path walk keeps its
  depth cap 64 `[existing E/combine/ports.py:44]`; no eval.
- **SG-D12** Concurrency `[implied]` (L×L): the recorder is task-local; parallel Cases never see each
  other's calls.
- **SG-D13** Live latency `[implied]` (L×M): a fresh live rerun (no cache) can give a different
  `latency_ms`; only a cached replay is identical. The README says so.

## 4. Non-functional requirements

- Adapter cost: O(model calls in the Case) per combine call, one fingerprint index built once
  `[proposed]`.
- No new model call and no gateway change `[implied]`.
- COMBINE_CORE layering gate stays green `[existing .claude/scripts/check_layering.py:102]`.

## 5. Out of scope

- E4b declared signals and produced-by-block signals on Answers; the suffix rule.

## 6. Open questions

None.

## 7. TDD plan

Outside-in: the original-value rule first (it carries the replay risk), then the wire, the adapter,
the core.

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| 1 | CHAR: a cache hit has `OperationAccounting.usage.cost_usd == "0"` (stays true) | unit | [existing E/world/accounting.py:431] | — | passes today |
| 2 | `signal_accounting_reads_cache_reference_on_hit` | unit | SG-D1 | H×H | new pure function next to `avoided_usd_from_aigw` |
| 3 | `unpriced_hit_gives_none_cost` | unit | SG-D2 | M×M | reuse `_saved_cost_usd` |
| 4 | `signal_key_outside_e4a_set_is_rejected_at_construction` | unit (SDK) | SG-E2 | M×H | `sf.signal` |
| 5 | `compile_emits_sources_only_when_accounting_signal_is_read` | unit (SDK) | delta 2, SG-D7 | H×H | `candidate.py` walk of model calls |
| 6 | `existing_reducer_goldens_unchanged` | unit (SDK + engine fixtures) | SG-D7 | H×M | no `sources` without accounting keys |
| 7 | `malformed_sources_is_spec_invalid` | unit | SG-D6 | H×L | `spec.py` context parse |
| 8 | `adapter_sums_member_signal_accounting_by_fingerprint` | integration (adapter + recorder) | SG-1, SG-D3 | H×M | reuse the `operation_outputs` fingerprint |
| 9 | `fingerprint_claimed_twice_in_expression_is_left_out_of_sources` | unit (SDK, nested Fusions) | SG-D4 | H×M | expression-wide claimant count at compile |
| 10 | `unmatched_or_unrecorded_source_gives_none_not_error` | integration | SG-D5 | M×L | exactly-one rule; no-recorder path |
| 11 | `missing_cost_is_none_not_error` | unit | SG-E1 | H×M | contagious absence |
| 12 | `field_signal_reads_number_or_bool` | unit | SG-2, SG-D8 | M×M | path walk moved to `ports.py` |
| 13 | `judge_score_signal_per_member` | unit | SG-3 | M×M | `parse_scores` moved to `ports.py` |
| 14 | `only_read_signals_are_written` | unit | SG-D10 | L×M | — |
| 15 | `cached_replay_gives_same_signals_and_tally` | integration | SG-D1 | H×H | — |
| 16 | `signals_are_deterministic_across_hash_seeds` | unit (subprocess) | SG-D9 | H×M | extend determinism inputs |
| 17 | `field_path_keeps_depth_cap` | unit | SG-D11 | M×L | — |
| 18 | `parallel_cases_see_only_their_own_calls` | integration (two tasks) | SG-D12 | L×L | `ContextVar` |
| 19 | `retried_call_signal_equals_cache_reference_on_replay` | integration | SG-D14 | H×M | final successful attempt on a miss |
| 20 | `dotted_param_key_compiles_in_sources` | unit (SDK) | SG-D15 | M×L | canonical params string |
| — | SG-D13 is a README statement, checked in review | — | — | — | — |
