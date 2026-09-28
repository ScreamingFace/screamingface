---
ticket: OME-1264
stack: screamingface-engine
status: done
started: 2026-09-23
finished: 2026-09-24
---

# OME-1264 — Importer detects MCQ by solver family, renders str scorer kwargs format-safe

## Intent

Two small importer gaps found while preparing the lab_bench board batch, fixed
ahead of it in their own PR (stacked on #1033):
1. `facts.mcq` keys on the scorer NAME (`== "choice"`), so an MCQ eval with its
   own choice-family scorer (lab_bench's `precision_choice`) reads as free-text
   and the generated board row carries `with_check_surface=True` — an OME-796
   violation (pass/fail feedback over options = elimination attack). MCQ-ness is
   the exam's SHAPE, declared by the `multiple_choice` solver, not by which
   scorer grades it — detect it there.
2. String scorer kwargs render via `!r` (single quotes), so the first eval with
   a str kwarg (`no_answer="Insufficient information…"`) emits a board row the
   `ruff format --check` gate rejects. Render str values with `json.dumps`
   (double quotes, still escape-safe).

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine_inspect/importer.py`
  - `introspect_task`: `mcq` = the Task's solver chain contains inspect's
    `multiple_choice` (registry name), replacing the scorer-name test
  - `_board_lines`: str kwarg values via `json.dumps`
- Tests appended in `tests/unit/inspect/test_inspect_importer.py`:
  - MCQ eval with a custom choice-family scorer → `mcq=True`, board row omits
    the check surface
  - str scorer kwarg renders double-quoted and the fragment survives
    `ast.parse` + the 100-col line check

## Test plan

- `_mcq_task` (choice scorer + multiple_choice) stays `mcq=True` (prior test)
- free-text task (no multiple_choice) stays `mcq=False` (prior test)
- NEW: multiple_choice + custom scorer → `mcq=True`; `with_check_surface` absent
- NEW: scorer kwarg `{"no_answer": "…"}` emits `"no_answer": "…"` (double quotes)

## Acceptance

- lab_bench tasks introspect with `mcq=True`; emitted rows carry no check surface
- All prior tests untouched and green; gates green (no append-only skip)

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned (`_solver_facts` returns a fifth
  `uses_multiple_choice` element; `_scorer_kwarg_literal` helper).
- **Commits:** the feature commit on `OME-1264-importer-mcq-family` (stacked on
  `OME-1264-data-files-features` / PR #1033).
- **Gates:** `run_gates.py screamingface-engine` ALL GREEN (append-only clean);
  inspect lane 234 passed. Verified live: all six text lab_bench tasks
  introspect with `mcq=True`.
- **Deviations:** first attempt put the conditional inside an f-string
  replacement field ending `!r` — the conversion applied to the WHOLE field,
  wrapping json output in repr; fixed via the explicit helper.
- Review finding — solver-only detection misclassified the mmlu wrapper family
  (`mmlu_multiple_choice` hides `multiple_choice()` from the registry walk);
  fixed with the or-rule (`uses_multiple_choice or scorer_name == "choice"`) +
  regression test.
