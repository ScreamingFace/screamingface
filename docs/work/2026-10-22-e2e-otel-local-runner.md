---
ticket: OME-1747
stack: screamingface-engine
status: done
started: 2026-10-22
finished: 2026-11-04
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

- **Actual files:** as planned, plus
  `apps/screamingface-engine/tests/unit/test_inprocess_span_export_lazy_import.py` (the sync
  lazy-import test, split out) and this ledger.
- **Commits:** see `git log` on branch `OME-1747-local-run-span-export` (started as
  `e2e-otel-local-runner`, renamed at PR-open).
- **Gates:** pytest 5752 passed / 147 skipped / 13 deselected (2026-10-22); after the rebase onto main (2026-10-27) 5831 passed / 153 skipped / 13 deselected; ruff check clean; ruff format
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

## Review follow-ups (minors)

- **Status race:** the terminal frame's verdict is recorded before the span flush is awaited,
  and `status()` prefers it over the task's state. A `stop()`/`aclose()` that cancels the task
  mid-flush no longer turns a `succeeded`/`failed` run into `stopped`. Side effect: `status()`
  of a finished run now reports the frame's verdict (`failed`, `timed_out`), not a
  task-derived `succeeded`. `lifecycle.run` catches failures, so the task never raised.
- **Loader guard:** a raising `span_sink` loader is logged at WARNING and the run goes ahead
  without export. The production loader never raises, but the injected seam isn't trusted to.
- **Test hygiene:** the sync lazy-import test moved to
  `tests/unit/test_inprocess_span_export_lazy_import.py`, so the module-level asyncio mark no
  longer raises a PytestWarning.
- **Documented hold:** the module docstring now says that a down collector holds a run's
  admission slot, `exists()` and `status() == "running"` for up to `FLUSH_TIMEOUT_MS` (5 s)
  after `Terminated`. That's the same hold a Job's process has before it exits.

## Review round 2 (HupBaHa, CHANGES_REQUESTED 2026-10-29, head `aced56aa7`)

### Planned changes

- `adapters/inprocess.py`:
  - **Finding 1 (sink cleanup owner):** `relay.shutdown` moves out of the run task's
    cancellable `await` into a cleanup task the runner owns (`self._cleanups`). The run task
    awaits it through `asyncio.shield`, so cancelling the run can't cancel a close that's
    running or still queued on the default executor. `aclose()` waits for every cleanup task
    after the runs. Shutdown runs exactly once per built sink.
  - **Finding 2 (terminal durability):** the frame's verdict is recorded only after
    `lifecycle_run` returns normally. If lifecycle raises (terminal flush failure, a cancel
    during the terminal flush), the task status wins (`failed` / `stopped`). Cancellation
    during the later span-sink cleanup still keeps the recorded verdict.
- New tests only (append-only): `tests/unit/test_inprocess_sink_cleanup.py`,
  `tests/unit/test_inprocess_terminal_durability.py`.

### Test plan

- One-worker default executor kept busy: run reaches `Terminated`, then `aclose()`. It must
  not return until the worker is freed, and when it returns `close_calls == 1` (Dmitry's
  repro, RED first).
- `stop()` while the close is queued behind the busy executor: the close still runs exactly
  once after the worker frees, and `aclose()` waits for it.
- Close already running (held sink): `aclose()` returns only after the close finishes.
- No-OTel: a terminal flush that raises -> `status() == "failed"`; an executor that raises ->
  `failed`; a run past its deadline -> `timed_out`.

### Outcome (round 2)

- **Merged** `origin/main` first (clean, `e26dc1df0`).
- **Commits:** `4a9f70f4b` (finding 2, durability) and `c9ab86037` (finding 1, close owner).
- **RED first:** before the fix, 4 of the new sink-cleanup tests failed (aclose returned early;
  `close_calls == 0` after stop) and 2 of the new durability tests failed (`succeeded` instead of
  `failed` / `stopped`).
- **Gates:** `run_gates.py screamingface-engine --base origin/main` all green (append-only,
  ruff, format, pyright, layering, pytest+coverage); full suite 6810 passed / 168 skipped.
- **Deviations:**
  - No prior test was edited. `test_a_cancel_during_the_flush_keeps_the_terminal_frame_verdict`
    `[aclose-*]` now takes about 5 s each: its held sink is released only after `aclose()`
    returns, and `aclose()` now waits for the close, so it runs until that test's own
    `release.wait(timeout=5)` times out. The test still passes. The new tests assert the
    close-on-return behaviour directly.
  - `test_the_loader_is_asked_with_the_run_environment` isn't renamed (tests are append-only).
    Instead, the source docstring now says the loader gets `_base_env`, and why.
  - A cancel during the TERMINAL flush (inside `lifecycle.run`) now reports `stopped` rather
    than the frame's verdict. That follows directly from the requested rule and is pinned by a
    test.
  - `inprocess.py` is 513 lines (it was 476, already over the 450 guideline, before this
    round). No split this round.

### Outcome (round 3)

- **Finding (HupBaHa, on `4b9ba0b9f`):** `aclose()` gathered the runner-owned close tasks
  directly; cancelling `aclose()` cancelled them, the done callback dropped them from
  `_sink_closes`, and a queued `relay.shutdown` never ran. Repeated/concurrent `aclose()`
  returned without waiting.
- **Fix:** `aclose()` gathers `asyncio.shield(close)` views, so caller cancellation stops only
  that caller's wait. Nothing can cancel a close task now, so the done callback removes it only
  once it has really finished.
- **RED first:** 4 new tests in `tests/unit/test_inprocess_sink_cleanup.py` (cancelled
  `aclose()` with a queued close, with a running close, two concurrent with one cancelled,
  repeated after a cancelled one) all failed before the fix and pass after. No existing test
  changed.
