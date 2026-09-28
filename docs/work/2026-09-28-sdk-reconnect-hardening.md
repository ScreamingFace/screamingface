---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: screamingface (+ screamingface-engine tests)
status: in_progress   # planned | in_progress | done | blocked
started: 2026-09-28
finished:
---

# sdk-reconnect-hardening — close the reconnect test gaps of OME-1016 and show reconnects

Parent epic: **OME-1016** (Run control-plane resilience — resumable streams and stoppable
runs). Audit: the R4 (OME-1020) plan tests below are missing on `origin/main` (`3293550b`).

## Intent

Add the missing reconnect tests from the OME-1016 plan (step 4 and step 6). Fix each bug
that a test finds. Show a "reconnecting (attempt n)" line and a "reconnected" line in the
progress output that the SDK already renders (terminal text and notebook panel). Today a
reconnect is only a log warning, so a researcher does not know why the Run stops moving.

## Planned changes

- `packages/screamingface/src/screamingface/_engine/transport.py` — emit connection
  notices; bug fixes that the RED tests find (sync and async twins).
- `packages/screamingface/src/screamingface/_core/ports.py` — private connection-notice
  value and listener protocol.
- `packages/screamingface/src/screamingface/_evaluation/runner.py` — bound observer
  forwards connection notices to the built-in progress observer only.
- `packages/screamingface/src/screamingface/_evaluation/progress.py` — terminal line.
- `packages/screamingface/src/screamingface/_ui/evaluation_state.py`,
  `_ui/evaluation_view.py`, `_ui/evaluation_widget.py` — notebook row status.
- New tests: `packages/screamingface/tests/test_reconnect_handshake.py`,
  `packages/screamingface/tests/test_reconnect_progress.py`,
  `apps/screamingface-engine/tests/integration/test_run_control_resilience.py`.
- `docs/spec/2026-09-28-sdk-reconnect-hardening.md`, `docs/plan/2026-09-28-sdk-reconnect-hardening.md`.

## Test plan

- Reconnect handshake refused with 401 and with 403 (no Access challenge): one reconnect
  attempt only, sweep runs, `ExecutionError(code="websocket_disconnected")`, fast (well
  below the budget). Sync and async.
- Access challenge on the reconnect handshake: re-authenticate once, then resume on the
  SAME capability from the stream cursor; the frames that the caller sees have no gap and
  no duplicate. Sync and async.
- Reconnect handshake refused with 5xx: back off and resume (spec S3 BACKOFF row).
- Progress: one "reconnecting (attempt n)" notice per attempt and one "reconnected" notice
  on resume; terminal and notebook render them; user `on_event` callback gets no new
  object; text is generic (no URL, no token).
- Engine integration (in-process harness, no broker): App instance A stops mid-Run,
  instance B resumes the same capability from the cursor with no gap or duplicate; a Run
  older than 60 s is stoppable with `DELETE /` (204).

## Acceptance

- All new tests pass; all prior tests pass without change.
- `run_gates.py screamingface` and `run_gates.py screamingface-engine` green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
- **Commits:**
- **Gates:**
- **Deviations:**
- **Follow-ups:**
