---
ticket: OME-1188
stack: screamingface
status: in_progress
started: 2026-09-11
finished:
---

# OME-1188 — Client runtime OpenTelemetry dependency parity

## Intent

Record the user-authorized packaging ticket for the dependency mismatch introduced
by PRs 905 and 909 and caught by Client CI on PR 918. The user has now authorized
implementation and a draft PR.

## Planned changes

- Add the two missing requirements to the Client runtime extra and refresh its lockfile.
- Maintain the task mirror and this ledger through the separate fix PR.

## Test plan

- Reproduce the existing runtime dependency-parity failure before implementation.
- Run full screamingface gates after the packaging fix.

## Acceptance

- Runtime extra matches bundled apps' requirements and required CI passes.
- Base Client dependencies and tracing behavior are unchanged.

## Outcome

- Actual files: Client pyproject and lockfile, spec, plan, task mirror, and this ledger.
- RED: the unchanged runtime dependency-parity test failed on both missing OTel requirements.
- GREEN: that same test passes after adding the requirements; no tests were modified.
- Lockfile: eight new OTel/protobuf dependencies; no existing package version changes.
- Gates: `run_gates.py screamingface` reports ALL GATES GREEN, including full pytest
  with >=95% coverage, lint, formatting, pyright, notebook checks, build and distribution checks.
- Additional checks: `uv lock --check`; built wheel metadata restricts both new requirements
  to the runtime extra; `git diff --check`.
- Environment: the first gate attempt lacked the notebook extra; installed it with
  `uv sync --extra notebook`, matching CI, and reran all gates successfully.
- Wisdom: this is the minimal packaging repair; reuses existing regression coverage,
  adds no application code, changes no base requirements or telemetry configuration,
  and introduces no secrets, schema changes, or public API changes. Confidence >=95%.
- Commit: `fix(screamingface): include bundled runtime tracing dependencies`, Refs: OME-1188.
- Deviations: used the existing failing regression rather than duplicating its assertions.
- Gate log: `.docs/OME-1188-gates.log` (local).
- Draft PR delivery only; issue remains open until review and merge.
