---
ticket: OME-1680
stack: screamingface
status: done
started: 2026-10-23
finished: 2026-10-23
---

# case-result-picture-placeholder — Case Results show a placeholder instead of base64 for pictures

## Intent

A picture Benchmark's Case carries its pictures inline, as `data:` URIs inside a v2 candidate-input
envelope (OME-1678). The SDK's `CaseResult.conversation` reads only v1, so a v2 input falls back to
the raw string and the notebook and Report show megabytes of base64. This unit teaches the one
decode point to read v2: text parts stay text, and each picture or file part becomes one line
naming its file (when it has one), media type, size and sha256. It reads both forms a picture can
arrive in: a real `data:` URI (the SDK decodes it to measure size and digest) and the placeholder
object the engine will start writing in its place (OME-1679 design decision, 2026-10-23).

## Planned changes

- `packages/screamingface/src/screamingface/case_result.py`: the v2 schema name, the placeholder
  field names in one constant, the placeholder builder and its one-line rendering, and the
  envelope decoder reading v2 part lists.
- `packages/screamingface/tests/test_case_result_pictures.py` (new): the rendering tests.
- `packages/screamingface/tests/unit/test_candidate_input_schema_conformance.py` (new): the SDK's
  schema names equal the engine's, read from `benchmarks/contract.py` with `ast`.

## Test plan

- One image part renders as the placeholder line, and the base64 appears in none of
  `conversation`, `display_input`, `prompt_preview` or the Report HTML.
- The placeholder-object form renders the same line as the `data:` URI it replaced.
- A file part with a filename leads its line with the filename.
- Text-only (v1) results render exactly as on main (existing tests pinned unchanged).
- Unknown schema and malformed v2 keep today's raw-string fallback.
- Conformance: the SDK's candidate-input schema names equal the engine's.

## Acceptance

- Ticket acceptance 1, 2, 3 and 5 hold in tests; 4 (a reviewer other than the author) at review.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned (`case_result.py`, `tests/test_case_result_pictures.py`,
  `tests/unit/test_candidate_input_schema_conformance.py`), plus this ledger and the mirror.
- **Commits:** `0a203db3b` — feat(screamingface): show pictures in Case Results as a placeholder,
  never base64; then the docs-close commit.
- **Gates:** the PR's tests only: the two new files plus every existing test of the decode path
  and its renderers (`test_case_results.py`, `test_case_outcome_decoding.py`,
  `test_inspect_log_payload.py`, `test_report_panel.py`, `e2e/test_report_tape.py`,
  `test_public_surface.py`): 163 passed. ruff check + format and pyright clean on touched files.
- **Deviations:** none. The inspect log export (`_inspect_log/payload.py`) reads `conversation`,
  so a v2 Case now exports placeholder text instead of the raw envelope; noted for review.
  The placeholder-format conformance test waits for the engine's builder (OME-1679); the SDK's
  field names live in `_PLACEHOLDER_FIELDS` / `_PLACEHOLDER_OPTIONAL_FIELDS`.
