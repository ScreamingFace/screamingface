---
ticket: OME-1067
stack: screamingface
status: done   # planned | in_progress | done | blocked
started: 2026-09-28
finished: 2026-09-28
---

# sdk-run-isolation-disconnect — a lost stream stops only its own Run; a completed Run is never stopped

Ticket: **OME-1067** (epic OME-1064). Spec: `docs/spec/2026-09-28-sdk-run-isolation.md`
(§4.1 C3, §4.2, bug B2). Plan: unit 2. Stacked on `sdk-run-isolation-stop-one`.

## Intent

When one stream's outage budget is spent, `_sweep_after_disconnect()` calls
`cancel_active()` and stops every Run the Client owns — in the 2026-09-01 incident, a
sibling that had all 100 of 100 cases complete. Make that path stop only the lost Run.
Also retire a Run's capability the moment its terminal frame is accepted, so no stop (own
or owner sweep) can reach a completed Run (B2).

## Planned changes

- `packages/screamingface/src/screamingface/_engine/transport.py` — `_sweep_after_disconnect`
  takes the capability and stops one Run (name kept: `test_reconnect_recovery_window.py`
  patches it by name); `_back_off` / `_on_stream_failure` pass the capability; retire the
  capabilities when `_run_connected` returns an outcome. Both twins.
- New tests `packages/screamingface/tests/test_run_isolation_disconnect.py`.

## Test plan

- Two Runs on one transport; A's stream lost and every reconnect refused 503 (budget
  0.3 s); B healthy, held open until A fails → A `websocket_disconnected`, B completes, only
  A's capability is deleted. Sync + async.
- B2: a Run reaches its terminal frame with an artifact result; the artifact fetch is held;
  `cancel_active()` during the fetch sends NO `DELETE /`; the Run still returns its outcome.
  Sync + async.
- Owner abort still stops every active Run (prior pins stay green:
  `test_concurrent_interrupt_deletes_every_active_engine_capability`, async twin).

## Acceptance

- New tests pass; all prior tests pass unmodified; gates green; `git diff
  sdk-run-isolation-stop-one...HEAD` holds only this unit.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned — `_engine/transport.py` (both twins: `_sweep_after_disconnect(token)`
  stops one Run; `_back_off` / `_on_stream_failure` carry the capability; `_retire` takes a
  Run's capabilities out of the registry when its terminal frame is accepted), new
  `tests/test_run_isolation_disconnect.py` (5 tests). Stub unchanged.
- **Commits:** `fix(screamingface): stop only the lost Run when its stream gives up` (this unit).
- **Gates:** `run_gates.py screamingface --base origin/main` ALL GREEN — pytest 1915 passed /
  26 skipped, coverage 96 % (floor 95); ruff, format, pyright, notebooks, build,
  distribution ✓; append-only ✓ (no prior test touched).
- **Deviations:** none. The owner-abort regression pin already exists and stays green:
  `test_client_run.py::test_concurrent_interrupt_deletes_every_active_engine_capability`
  and `::test_async_concurrent_cancellation_deletes_every_active_engine_capability`.
- **Follow-ups / owner questions:** OME-1067 acceptance "one stream failing fails exactly
  one candidate; siblings continue" holds at the transport; at the Evaluation level it needs
  unit 4 (spec Q1-Q3), because the runner still sweeps when one Candidate raises. The
  report distinction "stream failed" vs "aborted" is also unit 4 (spec §5).
- **Review round 1 (design review: accept with fixes):**
  - Fix 2: a Run is complete at its terminal FRAME. `_run_connected` (both twins) retires
    the capabilities through `_settled` before the caller's callback for that frame runs,
    and its interrupt arm sends no `ai.url4.stop` once the outcome is in. New tests (sync +
    async): a sweep during a slow terminal callback sends no `DELETE /`; a raising terminal
    callback sends no stop frame (all four RED before the fix). The stub now records a stop
    frame sent after the terminal frame.
  - Fix 7 (placed here, where the asymmetry began): the async twin has its own `_retire`
    and uses it in `run()`'s `finally`, like the sync twin.
  - Gates after the fixes: ALL GREEN — 1922 passed / 26 skipped, coverage 96 %.
