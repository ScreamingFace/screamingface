---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: screamingface-engine
status: done
started: 2026-10-22
finished: 2026-10-22
---

# e2e-otel-local-runner — local in-process runs export their span tree (e2e workbench unit 6a)

## Intent

Local mode exported no OTel spans: `InProcessJobRunner` handed `lifecycle.run` the bare stream,
while a Job wraps its publisher in `SpanRelay(publisher, load_span_sink(env), traceparent=...)`
(`runner/main.py`). The e2e workbench (plan `docs/plan/2026-10-22-e2e-workbench-u6-telemetry.md`,
Task 1) needs the `url4.run` tree from local runs. Apply the same wrap per local run: export
when `OTEL_EXPORTER_OTLP_ENDPOINT` / `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` is set, pure
passthrough otherwise (the default).

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/adapters/inprocess.py`: per-run
  `SpanRelay` around `lifecycle_run`, loader injected as `span_sink=` (default
  `tracing.loader.load_span_sink`).
- `apps/screamingface-engine/tests/unit/test_inprocess_span_export.py` (new).

## Test plan

- Configured: `url4.run` root + a child carrying `gen_ai.request.model`, all under the run's
  trace id, root parented on the handed span; sink closed once.
- Stop / `aclose`: sink still closed, root status `stopped`.
- Sink raising on emit or close: run still `succeeded`.
- Not configured: loader returns `None`; frames byte-identical to an unwrapped `lifecycle.run`
  (minted ids and clock pinned). An active sink alters no published byte either.
- Sink flush runs off the event-loop thread.
- Importing the adapter does not load `opentelemetry` (clean subprocess).

## Acceptance

- Engine gates green: pytest, ruff check, ruff format --check, pyright, `check_layering.py`.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus this ledger.
- **Commits:** see `git log` on branch `e2e-otel-local-runner`.
- **Gates:** pytest 5752 passed / 147 skipped / 13 deselected; ruff check clean; ruff format
  clean; pyright 0 errors; `check_layering.py` OK. RED first: 9 of 10 new tests failed
  (`span_sink` kwarg absent); the byte-identical default-path test passed before and after,
  as a baseline should.
- **Smoke (real exporter, no paid calls):** a stdlib loopback OTLP/HTTP receiver got `chat`
  (`gen_ai.request.model` set) and `url4.run` under the handed trace id. A dead endpoint
  (`127.0.0.1:9`) still ended `succeeded`; the task stayed `running` for the 5 s flush bound.
- **Deviations:** the relay is built inside the run's task, not in `schedule`, so a run
  cancelled before its first step never creates an exporter thread. The flush is awaited
  through `asyncio.to_thread`, so the shared loop is never blocked. With a dead collector, a
  run's admission slot and `status()` are held for up to `FLUSH_TIMEOUT_MS` (5 s) after its
  terminal frame. That matches a Job; it's flagged for review.
