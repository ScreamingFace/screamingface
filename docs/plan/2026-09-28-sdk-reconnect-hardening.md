# Plan — SDK reconnect hardening (OME-1016 gaps)

Status: approved (user order: "spec + plan, then code"). Spec:
`docs/spec/2026-09-28-sdk-reconnect-hardening.md`. Language: ASD-STE100.
Worktree/branch: `sdk-reconnect-hardening`. Ledger: `docs/work/2026-09-28-sdk-reconnect-hardening.md`.

## Step 1 — RED: handshake tests (spec R1, R2, R3)

New file `packages/screamingface/tests/test_reconnect_handshake.py`. Use a self-contained
stub engine (same style as `test_run_resume_reconnect.py`): a real HTTP server that maps
each capability to a topic, closes the first stream with 1012, and scripts the second
handshake.

- 401 and 403 (no Access headers) on the reconnect handshake → `websocket_disconnected`,
  exactly 2 handshakes, 1 sweep `DELETE /`, elapsed time far below the 90 s budget.
  Sync and async.
- Access challenge (403 + `cf-access-aud`) on the reconnect handshake → 1 re-auth, the
  next handshake presents the ORIGINAL capability, attach has `from_sequence = 3`, the
  outcome completes, and the observed Event sequences are `1, 2, 3, 4` (no gap, no
  duplicate). Sync and async. Expected RED today (F1).
- 503 on the reconnect handshake → back off, resume, complete. Expected RED today (F2).

## Step 2 — GREEN: transport fixes (F1, F2)

In `_engine/transport.py`, both twins:
- `_on_handshake_rejection`: Access challenge and `run_started` → re-authenticate only.
  Keep the mint for the pre-start case. Fix the stale "60s iat window" comment.
- Non-Access status ≥ 500 and `run_started` → route to the stream-failure path
  (`recovery.failed()` + `_on_stream_failure`).

## Step 3 — RED then GREEN: progress notice (spec R4, R5)

New file `packages/screamingface/tests/test_reconnect_progress.py`:
- Transport: a listener `on_event` gets `reconnecting` attempt 1 (and 2 on a second loss)
  then `reconnected`; a plain function `on_event` gets no notice; a listener that raises
  does not end the Run.
- Runner `bind()`: forwards the notice to the built-in observer; the user callback gets
  nothing.
- Terminal: `_ProgressObserver.connection()` writes the two generic lines.
- Notebook state/view: `_EvaluationProgress.connection()` sets the row status text and the
  announcement; `reconnected` clears it; a finished row ignores it.

Code: `_core/ports.py` (notice + protocol), `_engine/transport.py` (`_notify_connection`),
`_evaluation/runner.py` (bound observer class, sync + async), `_evaluation/progress.py`,
`_ui/evaluation_state.py`, `_ui/evaluation_view.py`, `_ui/evaluation_widget.py`.

## Step 4 — Engine integration (spec R6)

New file `apps/screamingface-engine/tests/integration/test_run_control_resilience.py`,
in-process harness from `test_e2e_compose_flow.py`. Only commit it if it runs green here.
If the harness cannot model it, record the test design in the ledger follow-ups.

## Step 5 — Gates, ledger, commit, push

`uv run .claude/scripts/run_gates.py screamingface --base origin/main` and
`... screamingface-engine --base origin/main`. Fill the ledger Outcome. Commit with
conventional messages, no `Co-Authored-By`. Push the branch. No PR, no Linear.
