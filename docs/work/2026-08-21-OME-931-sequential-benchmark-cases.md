---
ticket: OME-931
stack: screamingface-engine
status: done
started: 2026-08-21
finished: 2026-08-21
---

# OME-931 — evaluate benchmark cases sequentially

## Intent

Make progress and resource use Case-oriented by admitting only one outer benchmark Case at a
time. URL4 already provides the required per-iteration bound; the Engine-owned shared benchmark
protocol must select it explicitly.

## Planned changes

- `docs/tasks/2026-08-21-OME-931-sequential-benchmark-cases.md`
- `docs/spec/2026-08-21-OME-931-sequential-benchmark-cases.md`
- `docs/plan/2026-08-21-OME-931-sequential-benchmark-cases.md`
- `docs/work/2026-08-21-OME-931-sequential-benchmark-cases.md`
- `apps/screamingface-engine/src/screamingface_engine/benchmarks/protocol.py`
- `apps/screamingface-engine/tests/unit/test_benchmark_protocol.py`
- `apps/screamingface-engine/tests/unit/test_benchmark_protocol.py` canonical URL4 byte pins.

## Test plan

- RED: execute several Cases through the shared protocol with an asynchronous endpoint and prove
  that no two complete Case subtrees overlap.
- Assert the rendered protocol carries exactly the outer `iteration.concurrency=1` directive.
- Preserve selected Case order and failure collection.
- Update deliberate URL4 byte pins while proving benchmark revisions remain unchanged.
- Run focused benchmark protocol/definition tests, then the full `screamingface-engine` gate.

## Acceptance

- At most one outer Case evaluation is active per benchmark run.
- A Case's candidate invocation, grading, and result construction complete or fail before the
  next Case begins.
- Nested concurrency inside one Case and concurrency across separate runs are unchanged.
- Registered built-in benchmark revisions remain unchanged because the scoring contract is
  unchanged; their rendered URL4 recipe hashes move.
- The full Engine quality gate passes.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** all planned files — four SDLC artifacts, the shared Engine benchmark
  protocol, and its unit test. No URL4 or Scoreboard files changed.
- **Commits:** pending — `fix(screamingface-engine): serialize benchmark cases`, landing with
  this ledger update.
- **Gates:** focused protocol/definition set: 37 passed; full Engine gate GREEN — ruff check,
  ruff format, pyright, layering, and pytest. Independent full test evidence: 1993 passed,
  6 skipped, 93.38% coverage (80% required).
- **Deviations:** the initial design proposed advancing `EVALUATION_PROTOCOL_REVISION`. Frozen
  identity tests and the benchmark-registration spec established that benchmark revision names
  the thing measured, not operational scheduling, so revisions remain stable and only rendered
  URL4 SHA pins moved. The append-only precheck was skipped with the owner's explicit approval
  to update those three exact byte pins; every substantive quality gate ran unchanged and green.
