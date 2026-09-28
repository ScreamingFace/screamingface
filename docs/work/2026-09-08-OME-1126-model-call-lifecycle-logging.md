---
ticket: OME-1126
stack: screamingface-engine
status: done
started: 2026-09-08
finished: 2026-09-08
---

# OME-1126 — a model call's completion, failure, and stalls reach the runtime log

## Intent

During the empty-prompt hunt the runtime log showed exactly one line per model call
(the gateway's `usage accounting started`) and then silence — a healthy long reasoning
call, a stalled provider endpoint, and a dead connection all looked identical for
minutes. The minimum observability to debug this class of problem: an engine-side line
when a call COMPLETES (model, duration, finish_reason), a line when it FAILS (model,
duration, error code), and a heartbeat while one is still in flight past a threshold.
Full transport-classification work stays with OME-1127; this is the logging slice only.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/runner/connector.py` — time each
  gateway round trip; log completion/failure; heartbeat task at 60s intervals while in
  flight. Log lines carry model id, elapsed seconds, finish_reason/error code — NEVER
  prompt or response text (OME-990: the runtime log must not carry prompt bytes).
- `apps/screamingface-engine/src/screamingface_engine/local.py` — attach a stream
  handler to the `screamingface_engine` logger in the local composition root (created
  after the RuntimeLog capture replaces stderr, so lines land in `runtime.log`);
  idempotent, INFO level. Deployed `app.py` path untouched.
- `apps/screamingface-engine/tests/unit/test_model_call_lifecycle_logging.py` — NEW.

## Test plan

- RED: a completed call emits one INFO record naming the model, a duration, and the
  finish_reason; a failing call emits a failure record with the error code before the
  exception propagates; a slow call emits repeated heartbeat records (interval patched
  small) that STOP once the call returns; no record ever contains the prompt text.
- Local composition: the logging helper attaches exactly one handler across repeated
  calls (idempotence) at INFO.

## Acceptance

- New tests pass; every existing test passes unmodified; gates green.
- A live run's `runtime.log` shows per-call completion lines and heartbeats during a
  long synthesis call (owner-verified on the next run).

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned; the round trip moved into `_logged_round_trip` (the
  lint statement budget forced the extraction the design wanted anyway).
- **Commits:** (this commit)
- **Gates:** run_gates.py screamingface-engine — ALL GATES GREEN (2433 passed, 5 skipped).
- **Deviations:** none.
