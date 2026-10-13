---
ticket: OME-1527
stack: screamingface-engine
status: done
started: 2026-10-13
finished: 2026-10-13
---

# conversation-cases — let a Case's prompt be a fixed conversation

## Intent

OME-1527 Work order #19 (R14), PR 19 of 20. healthbench hands the Candidate a chat the
dataset wrote (115 of 525 professional Cases, 43 of 157 worst-30 Cases): user, assistant,
user, and the Candidate writes the next turn. That is still one Candidate call, but capture
refused any message list other than system text plus one user prompt. This unit lets capture
write such a conversation as the candidate-input envelope, the text form the connector already
opens into chat messages, so healthbench (row 20) can move to a local Task and replay its
worst-30 Fusion golden unchanged (decision 5).

## Planned changes

- `screamingface_engine_inspect/conversation_input.py` (new): seal a conversation into the
  envelope (the hand-built preparer's exact bytes) and open a Case input back into turns.
- `capture.py`: a run of system/user/assistant text turns ending on a user turn becomes the
  envelope; the one-prompt shape keeps its plain text and bytes.
- `scorer_adapter.py`: a conversation Case's state is rebuilt as its turns.
- `single_shot.py`: `candidate_input_envelope` leaves an input that is already an envelope as
  written (no double wrap).

## Test plan

- `tests/unit/inspect/test_conversation_cases.py` (new): the written bytes equal a literal
  printed from hand-built healthbench's `envelope()` and that function itself; a one-prompt
  Case keeps its text; a system turn inside a conversation keeps its role; tool turns and
  tool-calling assistant turns refused; the Case Digest seals every turn; the envelope flag
  serves a conversation as written; the scorer sees the turns; plain prompts (JSON included)
  are never read as conversations; a broken envelope is refused.
- `test_capture.py`: the multi-turn refusal narrows to a conversation ending on an assistant
  turn.

## Acceptance

- A conversation Case's input is byte-identical to hand-built healthbench's.
- No published revision moves (`test_published_revisions.py` unedited and green).

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `.claude/test-change-approvals/OME-1527.json`
  (re-pinned for this branch: the one edited capture test).
- **Real-bundle check:** a locally prepared hand-built healthbench bundle (525 professional
  Cases) was rebuilt as inspect Samples, run through capture, then served through the
  `candidate_input_envelope` wrap: 525 of 525 served inputs byte-identical to the hand-built
  `cases.json`, 115 written as conversations. The bundle holds only user and assistant turns,
  strictly alternating, always ending on a user turn, so nothing in it hits a refusal.
- **Commits:** see the PR.
- **Gates:** relevant files only: `test_conversation_cases.py`, `test_capture.py`,
  `test_inspect_scorer_adapter.py`, `test_local_task_gdpval.py`, `test_published_revisions.py`
  and the four suites that import capture (`test_imported_catalogue_activity.py`,
  `test_inspect_gsm8k_benchmark.py`, `test_inspect_mmlu_benchmark.py`,
  `test_inspect_task_replay_benchmarks.py`), all with the inspect extra: 393 passed. ruff +
  format clean; extra-less pyright 0 errors on touched files. Full gate = pre-push hook + CI.
- **Deviations:** (1) No row flag: a conversation becomes the envelope whenever capture sees
  one, because these shapes were refused until now, so no imported Benchmark's Cases change.
  (2) Turns need not alternate (the connector and inspect don't require it); only the last turn
  must be the user's. (3) A system turn inside a conversation keeps its role; a system turn
  before a single prompt is still folded into the text, as before, so one-prompt Cases keep
  their bytes.
- **Owner-verify:** none for this unit; row 20 replays the worst-30 golden.
