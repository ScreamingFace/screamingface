---
status: approved-design; units 1-3 merged (#1105, #1109, #1115); unit 4 (runner, §5) approved by the owner 2026-09-29 and implemented on `OME-1071-sdk-evaluation-outcome`
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
- **E6. ADR-0002 was not built.** `ExecutionError` had no Partial Report. No code built a
  Report from a subset of Candidates. Unit 4 builds it (§5).

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
| C1b | runner except arm, an `Exception` from ONE Candidate's `transport.run()` | **no stop at all** (the transport already stopped that Run) | the failure belongs to one Run; siblings are healthy and independently attached. Owner Q1, 2026-09-29: the prior pin is replaced |
| C1c | runner except arm, an exception from the caller's `on_event` callback | stop everything (owner Q3, 2026-09-29) | the caller's own code failed; the Evaluation cannot deliver events any more. How the runner tells it apart: §5.1 |
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

## 5. Evaluation outcome when one Candidate fails (unit 4, decided 2026-09-29)

ADR-0002: after paid work begins, an infrastructure or protocol failure raises an
`ExecutionError` that carries an optional Partial Report with every recoverable completed
Candidate Result. Normal Benchmark and provider failures stay inside the returned Report.

Behavior (owner answers Q1-Q3, 2026-09-29). It is the same in the sync and async twins:

1. **C1a.** A `BaseException` that is not an `Exception` (KeyboardInterrupt, SystemExit,
   `asyncio.CancelledError`) stops everything: `cancel_active()` first, then the siblings
   are cancelled and the runner waits for them. The interrupt itself is re-raised. A failed
   sweep adds the note "Stopping active SF Engine runs also failed" to it (unchanged).
2. **C1b.** An `Exception` from one Candidate's `transport.run()` stops nothing. The
   transport already stopped that Run (units 1-3). The runner records the failure, tells
   the progress output at once (the row shows `run_failed`), and lets every sibling run to
   its end (success or failure).
3. **C1c.** An exception from the caller's `on_event` callback stops everything, as C1a,
   and re-raises THAT exception (not `candidates_failed`). See §5.1.
   - **Swept siblings read as stopped** (review round 1). The abort arm sets one abort flag
     per Evaluation BEFORE the sweep. After that, a sibling whose Run ends with an error
     (the sweep ended its stream) or that is cancelled is shown as `stopped` (row
     `stopped`, terminal `run stopped`), never as `run_failed`. The async twin waits with
     `asyncio.wait`, not `gather`: when the Evaluation's task is cancelled, `gather` would
     cancel the siblings before the arm can set the flag and sweep. It loops on
     `FIRST_COMPLETED` and treats a CANCELLED Candidate task like an exception: `FIRST_EXCEPTION`
     never wakes for a cancelled task, so a callback that raises `CancelledError` would leave
     the siblings running (C1a / C1c).
4. All Candidates succeed → the Report (unchanged).
5. One or more fail → `ExecutionError(code="candidates_failed")`, raised `from` the first
   failed Candidate in the caller's Candidate order, with:
   - `details={"failed": {candidate name: code}}` in the caller's Candidate order;
   - `code` is the failure's `ScreamingFaceError.code` (for example
     `websocket_disconnected`, `engine_at_capacity`, `engine_not_admitted`,
     `authentication_failed`, `engine_unreachable`). An exception without a code gets the
     stable fallback `unexpected_error`;
   - `partial_report`: a Report of the Candidates that succeeded (§5.2), or `None` when no
     Candidate succeeded;
   - message: `<n> of <total> Candidates failed: <name> (<code>), ...`;
   - `hint` points to `error.partial_report` and `error.details['failed']` (IPython shows
     only message, hint and code).
   So the caller can tell "this Candidate's stream failed" (`candidates_failed`, the name
   and its code) from "the Evaluation was aborted" (the interrupt or the callback's
   exception) — OME-1067 acceptance.
6. One-Candidate Evaluations keep today's behavior: the error itself, no Partial Report.
   (The runner runs one Candidate inline, with no sibling to protect.)

Consequence (it follows from Q2(a), "any failed → `candidates_failed`"): in a
multi-Candidate Evaluation, an error class that a one-Candidate Evaluation raises directly
(for example `EngineUnavailableError` or `AuthenticationError`) arrives as the `__cause__`
of `candidates_failed`, and its code is in `details["failed"]`. A caller that catches these
classes must catch `ExecutionError` for a multi-Candidate Evaluation. Pre-spend planning
failures (ADR-0002) are not affected: they are raised before any Candidate runs.

### 5.1 How the runner tells a callback exception from a Candidate failure

Both come out of the same `transport.run()` call: the transport calls the bound observer
for each frame, and `_observe_sync/_async` re-raise the callback's exception unchanged
(the same object, notes copied). So the runner cannot use the exception type.

Design: **an identity tag at the one place that calls the caller's callback.**
`_SyncEventObserver` / `_AsyncEventObserver` invoke `on_event` inside `observe`. When that
call raises, the observer records the exception object (in a private list, under its lock)
and re-raises it unchanged. The runner then asks `observer.raised_by_caller(exc)`: true only
when `exc` IS a recorded object (`is`, not `==` or type).

Why this design:

- The transport stays unchanged. It already stops its own Run in-band when the observer
  raises before the terminal frame, and it already preserves the exception object.
- No wrapper type crosses the transport. A private wrapper exception would change what the
  transport's `except` arms see, and a single-Candidate Evaluation would have to unwrap it.
- Identity cannot misclassify. A Candidate failure is a new object that the transport or
  the Engine layer made; it is never in the list. A callback that raises an
  `ExecutionError` copy of a real failure is still the caller's.
- The built-in progress output is not the caller's code. `_observe_progress` already
  catches its `Exception`s (decorative output never aborts paid work), so it cannot reach
  the runner as a failure. The SDK takes no other caller-supplied observer: `progress` is a
  bool. So `on_event` is the only caller code in the path.
- A `BaseException` from the callback (for example KeyboardInterrupt) is C1a before the tag
  is read.

### 5.2 Partial Report semantics

- Content: one `CandidateResult` for each Candidate whose Run succeeded AND whose result
  decodes, in the caller's Candidate order. The Report's `benchmark` and `case_count` are
  the Evaluation's own. It holds nothing for a failed Candidate: no row, no score, no
  usage.
- Derived fields describe only the Candidates in it: `usage`, `started_at`,
  `completed_at`, `ok`, `to_dict()`, `export()`. They make no claim about the missing
  Candidates. A missing Candidate is named only in `details["failed"]`.
- A Run that succeeded but whose result does not decode (for example `result_truncated`)
  is a failed Candidate: it goes into `details["failed"]` with its code and is not in the
  Partial Report. (In an Evaluation where every Run succeeded, a decode error is raised
  directly, as today.)
- `None` when no Candidate succeeded: `Report` requires at least one Candidate.
- `None` also when the multi-Candidate `Report` cannot be built (only a cross-Candidate
  rule, for example two equal names, can fail there, because each Candidate already passed
  its own one-Candidate Report). The reason is logged and added as a note on the error;
  `candidates_failed` is still raised.
- The Partial Report is a normal `Report`. The caller may export it or submit its
  Candidates to a leaderboard one by one; each `CandidateResult` is complete on its own.
- Progress output: the final step is `abort(candidates_failed)`, as for any error today.
  Rows that already have a result keep it (a row with a result ignores `abort`), each
  failed row keeps `run_failed`, and the panel error text is the message above. The runner
  does not call `reconcile` with the Partial Report: `reconcile` requires every Candidate.

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
  wait is cut to the time left, then the SDK sends one final attempt. Q4 is accepted
  (2026-09-29): 900 s stays and there is no public knob.
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

## 7. Owner questions (all closed 2026-09-29)

- **Q1. A prior test pinned the old sweep.** DECIDED 2026-09-29: **(a) replace it.**
  `packages/screamingface/tests/test_run_resume_reconnect.py::test_abort_sweep_records_note_when_stop_rejected`
  asserted that an `ExecutionError` from one Candidate calls `cancel_active()` once and adds
  the note "Stopping active SF Engine runs also failed". The owner approved replacing it:
  an ordinary Candidate failure calls no sweep, and a new pin proves that a
  KeyboardInterrupt (owner abort) still sweeps and records the note.
- **Q2. Public shape of a Partial Report.** DECIDED 2026-09-29: **(a).**
  `ExecutionError.partial_report: Report | None`; a new
  `ExecutionError(code="candidates_failed")` raised `from` the first failure, with
  `details={"failed": {name: code}}`. The public-surface snapshot is regenerated and the
  change is in the CHANGELOG. (Rejected: (b) re-raise the first failure with an
  attribute; (c) a Report that marks failed Candidates, which conflicts with ADR-0002.)
- **Q3. Is an exception from the caller's `on_event` callback an Evaluation abort?**
  DECIDED 2026-09-29: **(a) yes.** Stop everything and re-raise that exception. Design in
  §5.1.
- **Q4. Admission budget.** ACCEPTED 2026-09-29: 900 s default, no public knob. Nothing to
  build.
- **Q5. A sweep in one Evaluation stops the Runs of a concurrent Evaluation on the same
  Client.** Deferred by owner, 2026-09-29.

## 8. Out of scope

- Engine changes (none needed, E1).
- A public `Reconnecting` or `Queued` Event (owner decision 2026-09-28: no).
- Moving `_MAX_CANDIDATES_IN_FLIGHT` (8). With admission + retry it stops being a capacity
  decision, but a change is a separate unit.
- A fatal edge 503 on start that hid a start the Engine took: the Run has no reader and
  the Engine's orphan reaper stops it (120 s). Unchanged from today; recorded as a risk.
