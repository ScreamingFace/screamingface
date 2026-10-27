---
ticket: OME-1271
stack: screamingface-engine
status: done
started: 2026-10-27
finished: 2026-10-27
---

# results-picture-placeholders — a Case Result shows a placeholder, not base64, for each picture

## Intent

Every Case Result echoes its Case input, so a picture Benchmark (LAB-Bench FigQA: 181 Cases,
pictures inline, about 330 MB) would ship every picture's base64 to the researcher's notebook,
where large reports already run out of memory. When the engine hands back a Candidate result,
each picture or file part in the echoed input becomes the shared placeholder (type, size and
sha256 of the decoded bytes, plus the filename when the part names one). Grading still reads
the real Case; a text-only Case Result stays byte-identical.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/benchmarks/echoed_input.py` (new): the
  one function that turns a Case input into the text a result echoes.
- `apps/screamingface-engine/src/screamingface_engine/benchmarks/aggregation.py`:
  `finalize_candidate_result`, the single constructor of `CandidateResult`, echoes each Case's
  input through it after scoring.
- Tests: `apps/screamingface-engine/tests/unit/test_echoed_input.py` (new), appended cases in
  `apps/screamingface-engine/tests/unit/test_benchmark_aggregation.py`.

## Test plan

- A picture Case echoes the placeholder (sha256, decoded size, media type) and no `base64,`.
- A plain prompt and a v1 conversation echo the exact same string.
- A file part keeps its filename; a picture's `detail` is kept.
- A broken envelope echoes a fixed line that names the rule, never the bytes.
- Through `finalize_candidate_result`: the payload carries the placeholder, and the scorer
  still saw the real Case input.
- The SDK's `CaseResult.conversation` reads the engine's echoed text as the placeholder line
  (shape agreement checked against the SDK source).

## Acceptance

- No echoed input in a finalized Candidate result contains a picture's base64.
- Text-only results are byte-identical; grading is unchanged.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned (`benchmarks/echoed_input.py` new, `benchmarks/aggregation.py`
  wired, `tests/unit/test_echoed_input.py` new, 4 cases appended to
  `tests/unit/test_benchmark_aggregation.py`), plus one appended SDK test in
  `packages/screamingface/tests/unit/test_media_placeholder_conformance.py` that reads the
  engine's echo, byte for byte, as the placeholder line. No SDK source change: it already
  reads a placeholder object where the bytes were.
- **Where an echoed input leaves the engine:** only the Candidate result, and
  `finalize_candidate_result` is its one constructor (both the aggregate path and the early-grade
  path finish there). Progress events replace the input with `[not retained]`; spans carry no
  content; failure metadata is a whitelist of counts; the graded-case rows between url4 nodes
  stay internal and keep the real input (their decoder matches it against the selected Case).
- **Commits:** see `git log` on `OME-1271-pr3-results-placeholders` —
  feat(screamingface-engine): show a placeholder, not base64, for pictures in Case Results.
- **Gates:** relevant tests only. Engine extra-less lane: 40 files that import the finalizer or
  the envelope reader, plus the transport/incremental/aggregate files, 512 passed. Engine
  inspect lane (`--extra inspect`): the 30 inspect files importing the finalizer plus
  `test_one_envelope_reader.py`, 449 passed. SDK: `test_media_placeholder_conformance.py` +
  `test_case_result_pictures.py`, 19 passed. ruff check, ruff format --check, pyright clean on
  touched files; `check_layering.py` OK.
- **Deviations:** module named `echoed_input.py` (not a function in `candidate_input.py`, which
  would pass 450 lines). A Case the reader refuses echoes one line,
  `[Case input not shown: <the rule it broke>]`, instead of its raw text (owner to confirm).
