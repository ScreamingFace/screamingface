# PRD: Answer record (component)

**Source:** PRD "Core data model", criterion A1 · ans:Q2, ans:Q8 · **Priority:** P1 (every other
gap PRD reads it)
**Lifecycle:** existing (characterize + delta) — the member reading and the evidence row exist
**Owner:** Ionesio (E4a)

Paths: see [erd.md](../erd.md) (`E/`, `EI/`, `S/`, `ET/`, `ST/`).

## 1. Summary and the flows it serves

The Answer is the one record for "what a member, or a combine step, answered". It has
`member_id`, `text`, `value`, `status` (`answered` | `abstain` | `fail`), `reason`, and `signals`
([erd.md §2](../erd.md#2-answer-screamingfaceanswerv1--new-sdk-record)).

Flows that use it: [abstain](abstain.md), [signal-reduce](signal-reduce.md),
[filter](filter.md), [grader-parity](grader-parity.md), [report-trace](report-trace.md). The
[signals](signals.md) component fills `Answer.signals`.

## 2. Background and constraints

- "Every member returns an `Answer`; every block consumes and produces `Answer[]`. A string never
  crosses a block boundary." `[stated prompt]`
- "Typed record, text wire": the Answer is a versioned record on the combine input, on the
  evidence and on the SDK Report. url4 stage hand-offs stay text. No url4 change. `[stated ans:Q2]`
- "A parse failure is data, not an exception." `[stated prompt]`
- The fold edits unreleased v1 records in place `[stated ans:Q8]`.

### 2.1 Current behavior

- `MemberReading(member, raw, value, status, weight)`; `status` is a `ReadingStatus`
  (`voted`, `empty`, `not_numeric`, `not_json`, `field_missing`, `too_large`)
  `[existing E/combine/ports.py:40]` `[existing E/combine/ports.py:122]`.
- `CombineInput.voters` keeps readings with status `voted` `[existing E/combine/ports.py:150]`.
- The evidence row is `MemberReadingRecord(member, raw, value, status, weight, score)`
  `[existing E/combine/evidence.py:33]`; the SDK twin is `CombineMemberReading`
  `[existing S/combine_evidence.py:35]`.
- The SDK Report has no Answer. Member text is on `CaseOperation.output`
  `[existing S/case_result.py:264]`. `CaseResult` has no map from a member to its operation; the
  combine operation's Report entry lists its member operation ids in `depends_on`, in author order,
  then its judge/writer ids `[existing S/operation.py:16]`.

**Delta.**
1. Engine core: `MemberReading` becomes `Answer` (in-process): adds `reason` and `signals`;
   `status` becomes the PRD status (map in [erd.md §2.1](../erd.md#21-status-and-reason)).
2. Engine core: a reduce step returns a computed `result` Answer; the evidence gets `result` and
   `dropped` ([erd.md §3](../erd.md#3-changes-to-combineevidence-screamingfacecombine-evidencev1-edited-in-place)).
3. SDK: `sf.Answer` (frozen dataclass) and `CaseResult.answers(operation_id=None)`, which returns
   the member Answers plus the computed Answer of each combine operation. `text` is joined through
   `depends_on[k-1]` (erd §2.2); `None` when that operation is not attributed.

## 3. Scenarios and acceptance criteria

### 3.1 Happy path

- **AR-1** Given a Vote over 3 members that reply `"… 42"`, `"… 42"`, `"… 41"`, when the Case
  runs, then `case.answers()` returns 3 member Answers with `status="answered"`, values
  `"42"`, `"42"`, `"41"`, and a computed Answer with `member_id="member_1"`, `value="42"`,
  `status="answered"`. `[stated prompt]`
- **AR-2** Given the same Case, then each member Answer `text` equals that member's
  `CaseOperation.output` byte for byte. `[stated prompt]` ("The original output, untouched")
- **AR-3** Given a Concat or a Merge (compute mode), then the computed Answer has
  `member_id=None` and `value` = the built text's canonical value. `[stated prompt]`

### 3.2 Error paths

- **AR-E1** Given a member that replies `"no idea"` under `last_number@1`, then its Answer has
  `status="fail"`, `reason="empty"`, `value=None`, and no exception rises. `[stated prompt]`
- **AR-E2** Given a member output over the 1 MiB read cap, then `status="fail"`,
  `reason="too_large"`. `[existing E/combine/ports.py:40]`

### 3.3 Derived scenarios (risk-ordered)

- **AR-D1** Status map is total `[proposed]` (H×M): every old `ReadingStatus` maps to one
  (`status`, `reason`) pair per erd §2.1; an unknown status from a plugin is a `RuntimeError`
  (plugin bug), not a silent default.
- **AR-D2** Invariants I-A1, I-A2 hold for every golden case `[proposed]` (H×M): a plugin that
  returns `answered` with `value=None` fails the core's check.
- **AR-D3** A member Answer is never `abstain` (I-A3) `[proposed]` (M×L).
- **AR-D4** Nested member `[implied]` (M×M): a member that is a Pipeline gets `text` from the
  operation that `depends_on[k-1]` names (the Pipeline's final operation), also inside
  `Pipeline([Fusion(Vote), Model])`.
- **AR-D5** Evidence decoded without the operations list `[proposed]` (M×L): when a Case has no
  `operations` (for example a CorrectiveLoop Case, EV-10), `case.answers()` returns `()`, not an
  error.
- **AR-D6** `to_dict()` round trip `[proposed]` (M×M): `sf.Answer.from_dict(a.to_dict()) == a`
  for every Answer in the shared evidence fixture.
- **AR-D7** Order `[proposed]` (M×L): member Answers come in author order, then the computed
  Answer; never dict order.
- **AR-D8** Concurrency: N/A — Answers are immutable values built once per Case.
- **AR-D9** Ambiguous attribution `[existing E/benchmarks/operation_outputs.py:83]` (M×M): when two
  member calls share a fingerprint **and** their outputs differ, the engine leaves them unattributed
  and `text is None`; the Answer's other fields stay. When the outputs are equal, `text` is set.

## 4. Non-functional requirements

- The Answer adds no model call and no network call `[implied]`.
- Evidence size: an Answer row adds `reason` (≤ 16 bytes) and `signals` (empty unless the spec
  reads a signal, I-S3) `[proposed]`. No `text` in evidence (I-E1).
- `case.answers()` is O(members) per combine operation, computed lazily and cached on the
  frozen CaseResult `[proposed]`.

## 5. Out of scope

- A runtime `Answer[]` between url4 nodes `[stated ans:Q2]`.
- The PRD's key-overwrite suffix rule (E4b) `[stated prompt]`.
- Answers for CorrectiveLoop members (their operations are not lifted, U4 follow-up).

## 6. Open questions

None.

## 7. TDD plan

Core-out: the engine core record first, then the evidence wire, then the SDK join.

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| 1 | CHAR: today's evidence for a 3-member vote has `members[].status == "voted"` rows (pins the old shape before the delta; delete with the delta commit per the fold rule) | unit | [existing E/combine/evidence.py:33] | — | passes on today's code |
| 2 | `every_reading_status_maps_to_one_answer_status_and_reason` | unit | AR-D1 | H×M | a total `dict` from the old literal to `(status, reason)` in `ports.py` |
| 3 | `answered_answer_without_value_is_rejected_by_core` | unit | AR-D2 | H×M | core check after normalize; raise `RuntimeError` |
| 4 | `unparseable_member_is_fail_with_reason_not_exception` | unit | AR-E1 | H×H | `rejected("empty")` → `Answer(status="fail", reason="empty")` |
| 5 | `oversized_member_is_fail_too_large` | unit | AR-E2 | M×M | existing cap path, new fields |
| 6 | `vote_result_is_computed_answer_naming_the_winner` | unit | AR-1 | H×H | `Reduction` → `result` Answer in `endpoint.py` |
| 7 | `compute_mode_result_has_no_member_id` | unit | AR-3 | M×M | `result.member_id=None` when `built` |
| 8 | `evidence_wire_carries_member_id_status_reason_signals_and_result` | unit | erd §3 | H×H | `evidence.py` records; regenerate the shared fixture |
| 9 | `sdk_decodes_answer_rows_and_result_from_shared_fixture` | unit | I-E5 | H×M | `S/combine_evidence.py` |
| 10 | `case_answers_join_text_through_depends_on` | integration | AR-2 | H×M | `CaseResult.answers()` reads `depends_on[k-1]` |
| 11 | `nested_pipeline_member_text_is_its_final_operation_output` | integration | AR-D4 | M×M | same join, inside `Pipeline([Fusion(Vote), Model])` |
| 12 | `case_without_operations_has_no_answers` | unit | AR-D5 | M×L | return `()` |
| 13 | `answer_round_trips_through_to_dict` | unit (every fixture entry) | AR-D6 | M×M | `to_dict`/`from_dict` |
| 14 | `answers_are_in_author_order_then_result` | unit | AR-D7 | M×L | build from evidence order |
| 15 | `member_answer_is_never_abstain` | unit | AR-D3 | M×L | core check |
| — | AR-D8 is N/A (Answers are immutable values built once per Case) | — | — | — | — |
| 16 | `ambiguous_attribution_gives_none_text` | unit | AR-D9 | M×M | — |
