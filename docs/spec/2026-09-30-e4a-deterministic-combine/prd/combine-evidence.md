# PRD: Combine evidence — from the endpoint to the SDK Report (component)

**Source:** prompt (OME-1289), ans:Q6 · **Priority:** P1, build fourth
**Lifecycle:** existing (OME-843 operation attribution) — characterize, then delta
**Owner:** unassigned
**Landing:** `apps/screamingface-engine` and `packages/screamingface` (one sub-issue each)

## 1. Summary and the flows it serves

For each case and each reducer, the SDK Report shows what the combine step read and decided: the
reading for each member, the tally or scores, the agreement, the tie flag, and the chosen member.
The evidence goes with the existing per-operation record, so a candidate with several reducers
keeps one record for each reducer. It serves every reducer flow.

## 2. Background and constraints

- "The report shows the extracted value per member, the tally or the scores, and which member was
  chosen." `[stated prompt]`
- "The report includes the tally and the agreement fraction … Later epics read that fraction."
  `[stated prompt]`
- The evidence goes to the SDK Report only. The scoreboard payload does not change
  `[stated ans:Q6]`.

### 2.1 Current behavior

- During a candidate run, the connector records each terminal model call as
  `OperationCall(path, params, output, finish_reason, accounting)`
  `[existing apps/screamingface-engine/src/screamingface_engine/operation_calls.py]`.
- `attribute_operation_outputs` joins the calls to the named sources (`model_N`, `synthesis_N`) by
  the fingerprint `(path, sorted params)`. A fingerprint that one binding claims takes its last
  call. A fingerprint that several bindings claim stays null unless the outputs are identical
  `[existing apps/screamingface-engine/src/screamingface_engine/benchmarks/operation_outputs.py:1]`.
- `CandidateInvocation.operations` is left out of the JSON when it is null, so older envelopes stay
  byte-identical `[existing apps/screamingface-engine/src/screamingface_engine/benchmarks/contract.py:333]`.
- The corrective loop records one `CorrectiveLoopOutcome` in `execution` for each case
  `[existing apps/screamingface-engine/src/screamingface_engine/world/corrective.py:238]`. That
  field holds one value only, so it cannot carry one record for each reducer `[implied]`.
- The SDK keeps `CaseOperation(operation_id, output, finish_reason, accounting)` for each case
  `[existing packages/screamingface/src/screamingface/case_result.py:262]`.

**Delta.**
1. The combine endpoint records an `OperationCall` with `path=/ensemble/combine/v1`,
   `params=(("binding", "synthesis_N"),)`, `output=<step output>`, `finish_reason="stop"`,
   `accounting=None`, and the new field `combine=<CombineEvidence>` `[proposed]`.
2. `attribute_operation_outputs` copies `combine` into `OperationOutput.combine` `[proposed]`.
3. `OperationOutput.combine` is left out of the JSON when it is null `[proposed]`.
4. The SDK decodes it into `CaseOperation.combine: CombineEvidence | None`, with `to_dict()` and
   strict validation `[proposed]`.
5. Judge and writer model calls get the bindings `judge_N` and `writer_N`, so their raw outputs
   also appear as operations `[proposed]`.

## 3. Scenarios and acceptance criteria

### 3.1 Happy path

**EV-H1 Evidence reaches the Report.** `[stated prompt]`
Given a GSM8K run with a Vote over five members,
When case 1 finishes,
Then `report.candidates[0].cases["1"].operations` has `op_synthesis_1` with `output` equal to the
chosen member's text and `combine` with `members[5]`, `tally`, `agreement`, `tie`, and `chosen`.

**EV-H2 Agreement can be read.** `[stated prompt]`
Given EV-H1,
When code reads `operation.combine.agreement`,
Then it is a float in (0, 1].

**EV-H3 Members stay visible.** `[existing apps/screamingface-engine/src/screamingface_engine/benchmarks/operation_outputs.py]`
Given EV-H1,
When the Report is read,
Then `op_model_1 … op_model_5` still carry each member's own output and accounting.

### 3.2 Error paths

**EV-E1 Failed step, no evidence.** `[stated ans:Q9]`
Given a vote that raises `combine_no_votes`,
When the case is reported,
Then the case has the failure code, and no `combine` evidence for that operation is invented.

**EV-E2 Ambiguous fingerprint.** `[existing apps/screamingface-engine/src/screamingface_engine/benchmarks/operation_outputs.py]`
Given two combine calls whose `(path, params)` are the same (this happens only if the `binding`
param is missing),
When attribution runs,
Then `combine` is null for both, with no guess. SL-4 makes this impossible for compiled
candidates.

### 3.3 Derived scenarios (risk order)

| ID | Title | Tag | I×L | Given / When / Then |
|---|---|---|---|---|
| EV-D1 | No reducer means no wire change | [proposed] | H×M | Given a candidate without a reducer, when the envelope is encoded, then it is byte-identical to today's (golden). |
| EV-D2 | Two reducers in one candidate | [implied] | H×M | Given a Pipeline of two vote Fusions, when the case finishes, then `op_synthesis_1` and `op_synthesis_2` each have their own evidence. |
| EV-D3 | Corrective rounds | [existing apps/screamingface-engine/src/screamingface_engine/benchmarks/operation_outputs.py] | M×M | Given a Vote inside a CorrectiveLoop that runs 3 rounds, when attribution runs, then the evidence is from the last round. |
| EV-D4 | Multi-turn benchmark | [implied] | M×M | Given MedXpertQA (two calls of the candidate for each case), when attribution runs, then the evidence is from the second turn. |
| EV-D5 | Strict SDK decode | [proposed] | M×L | Given evidence with an unknown key or a wrong schema id, when the SDK decodes it, then decoding fails with a clear error, not a silent drop. |
| EV-D6 | Scoreboard unchanged | [stated ans:Q6] | M×L | Given a report with evidence, when `Leaderboards.submit` builds its payload, then the payload equals the payload without evidence. |
| EV-D7 | Payload size | [proposed] | M×L | Given 64 members, when evidence is built, then it holds readings and tally only (no member texts), and it is ≤ 64 KiB. |

## 4. Non-functional requirements

- The evidence holds no member text. Text is in each operation's `output` `[proposed]`.
- The decoders accept `screamingface.combine-evidence.v1` only. A `.v2` adds a decoder branch
  `[proposed]`.

## 5. Out of scope

- Scoreboard and leaderboard display `[stated ans:Q6]`.
- Studio display `[stated ans:Q5]`.

## 6. Open questions

None.

## 7. TDD plan (core-out: engine record → attribution → wire → SDK)

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| EV-1 | CHAR `envelope_without_reducer_is_byte_identical` (golden) | unit | [existing apps/screamingface-engine/src/screamingface_engine/benchmarks/contract.py:333] | H×M | passes today; keep it green |
| EV-2 | CHAR `ambiguous_fingerprint_stays_null` | unit | [existing apps/screamingface-engine/src/screamingface_engine/benchmarks/operation_outputs.py] | M×M | passes today |
| EV-3 | `combine_endpoint_records_an_operation_call_with_evidence` | unit | [proposed] | H×M | recorder in `combine/evidence.py` |
| EV-4 | `attribution_copies_combine_evidence_to_operation_output` | unit | [proposed] | H×M | one more field in `_attributed` |
| EV-5 | `operation_output_omits_combine_when_null` | unit | [proposed] | H×M | `exclude_if` |
| EV-6 | `two_reducers_keep_separate_evidence` | integration | [implied] | H×M | unique `binding` param |
| EV-7 | `sdk_decodes_combine_evidence_into_case_operation` | unit | [stated prompt] | H×M | new decoder |
| EV-8 | `sdk_rejects_unknown_keys_and_schema` | unit | [proposed] | M×L | strict decode |
| EV-9 | `judge_and_writer_bindings_are_attributed` | unit | [proposed] | M×M | widened pattern |
| EV-10 | `corrective_rounds_keep_last_evidence` | integration | [existing apps/screamingface-engine/src/screamingface_engine/benchmarks/operation_outputs.py] | M×M | last-call rule |
| EV-11 | `scoreboard_submission_ignores_combine_evidence` | unit | [stated ans:Q6] | M×L | no change; pin it |
| EV-12 | `gsm8k_vote_run_reports_evidence_end_to_end` (replay lane) | E2E | [stated prompt] | H×M | `packages/screamingface/tests/e2e/` replay |
| EV-13 | `multi_turn_case_keeps_second_turn_evidence` | integration | [implied] | M×M | last-call rule |
| EV-14 | `evidence_for_64_members_has_no_text_and_fits_64kib` | unit | [proposed] | M×L | readings only |
