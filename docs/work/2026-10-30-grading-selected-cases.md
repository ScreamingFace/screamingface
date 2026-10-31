---
ticket: OME-1789
stack: screamingface-engine
status: done
started: 2026-10-30
finished: 2026-10-30
---

# grading-selected-cases — Grading reads only the selected Cases, not all of cases.json

## Intent

An imported-board run's aggregate step calls `read_selected_cases`
(`shared_grading/case_grades.py`), which reads the whole `cases.json` into one string and
`json.loads` it just to pick the selected rows. On FigQA (181 Cases, ~330 MB of base64 pictures)
that adds hundreds of MiB of peak memory even for a 2-Case run (OME-1314: capacity for 30
concurrent users). Make the reader stream the top-level array one row at a time and keep only
the selected rows, so aggregation memory scales with the selected Cases (plus one row), not the
board. No per-Case storage (OME-1790); the Cases route (OME-1675) is untouched.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/benchmarks/shared_grading/case_grades.py`
  — `read_selected_cases` reads `cases.json` incrementally (chunked `raw_decode` per array
  element), keeping only rows whose id is selected; same results and error wording.
- possibly a small new module next to it for the streaming array reader if `case_grades.py`
  would pass the module-size limit.
- new test file `apps/screamingface-engine/tests/unit/test_selected_cases_streaming.py`.

## Test plan

- Identical result to the full-parse reader on: selected order, duplicates (last row wins),
  non-object rows and bool/non-int ids skipped, whitespace/pretty-printed JSON, rows larger
  than the read chunk, empty array.
- Errors unchanged in wording prefix: missing file / invalid JSON / truncated array →
  "cases are unavailable"; top-level non-array → "cases must be a JSON array"; missing or
  blank input → "Case N has no public input".
- INVARIANT: memory — the reader never holds the whole file: with a tiny chunk size, reading
  a board whose total size is many times the chunk keeps the largest buffer bounded by one
  row (asserted through the reader's chunk reads, not RSS).

## Acceptance

- Grades for a 2-Case run of a large board are byte-identical to today's.
- Measured peak RSS during `read_selected_cases` on a large synthetic board scales with the
  selected Cases, not the board — numbers below.
- `run_gates.py screamingface-engine --base origin/main` and `check_module_size.py` green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, the streaming reader in its own module:
  - new `apps/screamingface-engine/src/screamingface_engine/benchmarks/shared_grading/case_rows.py`
    (`iter_array_rows`, `NotAnArrayError`, `CHUNK_CHARS` = 1 MiB)
  - modified `.../shared_grading/case_grades.py` (`read_selected_cases` streams and keeps only
    the selected rows)
  - new `apps/screamingface-engine/tests/unit/test_selected_cases_streaming.py` (207 tests:
    oracle equivalence vs the old full parse across chunk sizes 1..1 MiB, duplicates, skipped
    rows, rows larger than a chunk, numbers cut at every chunk edge, 40 seeded random arrays,
    13 malformed documents, non-array documents, undecodable bytes, and the streaming
    invariant — the first row is yielded after < 3 rows' worth of text is read)
- **Commits:** see git log of `OME-1789-grading-selected-cases`.
- **Gates:** `run_gates.py screamingface-engine --base origin/main` — ALL GATES GREEN
  (append-only, ruff, format, pyright, layering, pytest 6229 passed / 157 skipped, cov >= 80;
  `case_rows.py` 100% line+branch). `packages/url4/scripts/check_module_size.py`: all capped
  modules within baseline (no url4 module touched).
- **Measurement:** synthetic FigQA-shaped board from `make_bundle.py` — 181 Cases, one ~1.36 MB
  JPEG each, `cases.json` = 328,269,060 bytes. macOS, peak RSS (`ru_maxrss`) of a process that
  only calls the reader, minus its RSS just before the call (49 MiB):

  | selected Cases | before (full parse) | after (streamed) |
  |---:|---:|---:|
  | 2 | +946 MiB | +50 MiB |
  | 20 | +946 MiB | +86 MiB |
  | 90 | +946 MiB | +244 MiB |
  | 181 | +946 MiB | +404 MiB |

  After: ~46 MiB fixed (1 MiB read chunk, one decoded row in flight, allocator) plus ~2 MiB per
  selected Case — the size of one row. `measure.py aggregate`: PEAK RSS 1010 MiB -> 107 MiB.
  Byte-identity: sha256 of `repr(read_selected_cases(...))` for ids (1, 2) and (181, 7, 90) on
  the same board is identical before and after.
- **Deviations:** the `cases are unavailable: {exc}` suffix for a malformed file may word the
  JSON error differently from `json.loads` (e.g. "expected ',' or ']' in the cases array"),
  and positions in a decoder error are relative to the read buffer. The prefix, the error class,
  and every accept/reject decision are unchanged. A non-array document still decodes whole
  (rare broken-bundle path) to keep "not JSON" vs "not an array" exact.
