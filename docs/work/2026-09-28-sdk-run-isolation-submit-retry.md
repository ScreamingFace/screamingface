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
  spec §8 (updated in review round 1). The reconnect backoff sleep
  (`time.sleep` in `_on_stream_failure`) is still not woken by an abort; prior tests pin
  that sleep through a patched clock, so it stays.
- **Review round 1 (design review: accept with fixes):**
  - Fix 1: re-send only on the Engine's own refusal (`_is_engine_refusal`: 503 +
    problem+json + `Retry-After`); an edge 503 stays fatal. After a re-send, a 409 is this
    Run (`_finish_start`), so no paid Run is left without a reader. New tests (sync + async):
    409 after a re-send completes the Run; a 409 on a first start still raises; a non-Engine
    503 is fatal with one attempt.
  - LOW: a refusal that is not about capacity (queue outage, #1098) ends as
    `engine_not_admitted` with the Engine's detail and no capacity claim (new test).
  - Fix 5: one factory `_new_admission(budget_s, base_delay_s)` in `transport.py` (it
    needs `_reconnect_delay`, and moving that out would drop the `random` import that
    `test_reconnect_recovery_window.py` patches through this module); the legacy
    `_start_sync(http, token, url4)` shape still works. `_first_refusal` is
    `field(default=None, init=False)`.
  - Fix 6: the `websockets` keepalive pings (20 s, sync thread and asyncio task) are traffic
    that keeps an edge from closing the idle socket. Now explicit (`_KEEPALIVE_PING_S`,
    passed as `ping_interval`) with a WHY comment; new tests (sync + async) prove pings flow
    while a start waits. No re-attach needed. The stub answers pings with pongs.
  - Fix 7: done on unit 2 (the async `_retire` helper), where the asymmetry began.
  - Tests changed in this unit's own new file only: two `(503, None)` answers became
    `(503, "soon")`, and the direct-call stub 503 got problem+json, because None now means
    an edge page.
  - Gates after the fixes: ALL GREEN — 1956 passed / 26 skipped, coverage 96 % (`admission.py` 100 %).
