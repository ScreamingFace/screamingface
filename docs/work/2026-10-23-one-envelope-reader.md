---
ticket: OME-1271
stack: screamingface-engine
status: done
started: 2026-10-23
finished: 2026-10-23
---

# one-envelope-reader — every inspect reader opens the Case envelope through the one shared parser

## Intent

A Case input that is a chat travels as the candidate-input envelope. The connector already opens
it with the shared parser (`benchmarks/candidate_input.py`, OME-1678), which reads v1 and v2 and
refuses any other version of the schema. The inspect plugin still had its own reader: it read a
v2 envelope (pictures inline) as "not an envelope", so the wrapping step would seal the whole v2
JSON as plain text inside a v1 envelope and the base64 would reach the Candidate and the judge as
tokens, silently. This unit moves the inspect reader onto the shared parser, so a v2 Case passes
through the wrapping step unchanged, an unknown schema is refused instead of read as text, and the
scorer rebuilds a v2 picture as inspect's own `ContentImage`. It must land before any importer
writes a v2 Case (OME-1271 acceptance 3, 4, 5). Text-only Benchmarks stay byte-identical.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine_inspect/conversation_input.py` —
  `conversation_messages` delegates to `parse_candidate_input`, keeps the inspect-only role rule
  (no `developer`), returns the shared typed messages.
- `apps/screamingface-engine/src/screamingface_engine_inspect/scorer_adapter.py` — `_chat`
  turns a v2 part list into `ContentText` / `ContentImage` / `ContentDocument`.
- `single_shot.py` — the wrapping step already asks `conversation_messages`, so it inherits the
  new rule; kept to the smallest edit (see Outcome) for the open PR rewriting its neighbours.
- `apps/screamingface-engine/tests/unit/inspect/test_one_envelope_reader.py` — new.

## Test plan

- A v2 Case passes through the wrapping step byte for byte; a plain neighbour is wrapped exactly
  as on main (hand-pasted bytes).
- An unknown candidate-input schema (v0, v3) is refused by the inspect reader and by the
  wrapping step, never wrapped as text.
- The scorer gets a v2 picture as `ContentImage` (and a PDF as `ContentDocument`); no message text
  and no `input_text` carries the base64.
- Existing: `tests/unit/inspect/test_conversation_cases.py`, `test_inspect_scorer_adapter.py`
  unchanged and green.

## Acceptance

- Every reader of the candidate-input envelope in the Engine's inspect plugin goes through
  `parse_candidate_input` (the SDK's reader is out of scope, see Not done).
- The new tests pass; every existing test that imports the touched modules passes unchanged.
- ruff + pyright clean on touched files.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** `conversation_input.py`, `scorer_adapter.py`, the new
  `tests/unit/inspect/test_one_envelope_reader.py` (10 tests), and a 6-line change in
  `single_shot.py`'s wrapping step (`_enveloped_inputs`): a refused envelope now names its
  Case id, keeping the parser's words and chaining the original error. Without it, one broken
  Case among hundreds surfaced as "message 0 part 1: expected an inline data: URI" with no
  Case number. The cases route (`case_selection.py`) is untouched (an open PR rewrites it).
- **Commits:**
  - `4179ba196` — refactor(screamingface-engine): read every candidate-input envelope through
    one parser
  - `dceeefe76` — docs(work): close the one-envelope-reader ledger
  - `34293e6c8` — fix(screamingface-engine): name the Case when the wrapping step refuses its
    envelope
  - the follow-up docs(work) commit carrying this Outcome update
- **Gates:** relevant tests only, with the inspect extra: every test file importing
  `conversation_input`, `scorer_adapter` or `single_shot` (41 files), 1203 passed, 0 skipped;
  ruff check + format clean and pyright clean on the touched files (the only pyright errors
  are the existing `url4` import lines in `single_shot.py`, which pyright cannot resolve
  through url4's editable install).
- **Deviations:** the scorer adapter had no envelope reader of its own; it already called
  `conversation_messages`, so moving that one function moved both engine-side readers. The v2
  picture to `ContentImage` step landed here (a few lines in `_chat`), not in a later PR.
- **Behaviour change beyond v2:** the shared parser trims leading whitespace before deciding
  whether a text is an envelope; the old inspect reader did not. A whitespace-prefixed v1
  envelope is now read as an envelope (served as written, rebuilt as a chat for the scorer),
  matching the connector. No existing fixture has such a Case.
- **Not done:**
  - The SDK's reader (`packages/screamingface`, `case_result.py`) still reads v1 only; it moves
    under OME-1680, in its own PR. "Every inspect reader" above means the Engine's inspect
    plugin.
  - In the scorer adapter, `_task_state` (which opens the envelope) runs before `grade()`'s
    `try`, so a refusal there is not turned into a per-Case failure: it propagates through
    `_observed` (which re-raises) and out of the aggregate's `grade_case` call, which does not
    catch it, so the whole aggregate fails instead of one Case. Read from code, not reproduced
    by a test. In practice a Benchmark that serves the envelope refuses the broken Case at the
    wrapping step first; left for a later PR.
