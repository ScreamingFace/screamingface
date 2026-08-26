---
ticket: OME-924
stack: screamingface-engine
status: in_progress
started: 2026-08-26
finished:
---

# OME-924 — Preserve upstream grading errors in model-graded benchmarks

## Intent

A judge failure inside a model-graded benchmark (DRACO, HealthBench) was collected by
url4's default `on_error="collect"` into the inner criterion/rubric fan-out, then decoded
by the case-evaluation route as a typed grading record — surfacing as
`draco_grading_failed: "DRACO Case evaluation contains an invalid Criterion envelope"` and
swallowing the real upstream failure (e.g. OpenRouter 429). Live incident: GitHub
ScreamingFace/screamingface#740 (Linear OME-993). This unit makes the original error reach
the shared `preserve_candidate_outcome()` boundary and render with its own code/message/
retryability, so a billed run ends in scores or an honest, actionable grading error.

## Planned changes

- `packages/url4/src/url4/dag/nodes.py` — `_error_payload` keeps the exception's `code`
  and `permanent` (rendered as `retryable`) beside kind/message.
- `apps/screamingface-engine/.../benchmarks/draco/exam.py` — inner criteria fan-out
  `on_error="fail"`.
- `apps/screamingface-engine/.../benchmarks/healthbench/exam.py` — inner rubric-item
  fan-out `on_error="fail"`.
- Tests: url4 collect-payload fidelity; engine aggregate/protocol/e2e judge-429
  regression; update pinned draco/healthbench protocol hashes and OME-962 e2e assertions.

## Test plan

- url4 unit: a collected `ResolutionError(code, permanent)` row carries code + retryable;
  a plain exception keeps the legacy kind/message payload.
- Engine: DRACO and HealthBench aggregates render a grading error's code/retryable/
  message; a permanent error keeps `retryable=False`; a legacy payload falls back to the
  benchmark default code.
- Engine protocol: rendered DRACO and HealthBench protocols carry exactly one
  `;iteration.on_error=fail` (the inner fan-out).
- Engine e2e: full DRACO board with a scripted gateway that 429s the judge → the case
  failure is `stage=grading`, `code=rate_limited`, `retryable=True`, original message,
  candidate output preserved, and never "invalid Criterion envelope".
- Regression: `pytest tests/unit` (engine), `tests/unit` (url4), SDK
  `test_benchmark_compilation.py` + `test_draco_vertical_slice.py`; ruff + pyright clean.

## Acceptance

- Simulated judge 429 in DRACO reports `rate_limited`, preserves the original message and
  `retryable=true`, and does not report an invalid Criterion envelope.
- HealthBench has equivalent behavior for a failed rubric-item judge call.
- The candidate answer is retained and the affected case remains unscored.
- Permanent judge failures retain their original classification (`retryable=false`).
- Successful grading behavior is unchanged (pinned protocol hashes updated deliberately;
  DRACO revision hash `66a463248586b277` is untouched — the revision input tuple is
  unchanged).
- Behavior is independent of the outer case-iteration concurrency.
- Cross-benchmark regression tests cover DRACO and HealthBench.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
  - `packages/url4/src/url4/dag/nodes.py` — `_error_payload` preserves `code` + `retryable`
  - `packages/url4/tests/unit/test_iteration.py` — collect-payload fidelity tests
  - `apps/screamingface-engine/src/screamingface_engine/benchmarks/draco/exam.py` — `on_error="fail"` on the criteria fan-out
  - `apps/screamingface-engine/src/screamingface_engine/benchmarks/healthbench/exam.py` — `on_error="fail"` on the rubric-item fan-out
  - `apps/screamingface-engine/tests/unit/test_grading_error_integrity.py` — new cross-benchmark regression suite (aggregate, protocol render, full DRACO e2e judge-429)
  - `apps/screamingface-engine/tests/unit/test_benchmark_protocol.py` — updated pinned hashes + payload-shape assertions
  - `packages/screamingface/tests/e2e/test_failures.py` — updated OME-962 assertions/docstring to the preserved code/retryable behavior
  - `docs/work/2026-08-26-OME-924-preserve-grading-errors.md`, `docs/tasks/2026-08-26-OME-924-preserve-grading-errors.md`
- **Commits:**
  - `e102c9a0` — fix(url4): preserve code and retryable in collected error payloads
  - `cea8d529` — fix(screamingface-engine): fail fast benchmark grading fan-outs so upstream errors survive
- **Verification:** engine `tests/unit` 2026 passed / 5 skipped; url4 `tests/unit` 752 passed; SDK `test_benchmark_compilation.py` + `test_draco_vertical_slice.py` 33 passed; ruff + pyright clean on all changed files.
