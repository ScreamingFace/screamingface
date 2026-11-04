---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: screamingface-engine
status: done
started: 2026-11-03
finished: 2026-11-04
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

## Update 2026-11-04 — merged with #1636 (OME-1739)

#1636 added `IndexedBoard.rows(Sequence[int]) -> str` for the Cases route, proven by a walk
from Case 1. A check of only the selected entries cannot catch its nested-object forgery
(`{"id":3}` inside another row), so this branch's seek-per-id reader was wrong.

- **Resolution (owner direction):** one validated read path, `IndexedBoard._walk`, behind two
  names. `rows(ids) -> str` keeps #1636's name and signature exactly. `rows_by_id(ids) ->
  dict[int, dict]` is grading's accessor. The branch's `_read_row` is gone, and
  `_check_row` returns the row it already parsed.
- **Correction:** grading's indexed read is **I/O O(largest selected id), memory O(selected)**,
  not O(selected) I/O as the Outcome above says.
- **Tests:** owner-approved 2026-11-04 (Sergey). The `rows(...)` dict test now calls
  `rows_by_id`. `test_only_the_selected_entries_are_checked` is inverted to
  `test_a_broken_entry_below_the_largest_selected_id_is_refused`. Recorded in
  `.claude/test-change-approvals/grading-board-store.json`. Appended: parity tests showing
  `rows_by_id` and `read_selected_cases` refuse #1636's nested `{"id":3}` and `true`-id
  tampers exactly as `rows()` does.
- **Measured peaks (tracemalloc, ~100 KB rows, selection (90, 7)):**

  | Board | Indexed, 2 Cases | Streamed, 2 Cases |
  |---|---|---|
  | 100 Cases, 10 MB | 700 KiB | 5465 KiB |
  | 200 Cases, 20 MB | 698 KiB | 5540 KiB |
  | 400 Cases, 40 MB | 698 KiB | 5565 KiB |

  Indexed, 20 Cases (300..319) on 400 Cases: 2391 KiB. The 2-Case peak rose from 512 KB to
  about 700 KiB because the walk has one unselected tile and its parse in flight. It is still
  flat across board sizes.
