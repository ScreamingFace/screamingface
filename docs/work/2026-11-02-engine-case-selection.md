---
ticket: OME-1739
stack: screamingface-engine
status: done
started: 2026-11-02
finished: 2026-11-02
---

# engine-case-selection — the Engine serves, grades and echoes a fixed list of Case ids

## Intent

A researcher's routing study on LAB-Bench needs fixed development and held-out Case id lists
(for example `[3, 17, 42]`), and `limit=N` can only ever mean Cases 1 to N. This unit is the
Engine half of OME-1739 (PR 1 of 2): a `POST /v1/benchmarks/{id}/selection` route takes
`{"cases": [...]}`, checks every id, and returns the Benchmark resource whose recipe runs only
those Cases. The resource echoes `selected_case_ids` so the SDK (PR 2) can refuse an Engine
that ignored the selection. Stacked on #1629 (OME-1790 offset index). The id list rides
today's intent text (owner, 2026-11-02): a count stays `3`, an id list is `[3,17,42]`, and a
list equal to 1..N is written as the count, so every `limit=` recipe stays byte-identical.

## Planned changes

- NEW `apps/screamingface-engine/src/screamingface_engine/benchmarks/selection.py` —
  `CaseSelection`: first N or an explicit ascending id list; parse from and write to intent
  text; canonicalises 1..N to the count.
- `benchmarks/protocol.py` — `build_evaluation_protocol` and `early_result` take an int or a
  `CaseSelection`; the Cases, aggregate and early-result intents carry its text.
- `benchmarks/definition.py` — `Benchmark.protocol` / `resource` accept a selection;
  `resource(cases=…)` adds `selected_case_ids`.
- `benchmarks/grading_endpoints.py` — the aggregate intent parses into a selection; adapters
  receive the Case-id tuple instead of a count (owner, 2026-11-02).
- `benchmarks/shared_grading/incremental_routes.py`, `shared_grading/serving.py` — loaders
  and the hand-built aggregate take Case ids; the hand-built Cases route serves only the
  selected rows.
- `benchmarks/case_selection.py`, `benchmarks/board_store.py` — `rows(ids)` beside
  `head(count)`; each read row's `id` must equal its position.
- `screamingface_engine_inspect/single_shot.py`, `benchmarks/medxpert/definition.py` — the two
  builders and the imported aggregate faces read the selection.
- `rest/benchmarks.py` — the new POST selection route; GET `?limit=` untouched.

## Test plan

- `CaseSelection`: prefix canonicalisation (`[1,2,3]` → `3`), ascending order, refusal of 0,
  negatives, bools, duplicates, ids above the Benchmark's count, non-integer text.
- Protocol: a `limit=3` recipe is byte-identical to the one built from `[1,2,3]`; an id-list
  recipe carries `[3,17,42]` in all three intents and slices `0..3`.
- Cases routes (hand-built and board, indexed and legacy): serve exactly rows 3, 17, 42 in that
  order; a row whose `id` differs from its position is a contract error.
- Aggregate and early-result endpoints: the adapter receives `(3, 17, 42)`; an out-of-range or
  malformed list is refused before scoring.
- REST: POST returns `selected_case_ids` and an id-list recipe; 422 for out-of-range,
  duplicate, bool, non-integer (`"3)!/x"`), empty, more than 1,000 ids, or a missing body.

## Acceptance

- `POST /v1/benchmarks/{id}/selection {"cases": [3, 17, 42]}` returns a resource with
  `selected_case_count: 3`, `selected_case_ids: [3, 17, 42]`, and a recipe that serves and grades
  only those Cases.
- Every `GET ?limit=N` response and every published recipe is byte-identical to before.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `tests/unit/inspect/test_imported_case_selection_run.py`
  (end-to-end imported gsm8k run on Cases 2 and 3 with a stand-in model) and the prior-test
  edits below.
- **Commits:** see the branch (`feat(screamingface-engine): serve, grade and echo a fixed list
  of Case ids`).
- **Gates (relevant tests only, per the owner rule):** the 72 extra-less test files that import a
  touched module, 862 passed; the 47 inspect-lane files with the `inspect` extra, 1417 passed;
  ruff, ruff format and pyright clean on the 20 touched files; `check_layering.py` OK. Every
  registered Benchmark's resource (90 Benchmarks × 4 limits = 360) hashes identical to the base
  commit. Mutation check: reverting the imported aggregate to 1..N fails the end-to-end test.
- **Deviations:** the adapter contract change (count → Case-id tuple, owner-approved) needed
  five prior-test edits, not the three named at approval time: one assertion each in
  `test_async_aggregate_endpoint`, `test_benchmark_evaluation` (plus its adapter's type
  annotation) and `test_early_grade_safety`, and one call argument each in
  `test_shared_grading_serving` and the `test_single_turn_judged_imports` helper. Each moved from
  a count to the matching ids; what they check is unchanged. Found in review: a hand-written
  recipe's huge count would have been expanded into ids before the bounds check; `parse` now
  takes the Benchmark's size and refuses first (pinned by a test). Found at pre-push
  (whole-Engine pyright): `Benchmark.build` is typed `int | CaseSelection`, because builders
  still take the historic count; and #1629's stand-in board in `test_board_cases_route.py`
  gained a two-line `rows` so it still matches the `BoardStore` protocol (no assertion moved).
- **Review round 1 (#1636, 2026-11-03):** `IndexedBoard.rows()` now gives `head()`'s guarantees
  on the explicit-id path: exact 16-byte entry reads, the row read with one byte each side and
  required to sit between `[`/`,` and `,`/`]` (an index entry aimed at a nested object inside
  another row is refused), `_check_row` on the bytes (`type(id) is int`, id == position), and
  every `OSError`/`struct.error`/`ValueError` (short reads, bad UTF-8, bad JSON) mapped to
  `benchmark_unavailable`; `_check_ids` requires ascending, distinct ids (`rows((2, 2))` is a
  `ValueError`); `LegacyBoard` refuses a `true` id. `CaseSelection.of` checks the cap before
  listing duplicates and every id list in an error message shows at most ten ids. Pinned by
  `tests/unit/test_board_rows_hardening.py` (8) and one appended test in
  `test_case_selection_ids.py`. The five prior-test edits (count → Case-id tuple) are approved by
  Sergey Bershadsky (owner, review of 2026-11-03) and pinned in
  `.claude/test-change-approvals/OME-1739.json`; the append-only check passes against `a91ef670`
  with the manifest and fails without it. Gates: 151 passed, 1 skipped across the 7 selection,
  board-store and selection-route test files; ruff, ruff format, pyright and layering clean.
  Skipped (needs a scoring harness the serving tests lack): a MedXpert `/case-result` loader test
  on `[2, 3]`.
