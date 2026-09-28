---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: screamingface (+ screamingface-engine tests)
status: done   # planned | in_progress | done | blocked
started: 2026-09-28
finished: 2026-09-28
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

- **Actual files:** as planned, plus the shared test stub
  `packages/screamingface/tests/_reconnect_engine.py`. No change to `_ui/activity_*`.
  - SDK src: `_engine/transport.py`, `_core/ports.py`, `_evaluation/runner.py`,
    `_evaluation/progress.py`, `_ui/evaluation_state.py`, `_ui/evaluation_view.py`,
    `_ui/evaluation_widget.py`.
  - SDK tests: `tests/_reconnect_engine.py`, `tests/test_reconnect_handshake.py` (10),
    `tests/test_reconnect_progress.py` (14).
  - Engine tests: `apps/screamingface-engine/tests/integration/test_run_control_resilience.py` (3).
- **Commits:**
  - `15cdf443` docs(screamingface): spec and plan for SDK reconnect hardening
  - `960d8511` fix(screamingface): resume the same capability after a reconnect Access challenge
  - `cd196010` feat(screamingface): show reconnecting and connection-restored progress lines
  - `628b7291` test(screamingface-engine): pin resume across an App restart and stop past 60 s
- **Gates:**
  - `run_gates.py screamingface --base origin/main`: ALL GATES GREEN — 1888 passed,
    26 skipped; coverage 96 % (floor 95 %); notebooks, build, distribution checks green.
  - `run_gates.py screamingface-engine --base origin/main`: ALL GATES GREEN with
    `URL4_CLOUD_TEST_NATS_URL=nats://127.0.0.1:1` — 4021 passed, 61 skipped; coverage 94 %.
    With the local NATS at `localhost:4222` reachable, 2 tests in
    `tests/integration/test_worker_spine.py` fail (`spawn_failed: expected a READY line`).
    They fail the same way on a clean `origin/main` worktree, so they are an environment
    fault here and not from this unit.
- **Bugs found (TDD, RED first):**
  - **F1** — Access challenge on a reconnect after the Run started minted a NEW
    capability. Each mint names a new topic, so the resume attached to an empty topic and
    looped until the 90 s budget ended (RED: `websocket_disconnected` after ~97 s, close
    1008 from the stub). Fix: re-authenticate and resume on the SAME capability.
  - **F2** — a 5xx handshake refusal on a reconnect was FATAL and swept every Run (RED:
    `InvalidStatus` HTTP 502/503 after 0.0 s). Spec §6 S3 says BACKOFF. Fix: after the
    start, a 5xx uses the same backoff and outage budget as a dropped socket.
- **Deviations:**
  - The notice goes to the built-in progress output only (terminal + notebook), not to the
    user's `on_event` and not to the public `Event` set (spec Q1, owner decision).
  - The 5xx backoff applies only after the Run started; a 5xx on the first connect stays
    FATAL (spec Q2).
  - The pre-start Access remint is kept because
    `test_an_access_challenge_retries_with_a_freshly_minted_capability` pins it.
  - The App-restart test is in-process (two App instances with the same secret and the
    same history), not a `docker kill` of a real App. Each App has its own
    `InMemoryEventStream` copy of the history, because an `asyncio.Condition` cannot cross
    the two TestClient loops.
- **Review round 1 (design review: ACCEPT WITH FIXES), applied:**
  1. Post-start Access re-login is bounded: at most `_MAX_RECONNECT_CHALLENGES = 2` in a
     row (reset on a successful connect), each login gets `timeout=` the time left in the
     outage budget, and none starts after the budget is spent. A tripped limit sweeps and
     raises `websocket_disconnected`. RED first; 4 tests (cap and budget, sync and async).
  2. RFC 6455 helpers moved to `tests/_websocket_wire.py`; `_reconnect_engine.py` imports
     them. **Deviation:** `test_run_resume_reconnect.py` keeps its own copy — the
     append-only test gate (`run_gates.py`) protects helper bodies in prior test files, and
     changing a prior test is an owner decision (sdlc rule 5).
  3. Added: 5xx (503/501/505) on the FIRST handshake stays fatal; async budget-exhaustion
     twin; async 5xx covers 502 and 503.
  4. `_is_transient_rejection` reuses `_core/retry.py` `_RETRYABLE_STATUS` (408, 429,
     502-504, 520-524) instead of `>= 500`; 501/505 on a reconnect are fatal (test added).
     `Retry-After` is ignored on purpose (WHY comment): the budget bounds the backoff.
  5. `ConnectionState` → `_ConnectionState`; runtime checks and their test removed;
     `attempt` is optional and `reconnected` sends none.
  6. `_new_app_resume` has a 10 s deadline, woken by 0.2 s heartbeats (the TestClient
     `receive_json` has no timeout). Test 3 (lifetime boundary → 401) is named in the spec
     as an addition outside R6.
  - Gates after the round: `screamingface` ALL GREEN — 1898 passed, 26 skipped, coverage
    96 %; `screamingface-engine` ALL GREEN (NATS-bound tests skipped as above).
- **Follow-ups:**
  - Reaper interaction (review fix 1): while no client is attached, the engine orphan
    reaper (`orphan_grace_s = 120`) counts down. A post-start re-login now fits inside the
    90 s budget, so a slow browser login fails the Run on the client side before the reaper
    does. Owner question Q3 in the spec.
  - Real-socket App-kill test (plan step 6, first bullet): kind case "K-new: delete the
    App pod mid-Run → SDK `Url4CloudTransport.run` completes, sequences 1..N once each,
    report equal to an unkilled Run". Blocker: the kind harness port-forward binds ONE pod
    (`tests/kind/conftest.py` `app_base_url`), so the SDK needs a stable endpoint that
    survives the pod (a NodePort/ingress in `deploy/kind/`, or a local TCP proxy that
    re-forwards). The local kind cluster is shared with other agents, so this unit did
    not kill pods there.
  - Pin the real engine's WS handshake status for an invalid/expired ticket (spec
    2026-08-26 §9 assumption; audit item 19) — still open.
  - Owner questions Q1 (public `Reconnecting` Event?) and Q2 (5xx backoff on the first
    connect?) in `docs/spec/2026-09-28-sdk-reconnect-hardening.md`.
  - OME-1071 not touched: `cancel_active()` still sweeps every Run of the client on a
    fatal reconnect. It did not block these tests.
  - Repeated Access challenges on a reconnect still retry with no backoff and no budget
    (pre-existing; bounded only by `reauthenticate()` raising).
