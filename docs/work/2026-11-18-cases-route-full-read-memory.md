---
ticket: OME-1961
stack: screamingface-engine
status: done
started: 2026-11-18
finished: 2026-11-18
---

# cases-route-full-read-memory — a full-set Cases read fits the run's memory budget

## Intent

A run that takes every Case of a large Imported Benchmark is killed by its own memory budget
before the first model call. Measured on EnigmaEval
([PR 1833](https://github.com/ScreamingFace/screamingface/pull/1833), 1,158 Cases, `cases.json`
399,892,129 bytes) inside the linux/amd64 Engine image: the Cases route peaks at 5,048 MiB
against the 2,560 MiB `memoryLimitMi`, and under a 2,560 MiB container limit the process is
OOM-killed (exit 137).

Cause: `IndexedBoard.head` decodes the selected bytes into one Python string and then builds a
second, bracketed copy. Python stores a string at the width of its widest character, and one
EnigmaEval Case holds U+1F815, so the 381-million-character string costs 4 bytes a character:
1,525 MiB a copy instead of 381. Any large Benchmark with one such character has the same
problem; a small selection does not.

Fix: the indexed store serves each selected row with every non-ASCII character written as its
JSON `\uXXXX` escape, so the served text is ASCII (1 byte a character) and holds the same JSON
value. Nothing downstream moves: url4's `parse_collection` re-serialises each Case with
`json.dumps`, which escapes non-ASCII already, so the Case texts a run fans out are byte for
byte the same.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/benchmarks/board_store.py`: `head` reads
  row by row through the loop `rows` already uses (one row in flight, no board-sized `bytes`
  beside the text); both serve rows through one ASCII-escaping helper; the module and
  `BoardStore.head` docstrings say "same JSON value, ASCII text" where they said "byte-identical".
- `apps/screamingface-engine/tests/unit/test_board_store.py`: new tests (below); the prior
  `test_head_equals_the_legacy_slice` compares bytes of non-ASCII rows and must change to compare
  values. That edit needs an owner approval entry in `.claude/test-change-approvals/`.
- `LegacyBoard` (bundles with no index) is left as it is: it parses the whole file by design.

## Test plan

- A row with BMP and astral characters is served as ASCII and parses back to the same rows, for
  `head` and for `rows`.
- An all-ASCII Benchmark is served byte for byte as written (no change for most Benchmarks).
- url4's `parse_collection` gives the same item texts for the served text as for the file's own
  bytes: the invariant that makes the change invisible downstream.
- Memory: serving a Benchmark that holds one astral character peaks under 3x the file size
  (tracemalloc); the old path peaks at 13x.
- Every prior refusal test (truncated files, shifted offsets, nested objects, invalid UTF-8)
  stays green unmodified.

## Acceptance

- Full-set EnigmaEval read (1,158 Cases) through the real route plus `parse_collection`, in the
  linux/amd64 image: peak resident memory at most 1,280 MiB (half the budget), and it completes
  under a 2,560 MiB container limit.
- The hash over all 1,158 item texts from `parse_collection` equals the old path's.

## Outcome

- **Actual files:** as planned, plus one new module: the ASCII helper lives in
  `apps/screamingface-engine/src/screamingface_engine/benchmarks/ascii_json.py`, not inside
  `board_store.py`, to keep that file under 450 lines. New test file
  `tests/unit/test_board_store_ascii_serving.py` (8 tests). The prior-test edit is recorded in
  `.claude/test-change-approvals/OME-1961.json`.
- **Measured (linux/amd64 seal image, bundle built from PR 1833's head, 1,158 Cases, real route
  plus url4's `parse_collection`):**

  | Cases (prefix) | Before | After |
  |---|---|---|
  | 300 | 1,195 MiB | 426 MiB |
  | 500 | 1,633 MiB | not measured |
  | 700 | 3,680 MiB | not measured |
  | 1,158 | 5,048 MiB, OOM-killed under a 2,560 MiB limit | 840 MiB, completes under the limit |

  The hash over all 1,158 item texts is `ee041c10360ccc2d` before and after (300 Cases:
  `6f49f2a433f3ffa8` both). Escaping only the characters above U+FFFF was tried and rejected:
  2,328 MiB at 1,158 Cases.
- **Gates:** the 8 store and Cases-route test files (`test_board_store_ascii_serving`,
  `test_board_store`, `test_board_rows_hardening`, `test_board_cases_route`,
  `test_board_integrity`, `test_board_modalities`, `test_board_index_prepare`,
  `test_selected_case_routes`): 173 passed. ruff and pyright clean on the 5 touched Python
  files. The pre-push gate (append-only check, ruff, pyright, layering, the full Engine suite
  with coverage) was green on the first push.
- **Deviations:** `head` no longer does one contiguous read; it makes one read per Case, like
  `rows`. Acceptance target was 1,280 MiB; measured 840 MiB.
- **Owner-verify:** a full paid EnigmaEval run on a real Runner; the measurement here ran under
  emulation on a Mac and stops after url4's parse.
