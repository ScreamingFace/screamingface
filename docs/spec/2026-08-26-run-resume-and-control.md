---
title: Run control-plane resilience — resumable streams and stoppable runs
status: approved-design, pending-implementation — owner decisions D1–D5 recorded 2026-08-26 (§10)
created: 2026-08-26
ticket: OME-1016 (epic) — sub-issues OME-1017 (R1), OME-1018 (R2), OME-1019 (R3), OME-1020 (R4); related OME-890 (subscriber-loss reaper, Done)
source: incident of 2026-08-26 14:58 UTC (App deployment closed 3 in-flight Runs with close 1012);
        related GitHub issue #737 (separate spec: fusion member failure resilience)
---

# Run control-plane resilience

## Outcome

A Run survives an Engine App restart. The SDK reconnects, replays the missed frames, and
returns the normal Report. Every Run stays stoppable by its owner for its whole life. No Run
continues to spend after its caller is gone.

```text
                       deploy: App pod replaced
                                │
client ── ws ──► old pod  ──X (close 1012)
client ◄───────────────────────┘  disconnected
client ── ws ──► new pod  ──► attach(from_sequence = last seen + 1)
client ◄── replay of missed frames from the JetStream log ── Result, Terminated
```

## 1. Incident (verified, 2026-08-26)

| Time (UTC) | Event | Evidence |
|---|---|---|
| 14:31:08 | Evaluation schedules 8 Runs (9 candidates, cap 8) | App log `run scheduled` ×8 |
| 14:33:37 | PR #751 merges to main | GitHub |
| 14:44:24 | New pod created (image rollout) | k8s pod start time |
| 14:39–14:56 | 6 Runs complete normally | `ws stream ended … close 1000` |
| 14:58:03 | Old pod SIGTERM; uvicorn closes live sockets with **1012** | `INFO: Shutting down` |
| 14:58:03 | 3 Runs die mid-flight; SDK raises `websocket_disconnected` | `close 1012`, durations 1615.2 s, 1615.2 s, 1081.6 s |

The Runner Jobs are separate pods. They kept running and publishing to their NATS streams
until completion, then reclaimed the streams after the 60 s grace. The token spend had no
consumer. The client could not re-attach, and could not stop the Runs.

## 2. Root cause — one claim carries three different concerns

The capability token is an HS256 JWT with `sub = topic` (unguessable, 64 chars). Its lifetime
is the mint freshness window:

- `auth/jwt.py:36-47` — `sign()` sets `exp = iat + iat_window_s`.
- `auth/jwt.py:72-77` — `verify()` rejects `now - iat > iat_window_s` **and** `now >= exp`.

`iat_window_s` is 60 s. So the token answers three questions with one 60-second answer:

1. *Freshness of the mint* (an anti-replay concern) — legitimately 60 s.
2. *May the holder attach to the topic's stream?* — needed for the whole Run, up to 16 h.
3. *May the holder stop the Run or redeem its result?* — needed for the whole Run.

Three features of the codebase exist **because** of this conflation, each a work-around:

- The Runner reclaims its own stream (`run_and_reclaim`, `runner/main.py:113`): the comment
  records that tokens "expire 60 s after minting and cannot be re-issued for an existing
  topic, so any run longer than a minute could never tear its own stream down".
- Artifact redemption mints a **fresh** token (`transport.py::_materialize_*`): "Capability
  tokens live ~60 s while an evaluation can run for hours... reusing one 401s".
- The abort sweep is defeated in practice: `_evaluation/runner.py:382-389` calls
  `transport.cancel_active()` on every abort, but each `DELETE /` presents a token older than
  60 s → 401 → `AuthenticationError` → the sweep swallows it as a note. This is the exact
  mechanism that orphaned the 3 Runs in the incident.

## 3. What already exists (and must be reused, not rebuilt)

- **Durable sequenced log per Run.** The Runner publishes every frame to a per-topic NATS
  JetStream stream. It survives the App pod. Frames carry a broker-stamped `sequence`.
- **Client cursor and gap replay.** The SDK's `_RunState` tracks `_last_sequence`, detects
  gaps, and answers with `replay_from` — the transport then sends `attach(from_sequence=N)`
  on the *same* socket (`run_lifecycle.py::accept`). Deduplication is by sequence and event
  id. Reconnect is the same mechanism on a *new* socket.
- **Bridge re-attach.** `ws/bridge.py` accepts attach with `from_sequence` at any time, from
  any pod; it cancels the old subscription and replays from the cursor. Multiple sockets per
  topic are permitted.
- **Stop path.** `DELETE /` stops the Job and deletes the stream; it needs a verified token
  for that topic.
- **Subscriber-loss reaper (OME-890, shipped).** When a topic's last subscriber disconnects,
  the App arms `orphan_grace_s = 120` and stops the Run through `JobRunner.stop` if nobody
  re-attaches inside the window. This covers a client that vanishes while the App lives. It
  does NOT cover the App itself dying (the registry is in-memory) — the incident's case —
  which is what S1+S3 close. Its grace window also bounds S3's reconnect budget (§6 S6).

The missing piece is one: a session credential that survives the Run.

## 4. Goals

- **G1** A Run whose stream connection dies (deploy, network, pod loss) completes normally on
  the client after reconnect and replay.
- **G2** A Run is stoppable by its caller at any age.
- **G3** No Run outlives a caller that abandoned it (disconnect, abort, crash) without a stop
  attempt that can actually succeed. Same-pod disconnects are already covered by the OME-890
  reaper (`orphan_grace_s = 120`); this spec adds the cross-pod case (the App itself died —
  the reaper's registry is in-memory and dies with it), via the long-lived token making the
  sweep's `DELETE /` succeed (S1) plus the transport-level sweep (S3).
- **G4** Deploys need no coordination with in-flight Runs.
- **G5** Old SDKs against the new Engine keep today's behavior — with their abort sweeps
  starting to work (long-lived tokens make `DELETE /` succeed at any Run age). A mixed
  old-engine fleet is out of scope per D5: one engine is deployed, merges deploy promptly.

## 5. Non-goals

- No identity-bound Run registry (account-scoped resume). Local mode is anonymous by design;
  identity binding does not exist there.
- No change to Runner execution, benchmarks, or billing.
- No multi-App failover orchestration beyond what the rolling update already gives.

## 6. Design

### S1 — Split token lifetime from mint freshness (Engine, `auth/jwt.py`)

- `sign()`: `exp = iat + capability_lifetime_s` (new `Settings.capability_lifetime_s`,
  proposed default `58_800` s = 16 h Job deadline + 1 h slack; §10 D1).
- `verify()`: replace the age check `now - iat > iat_window_s` (lifetime semantics) with a
  future-iat check `iat - now > iat_window_s` (clock-skew tolerance; keep the 60 s default and
  the field name, re-documented). The `exp` check is unchanged and becomes the only lifetime
  rule.
- Boundary semantics pinned by tests: accept at `exp - 1`, reject at `exp`; reject an `iat`
  more than one window in the future; accept normal skew.

What a holder gains: attach (read their own Run's telemetry), stop (destroy their own Run),
start (already single-shot: 409 on replay), artifacts (unchanged — the artifact route is not
topic-scoped today; it admits any valid token against an unguessable content address, so the
lifetime change adds nothing there).

### S2 — Make "stream reclaimed" an explicit, typed answer (Engine, `ws/`)

Today an attach to a topic whose stream was deleted surfaces as a `stream_failed` error frame
(pump exception), which a reconnecting client cannot distinguish from a transient failure.

- The bridge maps "stream not found" from the consumer to a typed terminal error frame,
  `ai.url4.error` with `code = stream_reclaimed`, instead of the generic `stream_failed`.
- The SDK treats `stream_reclaimed` as final: the Run finished while the client was away and
  the Runner reclaimed the stream (grace elapsed). Raise `run_result_lost`, not
  `websocket_disconnected`.

### S3 — Reconnect state machine (SDK, `_engine/transport.py`, both sync and async twins)

State machine (explicit; one enum, no scattered booleans):

```text
CONNECTING ──► ATTACHED ──► stream loop ──► OUTCOME
     ▲             │ ws error / close 1012|1001|1006 / OSError
     └── BACKOFF ──┘        (any cause; budget not spent)
BACKOFF ── handshake 401/403 (not Access) ──► FATAL websocket_disconnected   (dead credentials)
BACKOFF ── connect refused / 5xx / timeout ──► BACKOFF (full jitter, cap 15 s)
ATTACHED (resumed) ── attach(from_sequence = last) ──► dedup by sequence/id (existing)
ATTACHED ── stream_reclaimed frame ──► FATAL run_result_lost
BACKOFF budget exhausted (90 s total per Run, D2 ceiling 120 s — §6 S6) ──► SWEEP ──► FATAL
```

- Reconnect reuses the SAME token (S1 makes it valid). `attach(from_sequence =
  _RunState._last_sequence)` — identical to today's in-connection gap replay.
- BACKOFF pacing: full-jitter delays 0.5 s doubling to a 15 s cap; total budget
  `_RECONNECT_BUDGET_S = 90`, cumulative across the Run's lifetime, not per disconnect —
  pinned BELOW D2's 120 s ceiling by the reaper race (§6 S6).
- The existing Access-challenge branch (`InvalidStatus` with a challenge audience) stays first:
  re-authenticate, then re-attach. With long-lived tokens there is no re-mint on this path.
- On FATAL after a disconnect, run `cancel_active()` before raising (G3). The sweep is already
  wired at the evaluation level; the transport-level sweep covers single-candidate Runs.
- The 120 s inter-frame watchdog and the engine's ~30 s heartbeats are unchanged; heartbeats
  from the new pod satisfy the watchdog.
- Cache-policy "first attach wins" is pod-local registry state; a re-attach on the new pod
  re-declares the same policy the SDK already holds. No divergence path exists (one Run, one
  client, one policy).
- Progress UI: while in BACKOFF, render "SF Engine connection lost — reconnecting (attempt
  n)". The Run itself is unaffected.

### S4 — The reclaim race, stated honestly

If the Run TERMINATES while the client is disconnected and the Runner's grace
(`STREAM_GRACE_S`, default 60 s) elapses before re-attach, the stream is deleted and the
result is unrecoverable (inline result gone; spilled artifact's id rode the deleted stream).
The client fails with `run_result_lost` (S2) — an honest outcome, not a hang.

Options were keep 60 s or raise it. Disk math from the incident: one Run produced ~112 k
frames; at ~300 B/frame that is ~34 MB held per finished Run for each extra grace minute.
DECIDED (D3, 2026-08-26): keep 60 s; revisit with data. Interaction with D2: a Run that
terminates while the client is disconnected for 60–120 s lands in `stream_reclaimed`
(`run_result_lost`) rather than resume — the honest outcome.

### S5 — Drain notice before close (Engine) — OUT OF SCOPE FOR v1 (D4)

Deferred by owner decision D4 (2026-08-26). Recorded for a future iteration: on shutdown,
before uvicorn closes sockets, push one notice frame to every attached topic
(`engine_draining`, with a retry hint) — the GOAWAY pattern, one `sessions.notify` fan-out in
the lifespan shutdown path. Purely advisory; S3 reconnects correctly with or without it.

### S6 — Interaction with the OME-890 reaper

The reaper stops a Run whose last subscriber has been gone for `orphan_grace_s = 120` s. A
reconnecting client is EXACTLY such a subscriber gap — so the reconnect budget must land
strictly inside the reaper's grace, or a client still backing off at t≈120 s loses its Run
to the reaper one attempt before giving up. Hence `_RECONNECT_BUDGET_S = 90` (within D2's
ceiling, with margin for the reaper's sweep latency — reap fires at grace to grace +
grace/8).

If the reaper wins anyway (budget raised, grace lowered), the outcome stays honest: the
re-attach replays the `Terminated(stopped)` frame the reaper's stop produced, and the SDK
reports the stopped outcome — no hang, no silent loss. The race costs work, not
correctness.

## 7. Contract changes

| Contract | Change | Compatibility |
|---|---|---|
| Capability JWT | `exp` = mint + `capability_lifetime_s`; `iat` check = future-skew only | Old SDKs keep today's behavior and their stops IMPROVE (see below). Mixed old-engine fleet: out of scope per D5 — one engine is deployed, merges deploy promptly. No version field needed. |
| WS error frames | new typed `stream_reclaimed` code | additive; unknown codes already surface as generic errors on old SDKs |
| Notice frames | none in v1 (drain notice dropped, D4) | — |
| REST | none (all routes unchanged) | — |

## 8. Security review

- No new endpoints; mint stays unauthenticated (unchanged surface).
- Bearer exposure grows from 60 s to the Run horizon for: read-own-stream, stop-own-run,
  start (single-shot, 409 on replay), artifacts (route is already token-agnostic; the id is an
  unguessable content address). The stream may carry the Run's answer text — a stolen token
  leaks one Run's output. Tokens live in SDK process memory only and are never logged
  (pinned by existing auth error invariants). Accepted: the exposure is one Run, owned by the
  caller.
- DoS: minting tokens creates topics but schedules nothing without an attach and a start;
  unchanged.
- The 401 responses remain uniform (no oracle about which check failed) — `dependencies.py`
  is untouched.

## 9. Test strategy

Characterization first (pin today's behavior):

1. 1012 mid-Run → `websocket_disconnected` is fatal (today).
2. Abort sweep on a Run older than 60 s → stop fails with 401, note attached (today).

New — engine unit: codec boundary table (accept `exp-1`, reject `exp`; future-iat skew;
old-style age rejection is gone); bridge `stream_reclaimed` mapping.

New — SDK unit (fake sockets): disconnect at frame N → resume from N+1, no duplicates
(sequence dedup); missed Result+Terminated replayed after reconnect; handshake 401 → FATAL
fast (invalid or rotated token); budget exhaustion → `cancel_active` called, then FATAL;
`stream_reclaimed` → `run_result_lost`; Access-challenge during reconnect re-authenticates.

Integration (compose): kill the App container mid-Run → SDK completes the Run from the new
container; stop a Run older than 60 s via `DELETE /` (401 before, 204 after).

Live verification: deploy during a 9-candidate evaluation; expect zero failed candidates.

Gaps and assumptions: exact WS rejection codes for an invalid ticket during handshake are to
be pinned in implementation (S3 classification step); multi-node App deployments rely on the
ingress routing re-attach to any pod — assumed supported (stateless App, topic in ticket).

## 10. Owner decisions

- **D1 — DECIDED 2026-08-26:** `capability_lifetime_s = 58_800` (16 h Job deadline + 1 h).
- **D2 — DECIDED 2026-08-26:** reconnect budget ceiling 120 s total per Run (backoff 0.5 s
  doubling, 15 s cap, full jitter; cumulative across the Run, not per disconnect).
  IMPLEMENTATION NOTE (post-decision discovery): OME-890's reaper `orphan_grace_s` is 120 s,
  so the budget lands at **90 s** — strictly inside the grace (§6 S6); still within the
  decided ceiling.
- **D3 — DECIDED 2026-08-26:** `STREAM_GRACE_S` stays 60 s; revisit with data.
- **D4 — DECIDED 2026-08-26:** S5 drain notice is out of scope for v1.
- **D5 — DECIDED 2026-08-26:** Option A — no probe, no capability field. A handshake 401/403
  (after ruling out the Access challenge) is terminal: stop retrying, sweep, fail. The
  mixed-version fleet that motivated the question is out of scope by owner statement: one
  engine is deployed, and merges are deployed promptly, so no "old engine" exists.

All decisions (D1–D5) are answered. Implementation starts on explicit approval in plain
words; work items: `docs/plan/2026-08-26-run-resume-and-control.md`.

### 10.1 D5 — why the 401 rule needs no engine version probe

(Background for the record; the decision above closes it.) Even with a single engine, a
reconnect handshake can still be rejected 401 for genuinely dead credentials (lifetime
expired, signing secret rotated) — and "fail fast on 401" is the correct answer for that
case too, so the rule needs no way to distinguish causes. The tempting alternative — mint a
fresh token and retry — is wrong by construction: a fresh mint binds a NEW random topic and
attaches to a different, empty stream. Rejected option B (a `capabilities` field on
`POST /token`) would only have improved an error message for a fleet that no longer exists.
