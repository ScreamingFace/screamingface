---
status: approved-design, partly-implemented (units 1-3 transport half; unit 4 waits for owner answers Q1-Q3)
tickets: OME-1071 (epic OME-1016), OME-1067 (epic OME-1064), OME-1066 (epic OME-1064)
date: 2026-09-28
---

# SDK run isolation: stop one Run, not every Run

Language: ASD-STE100 Simplified Technical English.

## 1. Problem

The SDK has one way to stop a Run: `cancel_active()`. It stops EVERY Run that the Client
owns (`_active_tokens`). The SDK calls it in four places. Three of them react to the
failure of ONE Run:

| # | Caller (both twins) | Trigger | Today |
|---|---|---|---|
| C1 | `_run_candidates_sync/_async` except arm (`_evaluation/runner.py`) | any exception from any Candidate, or an interrupt | stops every Run |
| C2 | `_on_handshake_rejection` (`_engine/transport.py`) | a fatal 401/403 (or the re-login cap) on a started Run | stops every Run |
| C3 | `_on_stream_failure` → `_sweep_after_disconnect` | the outage budget of one stream is spent | stops every Run |
| C4 | the user or the runner calls `cancel_active()` directly | owner abort | stops every Run (correct) |

Result (incident 2026-09-01, OME-1071 / OME-1067): one lost stream stopped the healthy
sibling Runs. One of them had all 100 of 100 cases complete. No Candidate got a result and
no cost was recorded.

OME-1066: the Engine answers a run start with `503` + `Retry-After` when it has no free
capacity (OME-1091, queue depth and per-caller cap). The SDK does not retry a `503` on
`GET /?q=` (`_raise_response`: `permanent = status < 500`, one attempt). The Candidate fails
at once, and C1 then stops every other Candidate.

## 2. Facts from the code (origin/main `0e6a3bba`)

- **E1. The Engine stop is per capability.** `DELETE /` (`rest/routes.py`, `stop_run`)
  stops the Run of the token's topic only, then `delete_stream` purges that topic's frames
  (it keeps the terminal frame). The Engine needs NO change.
- **E2. A stop purges the stream.** If a sibling sweep stops a Run that is terminal on the
  Engine, but the SDK is still reconnecting to read the end of it, the resume gets
  `stream_reclaimed` → `run_result_lost`. This is how a complete Run is lost.
- **E3. A `503` on run start schedules nothing.** Admission refuses in `_schedule` (or in
  `_refuse_existing` when the queue cannot be read) before the Run exists. The same
  `GET /?q=` with the same capability is safe to send again. The Engine sends
  `Retry-After` as delta-seconds: its drain estimate (OME-1091), `1`, or `5`.
- **E4. The retrying HTTP transport does not touch run start.** `GET /?q=` has no
  `_REPLAY_SAFE` mark (OME-1107), by design. The new retry must live in `_start_sync` /
  `_start_async`, where the SDK knows that a 503 means "not admitted".
- **E5. OME-1071 fix 2 ("budget from stream start") is already done.** OME-1141 starts the
  outage budget at the first observed failure (`_RecoveryWindow.failed`). The test
  `test_first_connection_failure_starts_budget_when_observed` pins it.
- **E6. ADR-0002 is not built.** `ExecutionError` has no Partial Report. No code builds a
  Report from a subset of Candidates.

## 3. Bugs found while reading

- **B1. `_aborted` never resets.** `cancel_active()` sets `_aborted = True` for the life of
  the Client. After one sweep (today: any failed multi-Candidate Evaluation, or one Ctrl-C),
  every later Run on the same Client does not reconnect after a lost stream. It also does
  not stop its own Run (the `if not self._aborted` guard skips the stop), so the Run keeps
  spending until the Engine reaper stops it. Notebook users keep one Client for a session,
  so this is a real risk.
- **B2. A completed Run stays stoppable.** The capability stays in `_active_tokens` until
  `run()` returns. That includes the artifact fetch after the terminal frame (sync) and,
  for a cancelled async Run, until a sweep clears it. A sweep in that window sends a
  `DELETE /` for a Run that is complete.
- **B3 (hazard for OME-1066).** A plain `time.sleep` for a long `Retry-After` in a worker
  thread cannot see a Ctrl-C. After the sweep, the worker would wake up, send the start
  again, get admitted, and start a paid Run that nobody reads. The admission wait must be
  interruptible by the owner abort.

## 4. Core model

Two stop operations, with different owners:

- **Stop one Run** (`_stop_own_run`, new, private). It stops only the capability that
  started this Run. The transport calls it when THIS Run cannot continue. It is best
  effort: a failed stop is logged and does not hide the Run's own error. It retires the
  capability from `_active_tokens`, so a later sweep does not send it again.
- **Stop everything I own** (`cancel_active`, unchanged public port). Only for an owner
  abort: KeyboardInterrupt / SystemExit / `asyncio.CancelledError` of the Evaluation,
  a real Client shutdown, interpreter exit, or a direct call by the caller.

### 4.1 Caller classification

| # | Caller | New class | Reason |
|---|---|---|---|
| C1a | runner except arm, `BaseException` that is not `Exception` (KeyboardInterrupt, SystemExit, CancelledError) | stop everything | the owner stopped the Evaluation; no Run has a consumer any more |
| C1b | runner except arm, an `Exception` from ONE Candidate's `transport.run()` | **no stop at all** (the transport already stopped that Run) | the failure belongs to one Run; siblings are healthy and independently attached. See Q1 (a prior test pins the old behavior) |
| C1c | runner except arm, an exception from the caller's `on_event` callback | stop everything (recommendation, Q3) | the caller's own code failed; the Evaluation cannot deliver events any more |
| C2 | `_on_handshake_rejection` (fatal 401/403, re-login cap) | stop one Run | the refusal is about this stream's handshake; other Runs have their own sockets |
| C3 | `_sweep_after_disconnect` (outage budget spent) | stop one Run | one lost stream; the name stays because prior tests patch it by name |
| C4 | direct `cancel_active()` | stop everything | explicit owner request |

### 4.2 Never stop a completed Run

- **Definition.** A Run is complete when the SDK accepted its root terminal frame (the
  lifecycle returned an outcome).
- **Rule.** At that moment the transport retires the Run's capabilities from
  `_active_tokens`, BEFORE the artifact fetch and before the socket closes. After that,
  neither stop operation can reach it. The result fetch is not affected (it mints a fresh
  capability, OME-892).
- A Run that is terminal on the Engine but not yet read by the SDK is NOT complete in this
  sense. It is protected by 4.1: a sibling failure no longer stops it (E2).

### 4.3 The abort flag belongs to one abort

`_aborted` is set by `cancel_active()` (inside the registry lock, sync twin) and stays set
only while the Runs of that abort unwind. When a new Run starts and no other Run is
RUNNING, the transport clears it (B1). Both twins count in-flight `run()` calls
(`_running`), not registered capabilities: the async sweep empties the registry while its
Runs still unwind, and a Run can leave the registry before it ends (4.2).
The prior test `test_owner_abort_does_not_retry_or_sweep_again` sets the attribute
directly, so the attribute keeps its name and its bool meaning.

## 5. Evaluation outcome when one Candidate fails (unit 4, waits for Q1-Q2)

ADR-0002: after paid work begins, an infrastructure or protocol failure raises an
`ExecutionError` that carries an optional Partial Report with every recoverable completed
Candidate Result. Normal Benchmark and provider failures stay inside the returned Report.

Proposed behavior:

1. One Candidate raises (C1b). The runner records the failure, does not stop anything, and
   waits until every sibling ends (success or failure). The progress output shows the
   failed row at once.
2. All Candidates succeed → return the Report (unchanged).
3. One or more fail → build a Report from the successful Candidates only (the Partial
   Report; `None` when no Candidate succeeded), then raise (shape: Q2).
4. The error names each failed Candidate and its code (for example
   `websocket_disconnected`, `engine_at_capacity`). An owner abort re-raises the interrupt
   itself. So the caller can tell "this Candidate's stream failed" from "the Evaluation was
   aborted" (OME-1067 acceptance).
5. One-Candidate Evaluations keep today's behavior (the error, no Partial Report).

## 6. OME-1066: retry a run start that the Engine did not admit

- **Scope.** Only a `503` that the ENGINE wrote on `GET /?q=` (run start):
  `application/problem+json` with `Retry-After`. An edge proxy's 503 (plain text, HTML) may
  hide a start that the Engine took, so it stays fatal. Other 5xx keep today's behavior
  (fail at once). The 428 "attach a WebSocket" ladder stays as it is.
- **409 after a re-send.** One capability names one topic. So a `409 a run already exists`
  on a RE-SENT start is this Run: an earlier attempt was scheduled although its answer was
  a refusal (for example a queue-unavailable 503 after a publish whose ack was lost). The
  SDK treats it as admitted and reads the stream (the WebSocket is already attached). A 409
  on a first start is still an error.
- **Keepalive.** The WebSocket stays attached during the wait (up to the budget). The
  `websockets` keepalive sends a ping every 20 s (`_KEEPALIVE_PING_S`) on both twins, also
  while the start loop blocks, so an edge idle timeout (Cloudflare: about 100 s) does not
  close it. A test proves the pings flow during a wait.
- **Wait per attempt.**
  - `Retry-After` present: obey it. Both forms are accepted — delta-seconds and HTTP-date —
    through the existing `_core/retry._retry_after_seconds` (one parser in the SDK).
  - `Retry-After` absent or not parsable: full-jitter backoff `_reconnect_delay(attempt,
    base)` (0.5 s base, 15 s cap), the same helper the reconnect loop uses.
  - Floor: never less than the reconnect base delay, so `Retry-After: 0` cannot spin.
- **Budget.** One overall wait budget per Run start: **900 s (15 min) by default**
  (`_ADMISSION_BUDGET_S`). The transport constructors take `admission_budget_s=` (the same
  kind of seam as `reconnect_budget_s`). A wait never goes past the deadline: the last
  wait is cut to the time left, then the SDK sends one final attempt. See Q4 for the
  default and for a public knob.
- **Expiry.** `ExecutionError(code="engine_at_capacity", status=503, permanent=False)`.
  The message names Engine run capacity, the time waited, and the Engine's own detail. It
  is not a generic transport error. When the Engine's refusal was not about capacity (a
  run-queue outage, #1098), the code is `engine_not_admitted` and the message gives the
  Engine's detail without a claim about capacity.
- **Abort.** An owner abort ends the wait at once and the SDK does not send the start
  again (B3). Sync: the wait is a `threading.Event` wait that `cancel_active()` sets.
  Async: the task is cancelled, and the flag is checked before each attempt.
- **Siblings.** Nothing is stopped while a start waits. The WebSocket stays attached, as
  the Engine needs a subscriber before a `respond-async` start (428 rule).
- **What the user sees.** The internal connection notice from OME-1396 (NOT a public
  Event, owner decision of 2026-09-28) gets two new states:
  - `waiting_for_capacity` (with the attempt number): terminal line
    `ScreamingFace · <candidate> · waiting for Engine capacity (attempt n)`; notebook row
    `Waiting for Engine capacity (attempt n)`.
  - `admitted`: terminal line `ScreamingFace · <candidate> · Engine capacity available —
    starting`; the notebook row goes back to its normal status.
  - Generic text only: no URL, no token, no Engine detail.
- **Parity.** Sync and async use one shared policy object (`_engine/admission.py`), so the
  two twins cannot drift.

## 7. Open questions (owner)

- **Q1 (blocks unit 4). A prior test pins the old sweep.**
  `packages/screamingface/tests/test_run_resume_reconnect.py::test_abort_sweep_records_note_when_stop_rejected`
  asserts that an `ExecutionError` from one Candidate calls `cancel_active()` once and adds
  the note "Stopping active SF Engine runs also failed". That is C1b's old behavior. The
  append-only test rule does not let me change it.
  - (a) Replace it: an ordinary Candidate failure calls no sweep; add a new pin that a
    KeyboardInterrupt sweeps and records the note. **Recommended.**
  - (b) Keep sweep-all on any Candidate failure. Then OME-1071 and OME-1067 stay open for
    multi-Candidate Evaluations; units 1-3 still help single Runs.
- **Q2 (blocks unit 4). Public shape of a Partial Report.**
  - (a) Add `partial_report: Report | None` to `ExecutionError`, and raise a new
    `ExecutionError(code="candidates_failed")` `from` the first failure, with
    `details={"failed": {name: code}}`. Changes the public-surface snapshot. **Recommended**
    (it is the ADR-0002 wording, and one type to catch).
  - (b) Re-raise the first failure unchanged and attach the Partial Report as a note/
    attribute only when it is an `ExecutionError`.
  - (c) Return a Report that marks failed Candidates. Conflicts with ADR-0002 (hides
    missing Candidates).
- **Q3. Is an exception from the caller's `on_event` callback an Evaluation abort?**
  (a) Yes, stop everything (**recommended**: the same callback serves every sibling);
  (b) No, treat it as that Candidate's failure.
- **Q4. Admission budget.** Default 900 s? Options: 600 s, 900 s (**recommended**), 1800 s.
  Must it also be a public knob (a `Client(...)` argument or an environment variable)?
  **Recommended: not yet** — keep the constructor seam and add a public knob when a user
  asks; a public knob changes the snapshot.
- **Q5 (follow-up, not blocking).** A sweep in one Evaluation still stops the Runs of
  another Evaluation that runs at the same time on the same Client (the port has one
  registry per Client). Scope the sweep per Evaluation later?

## 8. Out of scope

- Engine changes (none needed, E1).
- A public `Reconnecting` or `Queued` Event (owner decision 2026-09-28: no).
- Moving `_MAX_CANDIDATES_IN_FLIGHT` (8). With admission + retry it stops being a capacity
  decision, but a change is a separate unit.
- A fatal edge 503 on start that hid a start the Engine took: the Run has no reader and
  the Engine's orphan reaper stops it (120 s). Unchanged from today; recorded as a risk.
