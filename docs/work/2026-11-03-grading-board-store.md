---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: screamingface-engine
status: done
started: 2026-11-03
finished: 2026-11-03
---

# grading-board-store — imported-board grading reads the selected Cases through the offset index

## Intent

Follow-up to OME-1789 (#1628, `read_selected_cases` streams `cases.json`) and OME-1790 (#1629,
the per-Case offset index in `benchmarks/board_store.py`). Aggregation still streams the whole
`cases.json` to find a run's selected rows: O(board) I/O and parse for a 2-Case run on a 330 MB
picture board. When the bundle carries the offset index, grading now seeks to each selected
Case instead: O(selected) reads, peak memory proportional to the selection. Boards without an
index keep #1628's streaming path. Owner-approved 2026-11-03 (Sergey); branch only, no PR yet.

## Planned changes

- `benchmarks/board_store.py`: an id-keyed read on `IndexedBoard` (`rows(case_ids)`), one offset
  entry plus one row's bytes per Case, validated like `head` (bounded `benchmark_unavailable`
  on a mismatched index). Additive; the `BoardStore` Protocol (the Cases route's port) is
  untouched, as are `board.json`, `open_board`'s decision and picture admission (#1645).
- `benchmarks/shared_grading/case_grades.py`: `read_selected_cases` asks `open_board` for the
  index; an indexed board is read by id, anything `open_board` would read whole falls through
  to the streaming reader. Going through `open_board` keeps #1645's v1/v2 decision the only one.
- `tests/unit/test_grading_board_store.py` (new, append-only).

## Test plan

- Equivalence with the streaming reader on the same rows, indexed vs index-less: prefix,
  non-prefix (181, 7, 90), duplicates, out-of-range ids (0, -1, count+1), empty selection,
  a row with no usable input — same `SelectedCase`s or the same error text.
- Corrupt index (stale size, shifted offsets, wrong id at an entry, truncated offsets, bad
  board.json) → the bounded `benchmark_unavailable`, never wrong rows.
- tracemalloc: peak scales with the selection, not the board, and stays well under the
  streaming reader's peak.

## Acceptance

- `run_gates.py screamingface-engine --base origin/main` green, no skip flags.
- Trial merge with `origin/OME-1803-pdf-admission` reports no textual conflict.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned — `board_store.py` (+`IndexedBoard.rows`, `_read_row`;
  `_check_row` now returns the parsed row), `shared_grading/case_grades.py`
  (`read_selected_cases` dispatches; `_indexed_board`, `_streamed_rows`), new
  `tests/unit/test_grading_board_store.py` (30 tests).
- **Commits:** see branch `grading-board-store` (single commit).
- **Gates:** `run_gates.py screamingface-engine --base origin/main` → ALL GATES GREEN.
- **Measured peaks (tracemalloc, ~100 KB rows):** indexed, 2 Cases: 512 KB on 10/20/40 MB
  boards alike; indexed, 20 Cases: 2.3 MB; streamed (#1628), 2 Cases: 5.6-5.7 MB.
- **Deviations:** a row with no `id` is admitted by the index but never filed by the streamed
  reader, so `read_selected_cases` re-applies the streamed filter (int id == Case id) to
  indexed rows. `IndexedBoard.rows` is additive and off the `BoardStore` Protocol (the Cases
  route's port). Trial merge with `origin/OME-1803-pdf-admission`: see the commit's report.
