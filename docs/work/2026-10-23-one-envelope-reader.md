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
- `single_shot.py` — no change: the wrapping step already asks `conversation_messages`, so it
  inherits the new rule (kept untouched for the open PR rewriting its neighbours).
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

- Every inspect reader of the candidate-input envelope goes through `parse_candidate_input`.
- The new tests pass; every existing test that imports the touched modules passes unchanged.
- ruff + pyright clean on touched files.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned: `conversation_input.py`, `scorer_adapter.py`, the new
  `tests/unit/inspect/test_one_envelope_reader.py` (9 tests). `single_shot.py` untouched: the
  wrapping step inherits the shared rule through `conversation_messages`.
- **Commits:** `4179ba196` — refactor(screamingface-engine): read every candidate-input
  envelope through one parser.
- **Gates:** relevant tests only, with the inspect extra: every test file importing
  `conversation_input`, `scorer_adapter` or `single_shot` (41 files), 1202 passed, 0 skipped;
  ruff check + format and pyright clean on the touched files.
- **Deviations:** the scorer adapter had no envelope reader of its own; it already called
  `conversation_messages`, so moving that one function moved both readers. The v2 picture to
  `ContentImage` step landed here (a few lines in `_chat`), not in a later PR.
