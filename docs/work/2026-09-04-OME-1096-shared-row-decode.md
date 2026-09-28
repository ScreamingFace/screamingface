---
ticket: OME-1096
stack: screamingface-engine
status: done
started: 2026-09-04
finished: 2026-09-04
---

# OME-1096 — Share the row decode and index step between gdpval and healthbench

## Intent

Third code PR of the OME-1024 spine chain (after OME-1094/1095 goldens work and OME-1039's
declaration + failure ladder). The engine fans a benchmark run out over its selected cases and
collects one row per case; the aggregate step reads that array back — parse the JSON, check the
count, notice an outer error, file each row under its case id. That reader exists **twice**,
near byte-identical, because `gdpval/` was forked from `healthbench/` two weeks ago
(`_decode_rows`, `_index_rows`, `_index_row`, `_index_outer_error`, `_row_value`). Every fix
lands in one copy and drifts from the other. This unit extracts the reader into the spine once.

Purely mechanical: no grading, no scoring, no wording changes. The healthbench-worst30 golden
(157 cases, per-case statuses and failure codes pinned by OME-1094) is the proof nothing
observable moved.

## Design decisions (owner-approved in session, 2026-09-04)

**1. The row stays OPAQUE — no kind-tagged payload types in this unit.**

The ticket's 2026-09-03 review note asks the decoded row to carry inputs and answers as
kind-tagged payloads (`kind: "text"`). Deferred, deliberately, with owner approval:

- These five functions never open the envelope. They file a sealed board-decoded mapping under
  its case id; `case.input` / `case.output` are read one layer later by the board-owned
  `_candidate_fields` hook, which is OME-1097's seam, not this ticket's.
- The kind taxonomy is `OME-1103`'s decision (a design session, still Backlog, "No code in this
  ticket"). Inventing `TextPayload` here would answer that question by accident — the exact
  failure `OME-1103` warns about: *"Any decision made accidentally by the spine extraction (a
  text-only row shape frozen into `grade_case`) becomes a contract break later."*
- Keeping the row an opaque `Mapping` satisfies the note's actual requirement — nothing here
  hard-codes `answer: str` — while leaving all three kinds open. A payload type with no
  consumer would be dead scaffolding (YAGNI), and wiring one to a real consumer means editing
  `CaseGrader`'s hook signature, which is OME-1097's file boundary and would blow the ~300-line
  cap.

The invariant is recorded as an `INVARIANT:` anchor in the new module so a later agent does not
helpfully "improve" it into a typed row.

**2. Board-varying bits are injected at construction** — the OME-1039 `CaseGrader` precedent.
Exactly three things differ between the two copies:

| Injected | gdpval | healthbench | Why it must vary |
|---|---|---|---|
| `benchmark_label` | `"GDPval"` | `"HealthBench"` | appears in two `_decode_rows` error messages; texts stay byte-identical |
| `error_type` | `gdpval.AggregateError` | `healthbench.AggregateError` | keeps `pytest.raises(<board>.AggregateError)` meaning exactly what it means today |
| `decode_case_evaluation` | gdpval's | healthbench's | each board validates its own envelope schema |

Naming: `benchmark_label`, not `board_label` — "board" is prose-only vocabulary in this repo
(104 occurrences, all docstrings/comments, zero identifiers); `benchmark_` is the code noun
(`benchmark_id` ×61, `benchmark_revision` ×25). Not `benchmark_name` either: two Benchmarks
(`healthbench-worst30`, `healthbench-professional`) share the one value `"HealthBench"`, so a
`_name` beside the per-call `benchmark_id="healthbench-worst30"` would imply a 1:1 that does not
exist. `_label` marks it as display text. `error_type` rather than `error` because the field
holds a class, not an instance.

## Planned changes

- **new** `src/screamingface_engine/benchmarks/spine/rows.py` — `RowReader` frozen dataclass
  (`benchmark_label`, `error_type`, `decode_case_evaluation`) with the five extracted steps
  behind one public `index(raw_rows, case_ids) -> RowIndex` method; `RowIndex` is a small
  frozen dataclass carrying `(rows, collected_errors, grading_failures)` so the call site stops
  unpacking a bare 3-tuple.
- `src/screamingface_engine/benchmarks/gdpval/aggregate.py` — bind `_ROWS` at module bottom
  beside the existing `_GRADER`; delete the five copies.
- `src/screamingface_engine/benchmarks/healthbench/aggregate.py` — same; also deletes
  `_attach_collected_error` (a healthbench-only one-line wrapper whose `case_id is not None`
  guard is dead at its single call site — gdpval's inline `setdefault().append()` is the
  behaviour both keep).
- **new** `tests/unit/test_spine_row_reader.py` — one test per decode branch through the shared
  module.

NOT touched (ticket's explicit boundary): `aggregation.py`, `contract.py`, `spine/grading.py`.
No schema/model change, so stack rule S1 (migrations) does not apply.

## Test plan (RED first)

`tests/unit/test_spine_row_reader.py`, driving a `RowReader` built on a stub decoder so the
spine's own branches are covered without either board's envelope schema:

- happy path — two rows file under their selected case ids, in order
- raw payload is not JSON → `error_type` raised, message carries `benchmark_label`
- raw payload is a JSON object, not an array → `error_type`, label in message
- more rows than selected cases → `error_type` (the count guard)
- a row that is a JSON *string* is parsed (the `_row_value` double-encode path)
- a row that is not an object → `error_type` "must be an object"
- a row that is a malformed JSON string → `error_type` "is not JSON"
- outer error row with no `case_id` → retained as an orphan collected error (INVARIANT: the
  cause is never dropped — this is what made the first live smoke run debuggable)
- outer error row with a matching `case_id` → filed as the case's row
- outer error row claiming a different `case_id` → `error_type` (identity guard)
- outer error that is not a mapping → `error_type`
- a row whose decoder reports a grading error → lands in `grading_failures`, not `rows`
- a row whose `case_id` disagrees with the selected case → `error_type`
- decoder raising `ValueError`/`TypeError` → wrapped as `error_type` with the position
- INVARIANT test: `benchmark_label` and `error_type` are honoured per instance — two readers
  built with different values raise their own class with their own wording

**Append-only:** every existing gdpval and healthbench test must pass **unmodified**. That is
the real proof of this extraction — if a board test needs an edit, the extraction changed
observable behaviour and that is a STOP.

## Acceptance

- The five decode/index functions exist once in the repo (`spine/rows.py`).
- Both copies deleted; both aggregates call the shared reader.
- Every pre-existing engine test green, unmodified.
- `run_gates.py screamingface-engine` all green.
- Diff under ~300 lines.
- Free tests only — no paid model run. (healthbench-worst30 golden replay is a client-side
  e2e lane, run separately by the owner.)

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `benchmarks/spine/__init__.py` (re-export `RowReader` +
  `RowIndex`, matching how OME-1039 re-exported `CaseGrader`) and the `docs/tasks/` mirror.
  New tests: `test_spine_row_reader.py` (20).
- **Commits:** single commit on `OME-1096-shared-row-decode` —
  `refactor(screamingface-engine): read benchmark rows through one shared spine reader`.
- **Gates:** `run_gates.py screamingface-engine` **ALL GREEN** — append-only test check,
  ruff check, ruff format, pyright, layering, pytest **2340 passed / 5 skipped**, cov ≥80%.
- **Diff:** modified files +28 / −222; new module 215 lines, new test 232. The extraction
  itself is well under the ~300-line cap; the two new files are the shared module and its
  tests, which the ticket asks for explicitly.
- **Deviations:**
  - **Kind-tagged payload types deferred to OME-1097/OME-1103, with owner approval in
    session.** Reasoning recorded in "Design decisions" above. The row is opaque and a
    test (`test_the_reader_never_reads_a_case_input_or_answer`) pins that as an invariant,
    so a later agent cannot quietly turn it into a typed `answer: str` row.
  - **`RowIndex` result type** rather than the bare 3-tuple both boards unpacked. Five
    lines; the call sites now read `indexed.rows` / `indexed.collected_errors` /
    `indexed.grading_failures` instead of positional unpacking. Declared in the plan.
  - **healthbench's `_attach_collected_error` deleted, not extracted.** It was a
    healthbench-only one-line wrapper whose `if case_id is not None` guard is dead at its
    single call site (the caller has already established the id). gdpval's inline
    `setdefault().append()` is the behaviour both boards now share — no behaviour change,
    confirmed by healthbench's own orphan-error test passing unmodified.
  - **Remote is `upstream`, not `origin`.** The repo `CLAUDE.md` worktree recipe says
    `git fetch origin` / `origin/main`, but this clone has only `upstream`
    (`github.com/ScreamingFace/screamingface`). Branched from `upstream/main`. Worth a
    one-line fix to the recipe in `CLAUDE.md` — flagged, not changed (process tooling is
    owner territory).
  - **No existing test was modified** — `git status` shows only the two aggregate files as
    modified, and the append-only gate passed. That is the extraction's real proof.
- **Status:** DONE (pending review + merge).
