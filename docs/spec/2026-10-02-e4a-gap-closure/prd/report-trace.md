# PRD: Report trace and the frozen v1 schemas

**Source:** PRD "Budget and Report", criteria A6 and S1 · ans:Q2, ans:Q8, ans:Q13 · **Priority:** P1
**Lifecycle:** existing (characterize + delta) — one evidence object per combine operation exists
**Owner:** Ionesio (E4a)

Paths: see [erd.md](../erd.md). Uses [answer-record](answer-record.md), [signals](signals.md).

## 1. Summary and user story

As a reviewer, I want one ordered trace per Case with an entry per model call, per extract and per
reduce, so that I can check exactly what each block did. I also want the record shapes frozen, so
that the leaderboard (E14) and the client (E3) can depend on them.

## 2. Background and constraints

- "Report is a trace schema every block appends to. One report per run, one entry per block
  execution, in execution order." `[stated prompt]`
- Entry content: Model call (member_id, provider, model, cache hit or miss, cost, latency, tokens,
  status); Extract (rule, raw match, normalized value, or the parse failure); Reduce (op, tally,
  chosen member_ids, the signal read and its values) `[stated prompt]`.
- "Answer, Budget and Report schemas are documented, versioned and frozen for v1." `[stated prompt]`
- "report.v1 stays byte-identical. New `Report.trace_dict()` emits
  `screamingface.report-trace.v1` beside it; E14 pins both files with a submission. No edits to
  main's tests." `[stated ans:Q13]`

### 2.1 Current behavior

- `CaseResult.operations` holds `CaseOperation(operation_id, output, finish_reason, accounting,
  combine)` in list order `[existing S/case_result.py:264]`.
- `Report.to_dict()` emits `screamingface.report.v1`, released in SDK `v0.1.1.post9` and pinned by
  tests on `main` `[existing ST/test_report.py:446]`.
- Combine evidence holds extract and reduce data in one object per combine operation
  `[existing E/combine/evidence.py:69]`. There is no per-Case trace.

**Delta.**
1. SDK `CaseResult.trace() -> tuple[TraceEntry, ...]`, derived from `operations` and evidence
   ([erd.md §8](../erd.md)). No engine change.
2. SDK `Report.trace_dict() -> dict`: `{"schema": "screamingface.report-trace.v1", "candidates":
   [{"candidate": <label>, "cases": [{"case_id", "entries": [...]}]}]}`.
3. `Report.to_dict()` and `report.v1` do not change.
4. Freeze (erd §10): engine `model_json_schema()` snapshots for `combine-spec.v1` and
   `combine-evidence.v1`; SDK field-set snapshots for `answer.v1` and `report-trace.v1`.

## 3. Scenarios and acceptance criteria

### 3.1 Happy path

- **RT-1** Given a Vote over 3 Models, then `case.trace()` is: 3 `model_call` entries (member
  order), 3 `extract` entries (member order), 1 `reduce` entry. `[stated prompt]`
- **RT-2** Each `model_call` entry carries provider, model, cache, cost, latency, tokens and status
  from `OperationAccounting`. `[stated prompt]`
- **RT-3** The `reduce` entry carries op, mode, tally, chosen, signal (key, order) and the result.
  `[stated prompt]`
- **RT-4** Given the same url4 replayed from cache, then the trace is equal except `cache`, and
  `cost_usd`/`latency_ms`/tokens on `model_call` entries (accounting is 0 on a hit; the signal values
  in the `extract`/`reduce` entries stay equal, [signals](signals.md) SG-D1). `[stated prompt]`

### 3.2 Error paths

- **RT-E1** Given a failed Case (no operations), then `trace()` returns `()`, never raises.
  `[proposed]`
- **RT-E2** Given a Case from an Engine without evidence on its combine operation, then the trace
  has `model_call` entries only. `[implied]`

### 3.3 Derived scenarios (risk-ordered)

- **RT-D1** Schema freeze `[stated prompt]` (H×M): a snapshot change with an unchanged schema id fails
  the gate (erd §10). No new test dependency.
- **RT-D2** `report.v1` untouched `[stated ans:Q13]` (H×M): `Report.to_dict()` output is
  byte-identical before and after the change for the stack's reducer fixtures.
- **RT-D3** Nested recipes `[proposed]` (M×M): a Pipeline of two Fusions gives two groups, each in
  operation order.
- **RT-D4** Judge and writer calls (M×M): `model_call` entries with `member_id=None` and their
  binding, before the `reduce` entry.
- **RT-D5** Abstain `[stated ans:Q3]` (M×M): the reduce entry shows `result.status="abstain"`.
- **RT-D6** `cache` value (M×M): the erd §8 rule maps mixed counts (hit / miss / bypass / unknown).
- **RT-D7** Size `[proposed]` (M×L): the trace holds no member text.
- **RT-D8** Closed kinds `[implied]` (L×L): `model_call`, `extract`, `reduce`, `budget` in v1
  (`budget` is defined now with the Budget schema, [budget-schema](budget-schema.md), and has no
  producer in E4a); E4c's `branch` needs `report-trace.v2`.
- **RT-D9** `model_call.member_id` for earlier stages `[proposed]` (M×M): the earlier stages of a
  Pipeline member get that member's id (transitive dependency of `depends_on[k-1]`, erd §8); judge,
  writer and synthesizer calls get `None`.

## 4. Non-functional requirements

- `trace()` is O(operations + members) and pure `[proposed]`.

## 5. Out of scope

- An engine-side trace on the wire; Branch entries and producing Budget entries (E4c).

## 6. Open questions

None.

## 7. TDD plan

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| 1 | CHAR: `Report.to_dict()` bytes for the stack's reducer fixtures | unit | RT-D2 | — | passes today |
| 2 | `frozen_wire_schemas_match_snapshot_unless_id_changes` (engine) | unit | RT-D1 | H×M | `model_json_schema()` snapshots |
| 3 | `sdk_records_match_frozen_field_sets` | unit (SDK) | RT-D1 | H×M | field-set snapshots + fixture decode |
| 4 | `vote_trace_is_model_calls_then_extracts_then_reduce` | unit | RT-1 | H×H | `CaseResult.trace()` |
| 5 | `model_call_entry_carries_accounting` | unit | RT-2 | M×M | — |
| 6 | `reduce_entry_carries_tally_chosen_signal_result` | unit | RT-3 | M×M | — |
| 7 | `trace_dict_emits_report_trace_v1_per_candidate_and_case` | unit | delta 2 | H×M | `Report.trace_dict()` |
| 8 | `report_to_dict_is_byte_identical` | unit | RT-D2 | H×M | compare with row 1 |
| 9 | `failed_case_trace_is_empty` | unit | RT-E1 | M×M | — |
| 10 | `pre_e4a_engine_case_traces_model_calls_only` | unit | RT-E2 | M×M | — |
| 11 | `nested_pipeline_of_fusions_traces_two_groups_in_order` | unit | RT-D3 | M×M | — |
| 12 | `judge_calls_trace_before_reduce` | unit | RT-D4 | M×M | — |
| 13 | `abstained_reduce_entry_shows_abstain_result` | unit | RT-D5 | M×M | — |
| 14 | `cache_value_follows_count_rule` (parametrized) | unit | RT-D6 | M×M | — |
| 15 | `trace_holds_no_member_text` | unit | RT-D7 | M×L | — |
| 16 | `cached_replay_trace_differs_only_in_cache_and_accounting` | integration | RT-4 | M×M | — |
| 17 | `pipeline_member_earlier_stages_carry_member_id` | unit | RT-D9 | M×M | walk `depends_on` |
| — | RT-D8 is pinned by row 3 (closed kind set in the snapshot) | — | — | — | — |
