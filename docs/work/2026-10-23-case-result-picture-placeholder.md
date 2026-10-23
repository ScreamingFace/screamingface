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
  never base64; `1fce932a1` — docs(work): close the OME-1680 ledger and mirror; `82716bedd` —
  fix(screamingface): never crash or dump base64 on an envelope the SDK cannot read (review
  fixes); then this docs update.
- **Gates:** the PR's tests only: the two new files plus every existing test of the decode path
  and its renderers (`test_case_results.py`, `test_case_outcome_decoding.py`,
  `test_inspect_log_payload.py`, `test_report_panel.py`, `e2e/test_report_tape.py`,
  `test_public_surface.py`): 168 passed. ruff check + format and pyright clean on touched files.
- **Review fixes (82716bedd):** a non-text `schema` no longer raises (the engine runs such a Case
  as a plain prompt); an unknown `screamingface.candidate-input.*` version shows one upgrade line
  instead of its raw base64; base64 is decoded as the engine's request key decodes it (line
  breaks dropped, padding restored), so the sha256 shown is the one that keys the call; a file
  part's own `filename` names its placeholder object; a twin test pins the SDK's `data:` URI
  pattern to the engine's `_DATA_URI_RE`.
- **Deviations:**
  - The base64 is hidden in the view, not dropped. `CaseResult.input`, `to_dict()["input"]` and
    the dataclass repr still hold it, so `repr(case)` in a notebook still prints it and per-run
    memory (OME-1448) is unchanged. The real drop lands engine-side (OME-1271 PR 3).
  - The inspect log export (`_inspect_log/payload.py`) reads `conversation`, so a v2 Case now
    exports placeholder text instead of the raw envelope; an unknown-version Case still exports
    its raw input there.
  - `_size_text` copies the Report's byte formatter (`_ui/report_view.py` `_bytes`) on purpose:
    core must not import UI.
  - The SDK lane's CI path filter does not list the engine's `benchmarks/candidate_input.py`, so
    an engine-only change to `_DATA_URI_RE` will not run the new SDK pin until the SDK lane next
    runs. Adding that path to `.github/workflows/screamingface-tests.yml` is an owner action.
  - The placeholder-format conformance test waits for the engine's builder (OME-1679); the SDK's
    field names live in `_PLACEHOLDER_FIELDS` / `_PLACEHOLDER_OPTIONAL_FIELDS`.
