---
ticket: OME-1269
stack: screamingface-engine
status: done
started: 2026-09-29
finished: 2026-09-29
---

# pubmedqa-board — import pubmedqa through its question filter (OME-1269, PR 2 of 3)

## Intent

Ship the `pubmedqa` board on the question filter from PR 1: the eval loads 1,000 labelled
questions and keeps the 500 on its bundled test list; the board keeps exactly those 500.
Spec: `docs/spec/2026-09-29-inspect-task-route-bake.md`.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine_inspect/{pins,prepare,boards}.py` —
  the importer's rows plus the catalogue prose and tier.
- `apps/screamingface-engine/tests/unit/inspect/test_benchmark_declaration.py`,
  `test_inspect_imported_boards.py` — registration plus one pin test.

## Test plan

Board registry tests; a pin test for the question filter, template and kept count; a free real bake
compared with inspect's own load.

## Acceptance

Ticket acceptance 4 for `pubmedqa`: 500 cases, ids equal to inspect's own load.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus this ledger and the mirror update.
- **Commits:** one on `OME-1269-pubmedqa-board`, stacked on `OME-1269-task-route-bake`.
- **Gates:** ruff check, ruff format --check, pyright (0 errors), check_layering OK,
  `pytest --cov` 4585 passed / 44 skipped, coverage 93.67%; inspect lane 461 passed.
- **Free real-data check (no token):** the importer writes the question-filter row with 500 cases.
  The production bake gives 500 cases; the bake's samples have exactly the ids of inspect's
  own `pubmedqa()` load, with the same input, target and choices. No row seed: upstream
  serves dataset order, and its answers are already mixed (first 50: 26 yes, 14 no, 10
  maybe; all 500: 276 / 169 / 55).
- **Deviations:** none. The importer wrote the pins import block in an order ruff rejects
  (`GSM8K_DATA_DIR`), fixed with `ruff check --fix`; that ordering gap in the importer
  predates this ticket.
- **Owner-verify:** a paid smoke run of `pubmedqa` is the owner's to press.
