---
ticket: OME-1678
stack: screamingface-engine
status: in_progress
started: 2026-10-21
finished:
---

# candidate-input-envelope — send a Case's inline pictures to the model as image parts

## Intent

Picture Benchmarks (MMMU, HLE, MathVista, LAB-Bench FigQA) carry each picture inside the Case as a
`data:` URI in a v2 candidate-input envelope (§2.7 proposed on PR #1450). Today the connector
accepts message content only as one string, so a picture Case is refused as
`invalid_candidate_input`. This unit adds one envelope module in engine core that reads v1 and v2
and enforces the §2.7 rules, and moves the connector onto it so v2 parts reach the gateway as
OpenAI content parts. v1 Cases keep byte-identical requests.

## Planned changes

- NEW `apps/screamingface-engine/src/screamingface_engine/benchmarks/candidate_input.py` —
  `parse_candidate_input` (text → messages or `None` for a plain prompt), `CandidateInputError`.
- `apps/screamingface-engine/src/screamingface_engine/benchmarks/contract.py` — add
  `CANDIDATE_INPUT_V2_SCHEMA`.
- `apps/screamingface-engine/src/screamingface_engine/world/connector.py` — `_messages` calls the
  module; delete `_candidate_input_envelope`, `_json_object`, `_candidate_messages`,
  `_candidate_message`; message type widens to allow a list of parts.
- NEW `apps/screamingface-engine/tests/unit/test_candidate_input.py`.
- `apps/screamingface-engine/tests/unit/test_aigateway_connector.py` — append v2 tests.

Decisions (owner-approved 2026-10-21): module in `benchmarks/`; a text-only message in v2 is a
string, a list only when it carries a picture or file; pictures PNG/JPEG/GIF/WebP, files PDF only;
check the `data:` prefix only, never decode; refusal keeps the `invalid_candidate_input` code and
never echoes a URL; one PR.

## Test plan

- v1: same messages as today (existing connector tests stay green, unmodified).
- v2 happy path: user text + PNG part → list content, parts verbatim; PDF `file` part with filename.
- v2 refusals, each by message/part number with no URL in the text: unknown part type, `https://`
  URL, `/blob/` ref, `image/svg+xml`, PDF in `image_url`, non-PDF file, bad `detail`, extra keys,
  picture in a system/assistant message, text-only v2, list content with only text parts.
- unknown `screamingface.candidate-input.v3` refused by name; non-envelope JSON and plain text →
  `None` (a prompt).
- connector: a v2 Case reaches the gateway body as content parts; the largest MMMU-size input
  (≈3.8 MB) parses.

## Acceptance

- OME-1678 acceptance 1-3: v2 reaches the gateway as parts; v1 byte-identical; unknown schema refused
  by name, no base64 in the refusal text.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned. `_json_object`, `_candidate_input_envelope`, `_candidate_messages`
  and `_candidate_message` left the connector; `import json` went with them.
- **Commits:** see the PR.
- **Gates:** ruff check, ruff format --check and pyright on the 5 touched files clean;
  `check_layering.py` OK; `test_candidate_input.py`, `test_aigateway_connector.py`,
  `test_request_scope_hardening.py`, `test_failure_classes.py`, `test_terminal_error_detail.py`:
  172 passed. Full suite left to CI.
- **Deviations:** none in scope. OME-1678 acceptance 4 (MMMU `validation_Geography_16` end to end
  on the local stack) is an owner-verify step: it needs the importer (OME-1271 PR 2) to produce
  the Case and a vision model behind the gateway.
