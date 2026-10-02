---
ticket: OME-1450
stack: url4
status: in_progress
started: 2026-10-01
finished:
---

# remove-jobrunner-profile-port — make the shared scheduling port selector-less

## Intent

Remove the retired Profile selector from the shared URL4 `JobRunner.schedule` contract. Stage D
already refuses explicit selectors and Engine no longer creates selector-bearing work; retaining the
port parameter advertises a capability that no supported caller may use. The coordinated Engine
implementation change is tracked by `OME-1449`.

## Planned changes

- `packages/url4/src/url4/streaming/interfaces/jobs.py` — remove the `profile` keyword.
- URL4 package tests — add a structural signature contract and keep all prior behavior green.
- Coordinated Engine adapters/callers — satisfy the selector-less port under `OME-1449`.

## Test plan

- Add a failing signature assertion that `profile` is absent from `JobRunner.schedule`.
- Run the focused URL4 streaming tests and then the complete `url4` quality gate.
- Run the coordinated Engine type check and full gate to prove every implementation conforms.

## Acceptance

- The shared port cannot carry a Profile selector.
- URL4 package and ScreamingFace Engine gates pass together.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** removed `profile` from
  `packages/url4/src/url4/streaming/interfaces/jobs.py::JobRunner.schedule` and added the structural
  absence assertion to `packages/url4/tests/unit/test_jobs_port.py`; Engine adapters were updated in
  the coordinated `OME-1449` leaf.
- **Commits:** this commit — `refactor(engine): remove retired profile carrier`.
- **Gates:** focused signature test passed; direct full suite 1360 passed; configured URL4 gate
  passed append-only, Ruff, Ruff format, Pyright and the 95%-minimum coverage suite.
- **Deviations:** none in the URL4 leaf.
