---
ticket: OME-1246
stack: screamingface-engine
status: done
started: 2026-09-21
finished: 2026-09-21
---

# OME-1246 — Declare contracteval's failure codes in the engine vocabulary

## Intent

ContractEval (PR #984) landed in flight with the OME-1233 vocabulary close, so its
two failure codes — `polarity_mismatch` and `contracteval_grading_failed` — never
joined `DECLARED_FAILURE_CODES`. The `Failure` validator refuses undeclared codes,
so a run that should publish a failed case crashes instead;
`test_contracteval_aggregate.py::TestPolarityAgreement` is red on `main` and blocks
every engine push through the pre-push gate.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/benchmarks/contract.py` —
  append both codes to `DECLARED_FAILURE_CODES`.
- `apps/screamingface-engine/tests/unit/test_failure_classes.py` — extend the
  exact-set change-detector (`test_the_declared_vocabulary_is_exactly_the_agreed_set`)
  with the same two codes; that test exists precisely to make vocabulary additions
  deliberate.
- `packages/screamingface/src/screamingface/_report_primitives.py` — mirror both
  codes. Not a follow-up after all: `test_failure_code_conformance.py` (both sides,
  OME-1235) pins the engine and SDK copies equal, so the two files can only move in
  ONE PR — a split would leave whichever side lands first permanently red.

## Test plan

- RED already exists on `main`: the polarity-agreement test crashes on the
  undeclared code. GREEN = it passes with the codes declared.
- The exact-set pin keeps the addition deliberate and greppable.

## Acceptance

- Full engine suite green (the pre-existing red is gone); pre-push gate passes.
- Both copies updated together (the conformance test forces it); the PyPI release
  ordering note (new code = SDK release first for published reports) rides the
  ticket for the deploy sequence.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned (engine set + change-detector + SDK mirror + docs).
- **Commits:** fa8bbe85 — fix(screamingface-engine): declare contracteval's failure
  codes so a failed case reports instead of crashing (+ the close-docs commit).
- **Gates:** engine pre-push gate green (3,301 passed incl. the previously-red
  polarity test); SDK conformance test green both sides; review verdict Merge,
  zero blockers (PR #1002).
- **Deviations:** (1) modified one prior test — the exact-set change-detector —
  which is that test's designed purpose (owner-approved unblock); (2) SDK mirror
  included in this PR rather than a follow-up: the OME-1235 conformance test pins
  both lists equal, so a split was impossible.
