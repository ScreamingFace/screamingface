---
ticket: OME-1790
stack: screamingface-engine
status: done
started: 2026-10-31
finished: 2026-10-31
---

# board-offset-index — Imported boards: a per-Case byte-offset index and `board.json`

## Intent

Implement Option B of `docs/spec/2026-10-30-OME-1790-board-per-case-storage.md` so a 2-Case run
of a 330 MB Imported Board no longer reads and parses the whole `cases.json` on the Cases route.
The writer keeps `cases.json` byte for byte and adds `cases.offsets` plus `board.json`, both
written before `cases.json` (still the completion marker). The Cases route reads only the
selected prefix through the index, and picture admission reads `has_pictures` from
`board.json` instead of scanning every row.

## Owner decisions (2026-10-31, relayed at dispatch)

- **Q1 format: Option B** — keep `cases.json` byte-for-byte, add a per-Case byte-offset index
  and a small `board.json` (Case count, has-pictures flag), written before `cases.json`.
- **Q2 split: the wider scope (b)** — this ticket ships the writer, the reader, moves the Cases
  route onto the reader and moves picture admission onto `board.json`.
- **Q4 old bundles:** a bundle with no index falls back to the full read and logs a warning.
- **Out of scope:** the check-surface input lookup (Q3), ContractEval contract dedupe (Q5,
  OME-1675), the per-run budget (Q6, OME-1648/OME-1675). Aggregation stays with OME-1789.

## Owner decisions (2026-10-31, at review)

- **D1 CI bundle cache:** the goal is that CI rebuilds bundles with the new writer (`board.json`
  + `cases.offsets`) so the e2e replay lane runs the index path. No key is changed: both bundle
  keys are content hashes over `screamingface_engine/benchmarks/**` and
  `screamingface_engine_inspect/**` (`.github/workflows/screamingface-e2e-replay.yml:56`,
  `.github/workflows/screamingface-paid-benchmark-smoke.yml:90`), and this PR changes files in
  both folders, so both keys already miss and the bundles rebuild. The repo has never bumped
  these keys by hand; a literal would add nothing.
- **D2 grading reader:** OME-1789's grading reader stays separate for now (no `row(id)` on the
  port here). A follow-up moves grading onto `board_store` once both #1628 and this PR merge.

## Planned changes

- `src/screamingface_engine/benchmarks/board_store.py` (new, core): the format (encode), the
  `BoardStore` port, the indexed store and the legacy full-read store, `open_board`.
- `src/screamingface_engine/benchmarks/case_selection.py`: a count-aware board Cases handler.
- `src/screamingface_engine/benchmarks/picture_admission.py`: admission takes a flag.
- `src/screamingface_engine_inspect/prepare.py`: `_write_cases` writes `board.json` and
  `cases.offsets` before `cases.json`.
- `src/screamingface_engine_inspect/single_shot.py`: the imported-board route reads through
  the store; the envelope runs over the selected rows only.
- New tests only (append-only).

## Test plan

- Writer: `cases.json` bytes equal the pre-change `json.dumps(list)`; every offset slice parses
  to its row; non-ASCII, a single-row board; `board.json` fields; determinism; `board.json`
  and `cases.offsets` exist before `cases.json` is written.
- Store: head(N) equals the legacy slice for N = 1, mid, all; N = 0 / N > count refused; stale
  index (`cases_bytes` mismatch, truncated offsets) is a bounded error; no index → legacy
  fallback with a warning.
- Route: N rows served, envelope per selected row, admission uses `has_pictures` with no row
  scan; existing route/admission tests stay green unedited.
- Memory: peak RSS of the Cases route for a 2-Case selection on a 328 MB synthetic board,
  before vs after (scratchpad `mem/measure.py`).

## Acceptance

- Spec acceptance 2, 5, 6, 7 covered by unit tests; acceptance 3 measured locally (synthetic).
- `run_gates.py screamingface-engine --base origin/main` green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `tests/unit/test_board_store.py`,
  `tests/unit/test_board_cases_route.py`, `tests/unit/test_board_index_prepare.py`,
  `tests/unit/inspect/test_board_index_route.py` (all new). No prior test edited.
- **Commits:** a merge of `origin/main` (so the append-only gate compares against current
  main), then `perf(engine): read imported boards through a per-Case byte-offset index`.
- **Gates:** `run_gates.py screamingface-engine --base origin/main` — ALL GATES GREEN; inspect
  lane (`uv run --extra inspect pytest tests/unit/inspect`) 2817 passed;
  `packages/url4/scripts/check_module_size.py` — all capped modules within baseline.
  `board_store.py` 100% line+branch from its own tests.
- **Measurements** (local, macOS, synthetic FigQA-shaped board, 181 Cases, `cases.json`
  328,269,060 B; one Cases-route call, 2-Case selection, RSS sampled every 1 ms):
  - before (origin/main shape, `cases_handler(_cases(root))`): peak 998 MiB, +946 MiB over the
    52 MiB baseline, body 313.1 MiB, 254-275 ms (3 runs, identical peaks).
  - after (indexed): peak 62 MiB, +10 MiB, body 3.5 MiB, 2 ms (3 runs, identical).
  - after on a 90.7 MB board (50 Cases): +10 MiB as well, so the route's peak no longer grows
    with board size; the legacy fallback on the same board is +261 MiB.
  - legacy fallback on the 328 MB board (no index): +951 MiB, as before, with the warning.
  - index size: `cases.offsets` 2,896 B (181 x 16) + `board.json` 96 B.
  - writer time, back to back, best of 3: before 698-739 ms, after 699-726 ms (no
    measurable delta); `cases.json` sha256 unchanged (`dae6e6db...afe0`).
- **Deviations:**
  - The port exposes `case_count`, `has_pictures`, `head(count)` only. The spec's id-keyed
    `rows(ids)`/`row(id)` (aggregation, OME-1789) and `id_for_input` (check surface) are out of
    this scope, so they are not built yet.
  - `refuse_blind_models(node, rows)` is kept (prior tests and the hand-built route use it) and
    delegates to the new `refuse_blind_candidate(node, needs_pictures=...)`.
  - `single_shot._cases` is no longer on the imported route; it stays as the legacy reader's
    base and for its prior tests.
  - Envelope boards on the legacy fallback now envelope only the selected rows, so a broken
    Case outside the selection no longer fails a run that does not select it.
  - Not done here: full-image build time / image size (needs the benchmark image build), kind
    runs. No CI bundle-cache key bump: the content-hashed keys already change (D1).
  - Follow-up: move OME-1789 grading onto `board_store` after #1628 and this PR merge (D2).
