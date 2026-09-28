---
ticket: OME-1112
stack: screamingface-engine
status: done
started: 2026-09-15
finished: 2026-09-16
---

# OME-1112 — Benchmark catalogue records where each benchmark came from

## Intent

Give every benchmark registration one declared provenance fact — `origin:
"screamingface" | "inspect_evals"` — so downstream surfaces (SDK grouping in
OME-1114, the imported board in OME-1115) read where a board came from instead
of guessing from naming. The field rides the existing catalogue path: `Benchmark`
record → `catalog_entry()` → `GET /v1/benchmarks`. Nothing else moves.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/benchmarks/definition.py`
  — new `BenchmarkOrigin` literal type + `origin` field on `Benchmark`
  (default `"screamingface"`, validated in `__post_init__`), emitted
  unconditionally from `_metadata()` so both the catalogue entry and the full
  resource carry it.
- New test file `apps/screamingface-engine/tests/unit/test_benchmark_origin.py`.

Design note: the ticket's default-field shape was chosen over a required field.
A required field would force edits to 7 prior-cycle `Benchmark(...)` test
constructions (test-preservation rule), and the OME-1039 no-defaults invariant
guards score-changing declarations — provenance defaulting to `screamingface`
is honest for every existing board, and the import lane (OME-1115) must pass
`origin="inspect_evals"` explicitly anyway.

## Test plan

- Default: a `Benchmark` built without `origin` reports
  `origin == "screamingface"` in `catalog_entry()` and `resource()`.
- Explicit: `origin="inspect_evals"` registered and read back through
  `GET /v1/benchmarks` (API-level, per ticket acceptance).
- Error: an undeclared origin value (e.g. `"huggingface"`) is refused by name
  at construction.
- Invariant: every builtin board's catalogue entry carries
  `origin == "screamingface"`.

## Acceptance

- `/v1/benchmarks` returns `origin` for every installed board.
- A benchmark registered with `origin="inspect_evals"` reads back through the
  API with that value.
- All prior tests green and unmodified.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus one owner-approved edit to the prior
  exact-shape contract test (`tests/unit/test_benchmark_foundation.py` — inserted
  `"origin": "screamingface"` into the pinned catalogue dict; approved 2026-09-16).
- **Commits:** `feat(engine): record each benchmark's origin in the catalogue`
  (sha in the PR / Linear close comment).
- **Gates:** run_gates.py screamingface-engine ALL GREEN (2877+4 passed, 9
  skipped, coverage 93%); append-only skip owner-approved for the contract-pin edit.
- **Deviations:** none from the ticket. The earlier idea of a required
  no-default field was dropped: it would have forced edits to 7 prior-cycle
  test constructions, and the ticket's default shape is honest for every
  existing board.
