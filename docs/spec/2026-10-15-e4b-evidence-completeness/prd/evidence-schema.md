# PRD: Evidence schema and vocabulary (component)

**Source:** ans:Q1, ans:Q2, ans:Q3 · **Priority:** P0 (every other PRD writes through it)
**Lifecycle:** existing (characterize + delta)
**Owner:** unassigned
Paths: [erd §2, §3, §4, §7](../erd.md) · serves: [member-exclusion](member-exclusion.md),
[rank-and-cut](rank-and-cut.md), [judge-model](judge-model.md)

## 1. Summary and the flows it serves

This component owns the words and the wire keys that part 2 adds: the record status
`"excluded"`, the reasons `no_signal` and `no_weight`, the member key `rank`, and the evidence keys
`cut` and `judge_model`. It also owns the copy of each word in the SDK, the v1 schema snapshots,
and the SDK decoder. The flow PRDs only produce values. This PRD owns how the values are written,
checked and read.

## 2. Background and constraints

- A member that a rule leaves out gets a new status `"excluded"`, not a new field. Every reader of
  the status learns the third value. This was the user's choice, against the recommendation ("New
  field, status kept"). [stated ans:Q3]
- The evidence records the judge model. [stated ans:Q2]
- The evidence shows the rank and the cut of a top-k step (epic OME-1290 behavior 3: "the report
  shows the score and the rank, including members that were dropped"). [stated ans:Q1]
- Wire edits are additive, in place, with no new schema id.
  [existing docs/spec/2026-10-13-e4b-combine-extensions/00-overview.md:86]

### 2.1 Current behavior

- The engine evidence models are closed (`extra="forbid"`, `strict=True`).
  [existing E/combine/evidence.py:35-38]
- `MemberStatus = Literal["answered", "fail"]`, with the comment "I-A3: a member is never abstain".
  [existing E/combine/ports.py:52]
- `AnswerReason` has ten values; none of them says "no signal" or "no weight".
  [existing E/combine/ports.py:54-66]
- `AnswerRecord` checks: a reason exactly when not answered; no value when failed.
  [existing E/combine/evidence.py:53-59]
- `CombineEvidence.mean` is the one optional key: absent when `None`.
  [existing E/combine/evidence.py:129-131]
- The SDK copies the words in `answer.py` and derives the sets from them.
  [existing S/answer.py:19-41]
- `sf.Answer` allows a value only when `status == "answered"`. [existing S/answer.py:125-142]
- `CombineAnswerRow` checks the same rules as the engine record.
  [existing S/combine_evidence.py:61-75]
- The SDK decoder checks the exact key set of each record. `mean` is the one optional evidence key.
  [existing S/_evaluation/combine_evidence.py:39,60-63,70-80,117-124]
- The case view turns each evidence row into an `sf.Answer`, with the row's status and reason.
  [existing S/_case_views.py:37-55]
- The trace "extract" entries copy each row's status and reason. [existing S/_case_views.py:137-150]
- `ST/data/schemas/screamingface.answer.v1.json` pins the field set and the enums of `sf.Answer`,
  among them `member_status: ["answered", "fail"]`.
  [existing ST/data/schemas/screamingface.answer.v1.json:16-19]

**Delta.**

1. Engine: a new `RecordStatus = Literal["answered", "fail", "excluded"]` and a new
   `ExcludeReason = Literal["no_signal", "no_weight"]` in `E/combine/ports.py`. `MemberStatus`
   and the core `Answer` do not change (I-A3 stays true for the operator input).
2. Engine: `AnswerRecord.status: RecordStatus`, `reason: AnswerReason | ExcludeReason | None`,
   new optional `rank: int | None` (absent when `None`). New validator rules AR-I3 and AR-I4.
3. Engine: `CombineEvidence` gets optional `cut: CutRecord | None` and `judge_model: str | None`,
   both absent when `None`. `CutRecord = {k: int, order: "max" | "min"}`.
4. Engine: `CombineSpec` gets optional `judge_model: str | None` (absent from the spec bytes when
   the SDK has no judge).
5. SDK: `MemberStatus` and `AnswerStatus` add `"excluded"`; `AnswerReason` adds `no_signal` and
   `no_weight`. `sf.Answer`, `CombineAnswerRow` and the decoder follow. New public
   `sf.report.CombineCut`.
6. Snapshots: `combine-evidence.v1.json`, `combine-spec.v1.json`, `answer.v1.json` and the public
   surface snapshot get the new words and keys. These are owner-approved edits (plan §6).

## 3. Scenarios and acceptance criteria

### 3.1 Happy path

- **ES-1** Given an evidence with no excluded member, no top-k step and no judge model, then its
  bytes equal the bytes before part 2. [implied]
- **ES-2** Given an `AnswerRecord` with `status="excluded"`, `reason="no_weight"`, a value and
  `weight=null`, then the record is valid. [stated ans:Q3]
- **ES-3** Given the SDK decodes an evidence with an excluded row, a `rank`, a `cut` and a
  `judge_model`, then `CombineAnswerRow.status == "excluded"`, `.rank` is set, and
  `CombineEvidence.cut` and `.judge_model` are set. [stated ans:Q1] [stated ans:Q2] [stated ans:Q3]
- **ES-4** Given `case.answers()` on that Case, then the excluded member's `sf.Answer` has
  `status="excluded"`, its reason and its value. [stated ans:Q3]

### 3.2 Error paths

- **ES-E1** Given a record with `status="excluded"` and no reason, or with a failure reason such
  as `"empty"`, then the engine model and the SDK row refuse it. [proposed]
- **ES-E2** Given a record with `status="fail"` and the reason `"no_signal"`, then both refuse it:
  an exclude reason goes only with `"excluded"`. [proposed]
- **ES-E3** Given an unknown evidence key next to the new keys, then the SDK decoder still refuses
  it (closed key set). [existing S/_evaluation/combine_evidence.py:80]

### 3.3 Derived scenarios (risk-ordered)

- **ES-D1** (H×M) [implied] Given every case of the engine fixture `evidence_cases.json`, the new
  excluded, rank, cut and judge-model cases among them, then the SDK decoder accepts each one and
  the engine schema `combine-evidence.v1.json` validates each one. This is the cross-side pin: a
  word that one side lacks makes it fail.
  [existing ST/test_evidence_fixture_agreement.py] [existing ST/test_combine_evidence_contract.py]
  The SDK words are also pinned by `ST/test_frozen_record_fields.py:98-106`.
- **ES-D2** (H×M) [implied] Given `rank=0`, a negative rank, a boolean rank, or a rank above the
  member count, then both sides refuse it.
- **ES-D3** (H×L) [implied] Given `cut.k` outside 1..256, a boolean `k`, or an `order` that is not
  `max` or `min`, then both sides refuse it.
- **ES-D4** (M×M) [proposed] Given `judge_model` that is empty, longer than 256 characters, or has
  a control character, then both sides refuse it.
- **ES-D5** (M×M) [implied] Given an excluded member, then `dropped` does not count it, and the
  `dropped` check of both sides still passes. [existing E/combine/evidence.py:146-147]
- **ES-D6** (M×L) [implied] Given a trace of a Case with an excluded member, then the "extract"
  entry shows `status: "excluded"` and its reason. The `report-trace.v1` field set does not change.

## 4. Non-functional requirements

- No new import in `E/combine/evidence.py`: it still imports only pydantic and `combine.ports`.
  [existing E/combine/evidence.py:10-12]
- The wire keys keep the pinned field order; each new key goes after its nearest neighbor
  (`rank` after `score`; `cut` after `signal`; `judge_model` after `cut`). [proposed]
- Every new word has one source per side: the engine Literal and the SDK Literal. The sets derive
  from them. [existing S/answer.py:1-6]

## 5. Out of scope

- A count of excluded members in the evidence. The count is derivable from the rows. [proposed]
- A `cut` for `kept@1` (the filter threshold). [proposed]
- Showing the new values in the report UI (part 4). [stated ans:Q1]

## 6. Open questions

None.

## 7. TDD plan

Order: characterize the v1 bytes, then add each word and key core-out (engine model, SDK model,
decoder, snapshots).

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| 1 | CHAR `evidence_without_new_values_keeps_v1_bytes` | unit | ES-1 | H×M | passes today; reruns after each unit |
| 2 | `answer_record_accepts_excluded_with_an_exclude_reason` | unit | ES-2 | H×M | `RecordStatus`, `ExcludeReason` |
| 3 | `answer_record_refuses_excluded_without_an_exclude_reason` | unit | ES-E1 | H×M | validator AR-I3 |
| 4 | `answer_record_refuses_an_exclude_reason_on_a_failed_member` | unit | ES-E2 | H×M | validator AR-I2 |
| 5 | `sdk_decodes_every_engine_evidence_case` (new cases X1, X2, rank, cut, judge model) | unit | ES-D1 | H×M | regenerate `evidence_cases.json` (approved) |
| 6 | `rank_outside_one_to_member_count_is_refused` | unit | ES-D2 | H×M | `rank` validator, both sides |
| 7 | `cut_k_and_order_are_checked` | unit | ES-D3 | H×L | `CutRecord`, `CombineCut` |
| 8 | `judge_model_text_is_checked` | unit | ES-D4 | M×M | length and control-character check |
| 9 | `dropped_does_not_count_excluded_members` | unit | ES-D5 | M×M | no change to the `dropped` rule |
| 10 | `sdk_decodes_excluded_rank_cut_and_judge_model` | unit | ES-3 | H×M | decoder optional key sets |
| 11 | `sdk_decoder_still_refuses_unknown_keys` | unit | ES-E3 | M×M | `_exact_keys` |
| 12 | `case_answers_show_the_excluded_status_and_value` | unit | ES-4 | H×M | `sf.Answer` value rule |
| 13 | `trace_extract_entry_carries_the_excluded_status` | unit | ES-D6 | M×L | passes through |
| 14 | `answer_v1_and_evidence_v1_snapshots_match` | unit | ES-1..4 | H×M | approved snapshot edits |
