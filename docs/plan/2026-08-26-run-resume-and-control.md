# Run control-plane resilience — Plan

Spec: `docs/spec/2026-08-26-run-resume-and-control.md`
Incident: 2026-08-26 14:58 UTC (App deploy closed 3 in-flight Runs with close 1012)
Status: draft — spec decisions D1–D5 recorded 2026-08-26; Linear cut: OME-1016 (epic),
OME-1017 (R1), OME-1018 (R2), OME-1019 (R3), OME-1020 (R4); related OME-890 (reaper).
Decisions applied: capability lifetime 58 800 s; reconnect budget 90 s (D2 ceiling 120 s,
pinned below the OME-890 reaper's 120 s grace — spec §6 S6); stream grace 60 s;
R5 (drain notice) removed from v1; no engine-version probe (D5 — single deployed engine,
deploy-on-merge, so no old-engine fleet).

## 0. Work-item structure (per CLAUDE.md rule 8: cross-cutting)

One Linear epic plus one sub-issue per app/package. Linear is the authority; mirror each in
`docs/tasks/`. Cut these before Step 1 (owner action, MCP only):

| # | Sub-issue scope | App/package | Steps | Depends on |
|---|---|---|---|---|
| R1 · OME-1017 | Characterization tests: pin today's fatal-1012 and dead sweep | screamingface-engine, screamingface (SDK) | 1 | — |
| R2 · OME-1018 | Token lifetime split (`capability_lifetime_s`, skew-only iat check) | screamingface-engine | 2 | R1 |
| R3 · OME-1019 | Typed `stream_reclaimed` error frame | screamingface-engine | 3 | R1 |
| R4 · OME-1020 | Reconnect state machine + transport-level sweep | packages/screamingface | 4 | R2, R3 |

~~R5 (drain notice)~~ — removed from v1 by owner decision D4 (2026-08-26).

Rollout order: engine first (R2, R3 — safe, independent), then SDK (R4).
Compatibility is one-directional by owner decision D5: one engine is deployed and merges
deploy promptly, so no old-engine fleet exists. Old SDKs against the new engine keep today's
behavior — and their abort sweeps START WORKING, because the long-lived token makes
`DELETE /` succeed for Runs older than 60 s. The engine deploy alone therefore closes the
orphaned-spend half of the incident; R4 adds resume.

Every unit: worktree from `origin/main` (`.claude/worktrees/OME-N-<desc>`), ledger from
`docs/work/TEMPLATE.md` at start, PR with `Refs: OME-N`, green CI, squash-merge.

## Step 1 — RED: characterization (R1)

Engine (`apps/screamingface-engine/tests/unit/test_auth.py` vicinity):
- Pin: a token older than `iat_window_s` is rejected **and** a token with a future `exp` is
  still rejected by the age check (documents the conflation being removed).

SDK (`packages/screamingface/tests/…`, transport tests):
- Pin: a close-1012 mid-Run raises `ExecutionError(code="websocket_disconnected")`.
- Pin: `cancel_active()` with a token the server rejects raises; the evaluation sweep records
  the note and the Runs continue (today's orphan mechanism).

These tests pass before any change. Steps 2–4 flip specific assertions deliberately, each in
its own commit naming the spec section.

## Step 2 — Engine: token lifetime (R2)

Files:

| File | Change |
|---|---|
| `src/screamingface_engine/auth/jwt.py` | `sign()`: `exp = iat + capability_lifetime_s`. `verify()`: replace `now - iat > iat_window_s` with `iat - now > iat_window_s` (future-skew); `exp` check unchanged |
| `src/screamingface_engine/config.py` | new `capability_lifetime_s: int = 58_800` (D1); re-document `iat_window_s` as skew tolerance — its docstring currently states the OLD invariant ("start rejected when now - iat exceeds it"), which R2 deletes
| `src/screamingface_engine/auth/dependencies.py`, `rest/routes.py`, `ws/endpoint.py` | none (they pass `iat_window_s` through unchanged) |
| `tests/unit/test_auth.py` | boundary table: accept `exp - 1`, reject at `exp`; reject iat > now + window; age no longer rejects within lifetime |

RED first: write the boundary table against the NEW semantics; it fails. Then GREEN.
Gates: `python3 .claude/scripts/run_gates.py screamingface-engine`.

## Step 3 — Engine: typed reclaimed-stream answer (R3)

| File | Change |
|---|---|
| `src/screamingface_engine/ws/bridge.py` | `_on_pump_done`: classify "stream not found" from the consumer as `ai.url4.error` with `code="stream_reclaimed"`; keep `stream_failed` for other pump errors |
| `src/screamingface_engine/adapters/jetstream.py` (consumer) | surface "stream not found" as a distinguishable exception/type at the `EventConsumer` boundary |
| `tests/unit/…` | attach to a deleted stream → one `stream_reclaimed` frame; transient broker error → `stream_failed` as today |

Gates: `python3 .claude/scripts/run_gates.py screamingface-engine`.

## Step 4 — SDK: reconnect state machine (R4)

All changes in `packages/screamingface/src/screamingface/_engine/transport.py` and
`run_lifecycle.py`/`contract.py` only as needed; mirror in both sync and async twins.

1. Extract the resume cursor: expose `_RunState._last_sequence` through `_Lifecycle` (the
   `replay_from` path already computes it for gaps; add a getter for cross-connection use).
2. Add the state machine (one `enum`, transitions per spec §6 S3; no scattered booleans):
   - On `(WebSocketException, OSError, TimeoutError)` AFTER the start was accepted and BEFORE
     an outcome: enter BACKOFF, not FATAL.
   - BACKOFF: full-jitter delays 0.5 s doubling to a 15 s cap; total budget
     `_RECONNECT_BUDGET_S = 90` (D2 ceiling 120 s; 90 s is pinned STRICTLY INSIDE the
     OME-890 reaper's `orphan_grace_s = 120` — spec §6 S6 — so a reconnecting client never
     loses its Run to the reaper mid-backoff). Budget is cumulative across the Run's
     lifetime, not per disconnect.
   - Reconnect: same ticket; `attach(from_sequence = cursor)`; existing sequence/event-id
     dedup absorbs replayed frames.
   - Classify failures: Access-challenge (`_is_access_websocket_rejection`) → existing
     re-auth branch first; handshake 401/403 otherwise → FATAL (genuinely dead credentials:
     lifetime expired or secret rotated — no probe, D5); refused/5xx/OS
     errors → keep backing off; `stream_reclaimed` frame → FATAL
     `ExecutionError(code="run_result_lost", permanent=True)`; budget exhausted → sweep then
     FATAL `websocket_disconnected`.
   - Transport-level sweep: on FATAL-after-disconnect, call the same stop helper the
     evaluation sweep uses, so single-candidate Runs are also covered (G3).
3. Progress UI: emit an event/notice on each BACKOFF attempt ("reconnecting, attempt n");
   the widget renders it as a line, not a failure.
4. Pin the exact handshake rejection codes for an invalid ticket against a real engine in the
   integration environment (spec §9 assumption) before freezing the classification.

Tests (fake sockets/fake server): the matrix from spec §9 — resume without duplicates;
missed terminal replayed; 401 → fast FATAL; budget exhaustion → sweep called; reclaimed →
`run_result_lost`; Access challenge → re-auth then resume; two sequential disconnects.

Gates: `python3 .claude/scripts/run_gates.py screamingface`.

## Step 5 — (removed from v1, D4)

The drain notice was dropped by owner decision. If revisited: fan out one
`engine_draining` notice to every registered topic via the session registry's notifiers in
`app.py`'s lifespan shutdown path.

## Step 6 — Integration + live verification

- Compose test: start a Run; `docker kill` the App container mid-Run; SDK completes the Run
  after restart; report identical to an unkilled Run.
- Compose test: `DELETE /` a Run older than 60 s → 204 (was 401).
- Live: trigger a deploy during a 9-candidate evaluation; expect 0 failed candidates, and
  SigNoz shows `ws stream ended … 1012` followed by successful re-attaches on the new pod.

## Files (indicative, all units)

| File | Unit | Change |
|---|---|---|
| `apps/screamingface-engine/src/screamingface_engine/auth/jwt.py` | R2 | lifetime/skew split |
| `apps/screamingface-engine/src/screamingface_engine/config.py` | R2 | `capability_lifetime_s` |
| `apps/screamingface-engine/src/screamingface_engine/ws/bridge.py` | R3 | typed reclaimed frame |
| `apps/screamingface-engine/src/screamingface_engine/adapters/jetstream.py` | R3 | distinguishable not-found error |
| `apps/screamingface-engine/src/screamingface_engine/app.py` | — | no change in v1 (R5 dropped, D4) |
| `packages/screamingface/src/screamingface/_engine/transport.py` | R4 | reconnect state machine, both twins |
| `packages/screamingface/src/screamingface/_engine/run_lifecycle.py` | R4 | cursor getter |
| `packages/screamingface/src/screamingface/_engine/contract.py` | R4 | (only if the cursor needs exposing) |
| `packages/screamingface/src/screamingface/_ui/…` | R4 | reconnecting line |

## Risks

| Risk | Mitigation |
|---|---|
| Bearer token valid for the run horizon | spec §8: exposure is one Run's own stream/stop; tokens never logged; accepted |
| Reconnect storm on many clients after a deploy | full jitter + 15 s cap; budget bounded; heartbeats not required during BACKOFF |
| `stream_reclaimed` misclassification (transient broker error read as reclaim) | Step 3 types the error at the consumer boundary; unit tests pin both branches |
| Reclaim race (terminal during outage > grace) | documented (spec §6 S4); honest `run_result_lost`; grace dial is D3 |
| Sync/async twin divergence | the state machine is one pure function over events; twins provide I/O only |

## Definition of done

- Killing the App mid-Run in compose and in the dev cluster loses no candidate.
- A Run older than 60 s is stoppable by its caller (204, not 401).
- The orphan note from the incident ("stop also failed") no longer occurs on deploys.
- Spec §10 D1–D5 answered and recorded; ledgers closed; Linear closed in both places.
