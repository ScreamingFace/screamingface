---
ticket: OME-1679
stack: screamingface-engine
status: done
started: 2026-10-23
finished: 2026-10-23
---

# fusion-synthesizer-pictures — the Fusion synthesizer sees the Case's pictures

## Intent

A Fusion's synthesizer (and a reducer's signal calls) read one JSON text,
`{"input": <the Case input>, "outputs": …}`. On a picture Case that text holds the pictures as
base64, so the synthesizer reads up to a million tokens of base64 and never sees a picture. The
engine connector now spots that shape at run time: it sends the Case's picture parts first, then
today's text with each picture shown as a placeholder (type, size, sha256). Text-only Fusions keep
their exact bytes, so goldens replay. Design recorded on OME-1679 (2026-10-23).

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/benchmarks/candidate_input.py`: add
  `media_placeholder` (the one placeholder shape) and reword the module's "nothing decodes" rule.
- `apps/screamingface-engine/src/screamingface_engine/world/fusion_pictures.py` (new): read a
  Fusion context whose `input` is a v2 envelope into picture parts + one text part.
- `apps/screamingface-engine/src/screamingface_engine/world/connector.py`: `_native_messages`
  falls through to the Fusion reader when the context is not an envelope.
- `packages/screamingface/src/screamingface/case_result.py`: fix the stale `_data_uri_bytes`
  comment (the sha256 no longer keys the model call; #1550 closed).
- Tests: engine `test_candidate_input.py` (append), `test_fusion_pictures.py` (new),
  `test_media_placeholder_conformance.py` (new); SDK `test_candidate_input_schema_conformance.py`
  (append).
- `docs/tasks/2026-10-23-OME-1679-fusion-synthesizer-pictures.md` mirror.

## Test plan

- Placeholder: a PNG data URI gives size and sha256 of the decoded bytes; wrapped/unpadded base64
  gives the same placeholder; a filename is carried; broken base64 is refused by name.
- A picture Fusion context reaches the gateway with the image part first and no base64 in the text;
  the text holds the placeholder.
- Text-only Fusion contexts (plain prompt Case, v1 Case) reach the gateway byte for byte as today.
- The reducer (`panel`) form gets the image and is not refused.
- A struct built by url4 at run time feeds the synthesizer, so the test reads real bytes.
- A broken envelope inside `input` is refused before any gateway call.
- Under grading scope the path is off (unchanged).
- Engine ↔ SDK placeholder field names are equal (both lanes).

## Acceptance

- OME-1679 acceptance 1 and 2: image part present, no base64 in the text, placeholder in its place;
  text-only Fusion requests byte-identical.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, except the placeholder tests live in a new
  `tests/unit/test_media_placeholder.py` (not appended to `test_candidate_input.py`), and the SDK
  twin is a new `packages/screamingface/tests/unit/test_media_placeholder_conformance.py`.
  `candidate_input.py`'s `_json_object` became public `json_object` so the Fusion reader reuses it.
- **Commits:** see the PR.
- **Gates:** relevant tests only — engine `test_media_placeholder.py`, `test_fusion_context.py`,
  `test_media_placeholder_conformance.py`, `test_candidate_input.py`, `test_aigateway_connector.py`,
  `test_world_golden_parity.py`, `test_combine_wiring.py`, `test_combine_quorum_panel.py`,
  `test_combine_writer_world.py`, `test_combine_judge_world.py`: 156 passed. SDK
  `test_media_placeholder_conformance.py`, `test_candidate_input_schema_conformance.py`: 4 passed.
  ruff + pyright clean on every touched file, both lanes. Full suites run in CI.
- **Deviations:** none from the design on OME-1679. Owner decisions taken 2026-10-23: placeholder
  in the envelope module, broken base64 refused by name, SDK twin + stale comment fix in this PR,
  grading calls unchanged.
