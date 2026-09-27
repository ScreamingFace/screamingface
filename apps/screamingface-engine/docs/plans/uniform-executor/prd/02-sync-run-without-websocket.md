# PRD: Sync run without a WebSocket

**Source:** prompt, ans:Q1, ans:Q6 · **Priority:** P0 (small change, and PRD 04 builds on it)
**Lifecycle:** existing (characterize + delta)
**Owner:** unassigned

## 1. Summary and user story

As a client that wants one answer (for example a single-model call through the SDK or a
script), I want `GET /?q=<url4>` without `Prefer: respond-async` to work without an open
WebSocket, so that a simple request is one token call and one HTTP call.

## 2. Background and constraints

- "our workflow becomes uniform, no matter if the request is an ensemble or a simple
  request" `[stated prompt]`
- Scope includes "sync without a WebSocket". `[stated ans:Q1]`
- "Keep the token": `POST /token` stays mandatory for `GET /?q=`. `[stated ans:Q6]`
- The App stays at 1 replica. The in-memory registry stays. `[stated ans:Q1 — OME-890 not selected]`
- Component used: INTEREST_SESSION (`erd.md` §8). The shared events stream (PRD 01) carries
  the frames that the sync wait reads.

### 2.1 Current behavior

- `start_run` verifies the JWT, then calls `_require_subscriber(topic)`, which raises 428
  when `has_subscriber` is false. This happens for sync and async requests.
  `[existing rest/routes.py:163-170, 542]`
- `_parse_prefer`: `respond-async` → 202; `wait=<s>` → sync with bound
  `min(wait, sync_max_wait_s)`; no header → sync with bound `sync_max_wait_s` (30 s).
  `[existing rest/routes.py:105-120, 386-392; config.py:133]`
- `_await_terminal` waits for the terminal frame with `asyncio.wait_for`. On timeout,
  `_run_sync` returns 202 through `_accepted`. `[existing rest/routes.py:261, 293, 386]`
- `_terminal_response`: `succeeded` → 200 with the result (inline body, or the artifact file
  streamed with `FileResponse`; 404 if swept); other statuses → 502, 504, 409 problems.
  `[existing rest/routes.py:303-340]`
- `ConnectionRegistry.add/remove` change `subscribers` and fire `audience_arrived` (0 → 1) and
  `audience_left` (1 → 0). The orphan reaper arms a 120 s grace on `audience_left`.
  `[existing ws/registry.py:83-103; reaper.py:116-164; config.py:124]`

**Delta.**

1. A sync request holds interest for its topic while it waits. The registry counts
   `sync_holders` next to `ws_subscribers`.
2. The sync hold starts before the 428 check, so the check passes.
3. The hold ends on terminal frame, on bound timeout, on client disconnect, or on error.
4. `respond-async` requests keep the 428 rule.

## 3. Scenarios and acceptance criteria

### 3.1 Happy path

- **SY-H1.** Given a valid token and no WebSocket for the topic, when the client sends
  `GET /?q=<url4>` with no `Prefer` header, then the App returns 200 with the result body
  and never returns 428. `[stated ans:Q1]`
- **SY-H2.** Given the same request with `Prefer: wait=10`, when the run ends in 4 s, then
  the App returns 200 after about 4 s. `[existing rest/routes.py:386]`
- **SY-H3.** Given a request with `Prefer: respond-async` and no WebSocket, then the App
  returns 428, as today. `[stated ans:Q6]` + `[existing rest/routes.py:542]`

### 3.2 Error paths

- **SY-E1.** Given the run ends `failed`, then the App returns 502 with the problem body, as
  today. `[existing rest/routes.py:332-340]`
- **SY-E2.** Given the run ends `timed_out`, then the App returns 504, as today. `[existing rest/routes.py:332-340]`
- **SY-E3.** Given no token or a bad token, then the App returns 401. The sync hold never
  starts. `[stated ans:Q6]`

### 3.3 Derived scenarios (risk order)

| ID | Title | Tag | I×L |
|---|---|---|---|
| SY-D1 | The reaper does not stop a run that a sync caller waits for | [implied] | H×H |
| SY-D2 | Bound passes: 202, hold released, reaper arms | [implied] | H×M |
| SY-D3 | Client disconnects during the wait | [proposed — gap §per-flow/cancel] | H×M |
| SY-D4 | Sync caller and WebSocket client on the same topic | [implied] | M×M |
| SY-D5 | Second `GET /?q=` with the same token | [existing rest/routes.py 409] | M×M |
| SY-D6 | Exception inside the wait still releases the hold | [proposed — gap §per-flow/failure] | M×M |
| SY-D7 | Admission refuses (503) before a hold leaks | [implied] | M×M |

- **SY-D1.** Given a sync request waits 25 s for a long run, and no WebSocket exists, then
  `audience_left` never fires during the wait, and the reaper never arms for the topic.
- **SY-D2.** Given the bound is 30 s and the run takes 60 s, when 30 s pass, then the App
  returns 202 with `Location` and `Link`, releases the hold, and the reaper arms its 120 s
  grace. When the client attaches a WebSocket within 120 s, then the reaper disarms, and the
  client receives the rest of the frames. When nobody attaches in 120 s, then the reaper
  stops the run (`Terminated(stopped)`).
- **SY-D3.** Given a sync wait is in progress, when the client closes the TCP connection,
  then within 1 s the App stops waiting and releases the hold. The run continues until the
  reaper grace ends, because the client can still attach with its token.
- **SY-D4.** Given a WebSocket and a sync request both hold the topic, when the sync request
  returns, then `audience_left` does not fire. It fires only when the WebSocket also leaves.
- **SY-D5.** Given a run already exists for the token's topic, when the client sends a second
  `GET /?q=`, then the App returns 409 as today, and it takes no hold.
- **SY-D6.** Given `_await_terminal` raises, then the hold count for the topic returns to its
  value before the request.
- **SY-D7.** Given the queue is at capacity, when a sync request arrives, then the App returns
  503 with `Retry-After`, and the hold count is unchanged afterwards.

## 4. Non-functional requirements

- **Latency.** The hold adds no network hop. Target: < 1 ms added p95 in unit timing. Report
  only. `[proposed — ans:Q3]`
- **Disconnect detection.** The App polls `request.is_disconnected()` every 0.5 s during the
  wait. `[proposed]`
- **Observability.** New gauge `screamingface_engine_sync_holders` (current holds). Existing
  `screamingface_engine_orphan_runs_armed` must not rise during SY-D1. `[proposed]`
- **Security.** No change. The token still names the topic. `[stated ans:Q6]`

## 5. Out of scope

- Sync without a token. `[stated ans:Q6]`
- Holds that work across App replicas. `[stated ans:Q1]`
- The mount surface (PRD 04 owns it).

## 6. Open questions

None.

## 7. TDD plan

Order: outside-in from the route, because the risk is in the route order (hold before gate).
Unit level uses the in-memory registry and a fake stream.

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| SYN-C1 | CHAR `async_request_without_ws_returns_428` | unit | [existing rest/routes.py:542] | H×M | passes today |
| SYN-C2 | CHAR `sync_terminal_status_maps_to_200_502_504` | unit | [existing rest/routes.py:332] | M×M | passes today |
| SYN-C3 | CHAR `sync_bound_elapsed_returns_202_with_location` | unit | [existing rest/routes.py:261] | M×M | passes today (with a WS attached) |
| SYN-1 | `sync_request_without_ws_returns_200` | unit | [stated ans:Q1 — SY-H1] | H×H | `registry.hold_sync(topic)` context before `_require_subscriber` when not `respond_async` |
| SYN-2 | `reaper_does_not_arm_while_sync_holder_waits` | unit | [implied — SY-D1] | H×H | audience events on the sum of both counts |
| SYN-3 | `bound_elapsed_releases_hold_and_arms_reaper` | unit | [implied — SY-D2] | H×M | release in `finally` |
| SYN-4 | `client_disconnect_releases_hold_within_1s` | unit | [proposed — SY-D3] | H×M | race `_await_terminal` against a disconnect poll |
| SYN-5 | `audience_left_waits_for_both_ws_and_sync_to_leave` | unit | [implied — SY-D4] | M×M | split counters in `ConnectionRegistry` |
| SYN-6 | `hold_released_when_wait_raises` | unit | [proposed — SY-D6] | M×M | `finally` |
| SYN-7 | `admission_503_leaves_hold_count_unchanged` | unit | [implied — SY-D7] | M×M | the hold must start before the 428 gate, so one `async with` block covers gate + `_schedule` + wait; the 503 exits the block and releases the hold |
| SYN-8 | `duplicate_topic_409_takes_no_hold` | unit | [existing — SY-D5] | M×M | check order |
| SYN-9 | `sync_holders_gauge_tracks_holds` | unit | [proposed] | L×M | gauge in `metrics.py` |
| SYN-10 | `sync_without_ws_end_to_end_on_real_nats` | integration | [stated ans:Q1] | H×M | real JetStream + fake child (test_worker_spine style) |
| SYN-11 | `bad_token_401_takes_no_hold` | unit | [stated ans:Q6 — SY-E3] | M×M | JWT dependency runs before the hold block |

**Refactor notes.** Keep `SubscriberGate.has_subscriber` as the only read used by the gate.
Add `hold_sync(topic)` as an async context manager on the registry, not a new protocol
method on the gate.
