---
ticket: OME-1458
stack: screamingface-engine
status: done
started: 2026-10-07
finished: 2026-10-07
---

# importer-refuses-epochs — the inspect importer refuses a Task that asks each Case several times (PR 2 of 2)

## Intent

The inspect importer never reads a Task's `epochs`, so a Task that asks each Sample N times and
folds the N scores (MBPP, ZeroBench) would import and silently run once: a first-Attempt score
published as the eval's number. Until the Engine can run several Attempts per Case (the build
ticket, spec `docs/spec/2026-10-07-OME-1458-attempts-per-case.md` D12), the importer refuses any
Task declaring `epochs` > 1, naming the epoch count and the reducer. No published Benchmark
declares more than one epoch, so nothing already imported changes.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine_inspect/importer.py` — a Stage 1 reader
  that refuses `epochs` > 1 by name.
- `apps/screamingface-engine/src/screamingface_engine_inspect/import_replay.py` — call it first
  when reading the built Task's facts.
- `apps/screamingface-engine/docs/importing-an-inspect-eval.md` — the one-Attempt line now says
  the Task is refused.
- `apps/screamingface-engine/tests/unit/inspect/test_importer_refuses_epochs.py` — new.
- Close the OME-1458 mirror and both OME-1458 ledgers (this PR closes the ticket).

## Test plan

- RED first, through the real import child on a stand-in eval (the named-scores test pattern):
  - `epochs=2` with an any-match reducer (`pass_at_2`) is refused, naming `epochs=2` and the
    reducer: refused even though the build will accept it, because there is nowhere yet to send
    a second Attempt.
  - `epochs=5` with no reducer is refused naming inspect's default, `mean`.
  - `Epochs(1, "mode")` (lab_bench's shape) imports as today: one epoch is one Attempt.
  - No epochs imports as today.
- Every published Benchmark keeps importing: no published row's Task declares epochs > 1
  (checked: only cyse4_mitre_frr, coconot and lab_bench declare epochs, all at 1).

## Acceptance

- The four tests above green; every prior inspect unit test untouched and green.
- Engine gates green via `run_gates.py screamingface-engine`.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus the OME-1458 mirror and the spec ledger closed.
- **Commits:** 9507eaa75 feat(screamingface-engine): refuse an inspect Task that declares more than one epoch; the docs-close commit after it.
- **Gates:** `run_gates.py screamingface-engine` ALL GATES GREEN (append-only check, ruff check, ruff format, pyright, layering, full pytest with coverage ≥ 80%); the 4 new tests green through the real import child.
- **Deviations:** none. Owner-verify: none.
