---
ticket: OME-1069
stack: screamingface-engine
status: in_progress
started: 2026-09-01
finished:
---

# OME-1069 — Runner traceability and logging layer (k8s mode)

## Intent

The run-mode Job process (`screamingface-engine run`) is nearly silent in its own logs: five
warning-only `_logger` calls, no lifecycle, no outcome, no correlation. An operator reading
`kubectl logs <runner-pod>` cannot tell what run a line belongs to, whether it succeeded, or
how it maps to the CloudEvents stream. This unit gives the runner a structured, correlated
logging layer: every process log line carries `topic` + W3C `trace_id`, the runner logs its
lifecycle (boot, world resolution, start, terminal outcome, summary), and the final summary
line is the operator's one-stop answer. The CloudEvents stream remains the source of truth;
the process logs point at it.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/logs.py` — `run_context` ContextVar,
  `RunContextFilter`, `%(run_context)s` in the format string (renders empty when unbound).
- `apps/screamingface-engine/src/screamingface_engine/runner/summary.py` (new) — the
  `RunSummary` dataclass (exact-only: cost is the subtree total or `None`, never a false zero).
- `apps/screamingface-engine/src/screamingface_engine/runner/executor.py` — record the run's
  summary in `execute()` (outcome, trace_id, cost, cache counters, bridge overflow stats);
  expose `last_summary()`.
- `apps/screamingface-engine/src/screamingface_engine/runner/operation_capture.py` — delegate
  `last_summary()` to the inner executor.
- `apps/screamingface-engine/src/screamingface_engine/runner/main.py` — boot log (sanitized),
  bind `run_scope(topic, trace_id)`, world-resolution log, terminal + summary logs.
- Tests: run-context filter/format, executor summary (success/failure/unexecuted), wrapper
  delegation, `_log_terminal` rendering.

## Test plan

- The run-context filter appends `topic=`/`trace_id=` only inside a bound scope; unbound
  records render unchanged (existing `test_logs_configuration.py` must stay green).
- `Url4Executor.last_summary()`: `None` before any execute; `succeeded` with exact cost and
  cache counters after a completed run; `failed` with error code/type after a raising run;
  `stopped` on cancellation.
- `OperationCapturingExecutor.last_summary()` delegates to the inner executor.
- `_log_terminal`: renders the finished line and the summary line on success; omits cost/cache
  on failure; warns when no summary exists.

## Acceptance

- Every runner process log line inside a run carries `topic=` and (when known) `trace_id=`.
- The runner logs boot, world, start, terminal outcome, and a final summary line.
- The summary line's `trace_id` is exactly the one on the stream frames (recorded from the
  `TraceContext` the executor receives).
- No url4 expression, NATS credential, identity, or provider content is ever logged.
- All existing gates pass (ruff, pyright, layering, pytest).

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** `logs.py` (run-context machinery), `runner/summary.py` (new), `runner/executor.py`
  (summary recording + `last_summary()`), `runner/operation_capture.py` (delegation),
  `runner/main.py` (boot/world/terminal/summary logs), `tests/unit/test_logs_configuration.py`
  (run-context tests), `tests/unit/test_runner_summary.py` (new), plus this unit's task and
  work records.
- **Commits:** `feat(screamingface-engine): runner traceability and logging layer (OME-1069)`
- **Gates:** ruff check + format clean; pyright 0 errors; `check_layering.py` OK; full engine
  suite 2274 passed, 5 skipped, 91.62% coverage (gate 80%).
- **Deviations:** the planned `trace` param on `url4.streaming.lifecycle.run` was NOT needed —
  the executor already receives the `TraceContext` from `lifecycle.run`, so the summary records
  the exact stream trace id with zero cross-package change. The Linear issue must be filed by
  the owner (Linear MCP unavailable this session).
