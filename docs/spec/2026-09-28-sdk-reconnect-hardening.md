---
status: implemented
parent-epic: OME-1016
ticket: unfiled
date: 2026-09-28
---

# SDK reconnect hardening (OME-1016 gaps)

Language: ASD-STE100 Simplified Technical English.

## 1. Problem

PR #753 (OME-1020) and PR #874 (OME-1141) added the SDK reconnect loop. The OME-1016 plan
(`docs/plan/2026-08-26-run-resume-and-control.md`, step 4 and step 6) also asks for tests
that do not exist on `origin/main`:

1. A reconnect handshake that the engine refuses with 401/403 (not an Access challenge).
2. An Access challenge during a reconnect, then a resume from the stream cursor.
3. An App restart during a Run, and a stop of a Run that is older than 60 s.

The plan also asks for a progress line "reconnecting (attempt n)". Today the SDK writes
only a log warning (`_engine/transport.py`, `_on_stream_failure`).

## 2. Findings from reading the code

- **F1 (bug).** On an Access challenge, `_on_handshake_rejection` always mints a NEW
  capability. The engine mints each capability for a NEW topic
  (`rest/routes.py`: `codec.sign(new_topic(), ...)`). After the Run starts, the new
  capability names a topic with no Run. The resume attach then goes to the wrong topic and
  the caller never gets the result. Spec 2026-08-26 §6 S3 says: "With long-lived tokens
  there is no re-mint on this path."
- **F2 (bug).** The loop catches every `InvalidStatus` as a handshake rejection. Only an
  Access challenge continues; all other statuses are FATAL and sweep all Runs. A 502/503
  from a proxy while the App restarts is thus FATAL. Spec §6 S3 says: "connect refused /
  5xx / timeout → BACKOFF".

## 3. Requirements

- **R1.** Reconnect handshake refused with 401 or 403, and no Access challenge: make one
  attempt only. Run the sweep. Raise `ExecutionError(code="websocket_disconnected")`.
  Do not wait for the budget. (Existing behavior — pin it with a test.)
- **R2.** Access challenge on a reconnect handshake after the Run started:
  re-authenticate, then attach again with the SAME capability and
  `from_sequence = cursor`. Do not mint. Before the Run starts, keep the current behavior
  (mint a fresh capability — pinned by `test_an_access_challenge_retries_with_a_freshly_minted_capability`).
- **R3.** Reconnect handshake refused with a 5xx status after the Run started: use the
  same BACKOFF and outage budget as a connection loss. Before the Run starts, keep the
  current behavior (FATAL).
- **R4.** On each BACKOFF attempt, send a private connection notice
  `reconnecting, attempt n` to the built-in progress observer. When the stream attaches
  again, send one notice `reconnected`.
  - Terminal text: `ScreamingFace · <candidate> · connection lost — reconnecting (attempt n)`
    and `ScreamingFace · <candidate> · connection restored`.
  - Notebook panel: the candidate row status shows `Reconnecting (attempt n)` while the
    candidate is running; the live announcement says the same. On resume, the row goes
    back to its normal status.
  - The text is generic: no URL, no token, no close code, no exception text.
  - Sync and async paths are the same.
- **R5.** The user's `on_event` callback does not receive the notice. The public `Event`
  set does not change (see open question Q1).
- **R6.** Engine integration tests, in-process harness (`TestClient` +
  `InMemoryEventStream`, no broker):
  - App instance A closes during a Run; instance B, on the same event stream, resumes the
    SAME capability from the cursor. The frames have no gap and no duplicate.
  - `DELETE /` on a Run older than 60 s gives 204.

## 4. Design

- `_core/ports.py`: add a frozen `_ConnectionNotice(state, attempt)` and a runtime-checkable
  protocol `_ConnectionListener` with `connection(candidate_notice)`. Private names only.
- `_engine/transport.py`: `_notify_connection(on_event, notice)` calls
  `on_event.connection(notice)` only when `on_event` is a `_ConnectionListener`. A listener
  error is logged and ignored (a progress defect must not end a paid Run).
- `_evaluation/runner.py`: `bind()` returns a small callable object that is also a
  `_ConnectionListener`. It forwards the notice to the built-in observer only.
- Hexagonal rule: the transport knows only the port type. It does not import `_ui`.

## 5. Out of scope

- OME-1071 / OME-1066 / OME-1067: `cancel_active()` still stops all Runs of the client.
- Live deploy checks, the exact WS rejection codes of a real engine, Linear.
- A real-socket SDK-to-engine test (needs a server process; see follow-ups).

## 6. Open questions (owner)

- **Q1.** Must the user's `on_event` callback also get a public `Reconnecting` Event? This
  changes the public API snapshot, so the owner must decide. This unit sends the notice
  to the built-in progress output only.
- **Q2.** Must a 5xx handshake on the FIRST connect (before the Run starts) also back off?
  This unit keeps it FATAL.
