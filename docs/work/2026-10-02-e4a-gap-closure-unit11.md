---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: screamingface
status: in_progress   # planned | in_progress | done | blocked
started: 2026-10-02
---

# e4a-gap-closure unit 11 -- the e2e replay lanes: signals, traces, Fusion regression

## Intent

Fold the e2e replay lane (`e4a-e2e-replay`) into the gap-closure stack. The branch is rebased onto
`e4a-rank-concat-sdk`. Three rows land on top of the EV-10 and EV-12 lane: FR#13 (a GSM8K Fusion
regression lane, byte for byte), SG#15 (a cost-weighted vote replayed from cache gives the same
signals and tally) and RT#16 (the cached replay's trace differs from the live trace only in
model-call accounting). The paid recordings are made later by the user. Until then every e2e replay
test SKIPS loudly. No source file changes: this unit is tests, harness, fixtures, CI and docs.

## Planned changes

- Commit B: repair the lane tests onto the Answer-row evidence wire (unit 4).
- Commit C: pin an answered Case in the vote lane evidence lock (F3).
- Commit D: the lane snapshots carry `metadata_json` (F4, F13).
- Commit E: `harness/replay_trace.py`, the RT-4 drift rule.
- Commit F: the cost-weighted vote beside the GSM8K vote lane (record and bless seams).
- Commit G: the replay tests for signals and traces (skip until recorded).
- Commit H: `harness/fusion_golden.py` and its models.
- Commit I: `fixtures/fusion_lane.py`, `inspect_capture_stack`, and the lane tests.
- Commit J: the workflow and justfile for the fusion lane.
- Commit K: this ledger, closed.

## Test plan

Rebase. `git rebase --onto e4a-rank-concat-sdk 877f17a26 e4a-e2e-replay` replayed the 9 commits with
no textual conflict. The pre-check (`git diff --stat 877f17a26 e4a-rank-concat-sdk -- <the unit
paths>`) was empty. The workflow and justfile diffs against the parent equal the old ones.

Red set after the rebase (`pytest tests/e2e tests/test_corrective_vote_contract_fixture.py` in the
SDK, and the engine corrective rounds test):

| # | Observed | Fix |
|---|---|---|
| S1 | `test_reducer_golden_contracts.py` and `test_reducer_lane_contracts.py` fail at collection: `ImportError CombineMemberReading` | B |
| S2 | after S1: `_evidence()` has no `result` or `dropped`, status `"voted"` | B |
| S3 | the failure code `combine_no_votes` in the test data | B |
| S4 | does NOT apply: the EV-10 drift guard is green after the rebase | none |
| S5 | the engine test `test_corrective_loop_with_a_reducer_member_reports_no_operation_evidence_yet` stays green | none |

With the two broken files ignored: 119 passed, 25 skipped. Engine corrective rounds: 1 passed.

Rows without a RED: Commit B (repair), guard and CHAR rows, and every e2e test that skips until
the user records. Each is named in Notes when it lands.

## Notes

Decisions F1-F14 come from the unit spec (`gap-unit11-replay.md`). The ones that need a record:

- F1 no textual conflict on the rebase. The breaks are semantic (S1-S3).
- F2 the evidence wire moved in unit 4. `_evidence()` is rebuilt on `CombineAnswerRow` and
  `CombineResult`.
- F3 pin the first Case whose evidence has `result.status == "answered"`.
- F4 the replay snapshots drop `metadata_json`, so a hit has no price and no latency. The reducer
  and fusion lanes use 13 columns.
- F5 SG#15 rides on the EV-12 recording: `record` runs the cost-weighted vote first.
- F6 RT#16 uses the live `trace_dict()` that `record` saves.
- F7 request bodies are captured on replay only.
- F11 a bless refusal on SG-D1 or RT-4 is a product defect report, not an implementer stop.
- F14 EV-10 is a CHAR test: it is unchanged.
- Follow-ups file `gap-sdk-followups-from-engine.md`: it has no item tagged 11.

## Recording the lanes

(written in Commit K)

## Outcome

(written in Commit K)
