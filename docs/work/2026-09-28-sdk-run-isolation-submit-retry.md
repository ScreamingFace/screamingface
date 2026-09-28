---
ticket: unfiled   # OME-1066 (epic OME-1064) — backfill at PR-open
stack: screamingface
status: done   # planned | in_progress | done | blocked
started: 2026-09-28
finished: 2026-09-28
---

# sdk-run-isolation-submit-retry — wait for Engine capacity instead of failing the Candidate

Ticket: **OME-1066** (epic OME-1064). Spec: `docs/spec/2026-09-28-sdk-run-isolation.md` §6
(and bug B3). Plan: unit 3. Stacked on `sdk-run-isolation-disconnect`.

## Intent

The Engine refuses a run start with `503` + `Retry-After` when it has no free capacity
(OME-1091). The SDK fails the Candidate at once, and the runner then stops every sibling.
Retry a `503` on `GET /?q=`: obey `Retry-After` (delta-seconds and HTTP-date), else full-
jitter backoff, inside one overall budget (900 s default); on expiry raise
`engine_at_capacity`, naming capacity. Show the wait in the built-in progress output with
the internal connection notice (no public Event). An owner abort ends the wait at once and
never re-sends the start.

## Planned changes

- New `packages/screamingface/src/screamingface/_engine/admission.py` — `_AdmissionWait`
  policy shared by both twins.
- `packages/screamingface/src/screamingface/_engine/transport.py` — `_start_sync/_async`
  retry 503 (old call shape stays valid); `admission_budget_s=` constructor seam;
  `_aborted` backed by an Event so a wait can end at once; notices.
- `packages/screamingface/src/screamingface/_core/ports.py` — `_ConnectionState` gets
  `waiting_for_capacity`, `admitted`.
- `packages/screamingface/src/screamingface/_evaluation/progress.py`,
  `packages/screamingface/src/screamingface/_ui/evaluation_state.py` — render them.
- New tests `packages/screamingface/tests/test_admission_retry.py`.

## Test plan

- Policy (pure): delta-seconds, HTTP-date, absent and invalid header → backoff, `0` floor,
  last wait cut to the deadline, expiry, zero budget.
- Real stub, sync + async: 503 twice then 202 completes; `Retry-After: 1` waits about 1 s;
  503 forever → `engine_at_capacity` (status 503, message names capacity, retryable); 500
  fails at once; a sibling completes while one Run waits and nothing is stopped; a listener
  gets `waiting_for_capacity` 1, 2 then `admitted`; an owner abort ends a 30 s wait at once
  with one start attempt only.
- Renderers: terminal lines; panel row text and announcement; the row returns to its
  status on `admitted`.

## Acceptance

- New tests pass; prior tests unmodified and green; gates green; `git diff
  sdk-run-isolation-disconnect...HEAD` holds only this unit.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned — new `_engine/admission.py` (`_AdmissionWait`,
  `_ADMISSION_BUDGET_S = 900.0`); `_engine/transport.py` (`_start_*` retry 503 via
  `_send_start_*` + policy; `admission_budget_s=` seam; `_aborted` is now a property over a
  `threading.Event` / `asyncio.Event`; `_problem_parts` extracted from `_raise_response`
  for the capacity message; errors `engine_at_capacity` and `run_aborted`);
  `_core/ports.py` (two notice states); `_evaluation/progress.py`,
  `_ui/evaluation_state.py` (render them); new `tests/test_admission_retry.py` (24 tests).
  Plus: `tests/_isolation_engine.py` answers a client close while it waits for the start
  (a stub fidelity fix — the real engine answers a close at once).
- **Commits:** `feat(screamingface): wait for Engine capacity when a run start gets 503`
  (this unit).
- **Gates:** `run_gates.py screamingface --base origin/main` ALL GREEN — pytest 1939 passed /
  26 skipped, coverage 96 % (floor 95; `admission.py` 100 %); ruff, format, pyright,
  notebooks, build, distribution ✓; append-only ✓.
- **Deviations:** the policy takes the backoff as a callable (the transport's
  `_reconnect_delay`), so `admission.py` does not import `transport.py` (no cycle, no
  copy). The retry floor reuses the reconnect base delay seam.
- **Follow-ups / owner questions:** spec Q4 (default 900 s; public knob — recommended not
  yet). At expiry the runner still sweeps siblings until unit 4 (spec Q1-Q3). Risk noted in
  spec §8: a `409 a run already exists` after a retried start. The reconnect backoff sleep
  (`time.sleep` in `_on_stream_failure`) is still not woken by an abort; prior tests pin
  that sleep through a patched clock, so it stays.
