# Implementation notes: uniform executor

This file records where the build deviates from the PRDs, and why. It also records the
residual risks that the build accepts. Read it with the PRD of each phase.

Status: phases 1–3 built; phase 4 (PRD 04) built for production, local mode open on branch `exp/uniform-executor`. Exploratory work: the SDLC
steps (ticket, ledger) were skipped on the owner's instruction. Phase 0 is partial: the CHAR
tests of PRD 01 exist; the kind environment and the measurement harness do not exist yet.

## Phase 1 — shared events stream

### Deviations

| # | PRD text | Built | Reason |
|---|---|---|---|
| D1 | EV-H4, EV-D11: after the reclaim, "the stream holds no frame for the topic" | The reclaim (`delete_stream`) purges the subject with `keep=1`. The terminal frame stays until `max_age` (24 h). | The terminal frame is the evidence that a run is over. The worker dedupe gate reads it on redelivery, and App admission reads it to free a caller slot. In the old layout "the per-run stream is gone" was also evidence. A shared stream has no per-run object, and an empty subject is also the state of a queued run. |
| D1a | (not in PRD) | The admission path "stream absent after 90 s ⇒ run finished" (OME-1108, `reclaim_evidence_after_s`) is removed. | With D1 it is not necessary. With a shared stream it is wrong: it would free the slot of a run that waits in the queue for longer than 90 s. |
| D2 | (not in PRD) | Queued-cancel tombstone guard: "no frame and no stream ⇒ no-op" became "no frame and the App did not schedule the topic (`_scheduled_at`) ⇒ no-op". | An empty subject says nothing about the queue. |
| D3 | (gap in PRD) | Redelivery rebase: the first frame that a publisher stores for a run reads the subject tail, and every frame of the run is offset by it. | The url4 producer numbers every run from 1. A redelivered run (`max_deliver=2`, test K7) would write 1..n again on a subject that has 1..k. The client drops those frames as duplicates, and `Nats-Msg-Id=<topic>:<seq>` makes the broker drop them too. |
| D3a | (gap in PRD) | If the tail is terminal when a run starts (the tombstone won the race with the claim), the publisher drops the run's frames. | I-EV4: nothing follows the terminal frame. |
| D4 | Refactor note: callers use `publish_next` | `publish()` sends an unsequenced frame to `publish_next`. The three non-child writers (supervisor, App tombstone, max-deliveries advisor) keep calling `publish()`. | The url4 port contract (`EventPublisher.publish`, `assert_stream_conformance`) publishes unsequenced frames and expects the adapter to number them. Refusing them breaks the port. The child's url4 producer always sequences its frames. |
| D5 | (gap in PRD) | A duplicate `PubAck` in `publish_next` is a conflict only when the subject tail moved. Otherwise the writer retries with a message id that is unique to its frame. | The broker checks `Nats-Msg-Id` before `Nats-Expected-Last-Subject-Sequence`. So a late child frame at the same sequence shows as a *successful* duplicate, not as a conflict. After a full purge, a reused id matches a purged frame. |
| D6 | url4 contract: "purge keeps the counter" | The check moved to the reclaim (`_reclaim_keeps_counting`). `purge` only drops frames. | A full subject purge has no counter to keep, because the producer sequence lives in the frames. `purge` has no production caller for JetStream. |
| D7 | erd.md §10: "After deploy, run `purge-legacy-streams`" | The order is: drain → `admin purge-legacy-streams` (new image) → deploy. Startup fails and names the command while a legacy stream exists. | JetStream refuses `url4-cloud.*` while a legacy `url4-cloud_<topic>` stream holds an overlapping subject (err 10065). |
| D8 | EV-D10 / resume | `StreamNotFoundError` is raised only when the first retained frame is the kept terminal frame and it is above the cursor. For an empty subject the consumer waits. For a live run that lost its oldest frames, it resumes at the head. | A resume cursor is a producer sequence, which has no stream position. A live run that rolled over (EV-D6, ans:Q11) is not finished. |

### Residual risks (accepted)

| Risk | Window | Detection |
|---|---|---|
| A late frame from a dead child lands after the supervisor's terminal frame. The child's frame at `last+1` is dropped as a duplicate id, and its next frame is stored after the terminal frame. | The child has exited before the supervisor classifies it, so only frames that the broker has not processed yet can be affected. This exists in the old layout too. | The tail of such a run is not terminal: the dedupe gate and admission read it as "not finished" until the lease (1 h) ends. |
| A queued cancel is lost after an App restart (D2 uses App memory). | Between an App restart and the claim of a run that was queued before it. | After a restart, `status()` also reports such a run as `not_found`. The App stays at 1 replica by plan (ans:Q1). |
| `events_subject_purges_total` counts only App purges (`DELETE /`). | The runner purges in the child, which has no scrape endpoint. | Documented in the metric help text. |

### Validation done

- Integration against a real JetStream (`tests/integration/test_events_stream.py`, 27 tests).
  This includes EVT-C1, EVT-2..EVT-15, EVT-17, redelivery, conflict races, rollover resume and
  the legacy-overlap startup error.
- Linux container run of the worker spine and the child OOM cap (`RLIMIT_AS` does not work on
  macOS).

### Not done in phase 1

- EVT-16 (NATS restart during a run) and the kind cases K1, K6, K10, K11, K12: they need the
  kind environment (phase 0).
- The throughput measurement (2 000 frames/s): it needs the measurement harness.

## Phase 2 — sync run without a WebSocket

### Built as the PRD says

- `ConnectionRegistry` counts `subscribers` (WebSocket) and `sync_holders`. The audience events
  and `has_subscriber` use the sum. `hold_sync(topic)` is an async context manager on the
  registry (and on the `RunSessions` port), not a new method on the gate.
- A sync `GET /?q=` holds the topic in ONE `async with` block around the gate, the schedule and
  the wait. So every exit releases it: terminal frame, bound (202), client disconnect (polled
  every 0.5 s), admission 503, or an error.
- `respond-async` keeps the 428 rule.
- Gauge `screamingface_engine_sync_holders`.

### Decisions the PRD left open

| # | Decision | Reason |
|---|---|---|
| P2-1 | The existence check (409, or 503 when unreadable) moved out of `_schedule` into its own step, BEFORE the hold. | SY-D5 / SYN-8. The hold is an audience change, and the orphan reaper listens to audience changes. A duplicate request that held the topic for a moment would disarm and re-arm the reaper of the run that is already there, and reset its grace. |
| P2-2 | A sync request validates everything (q, answer seed, traceparent, the 409 check) before it takes the hold. An async request keeps the old order (the 428 comes before those checks). | A request that fails validation must not touch the audience. |
| P2-3 | On a client disconnect the App returns (to nobody) a 202 and does NOT stop the run. | SY-D3: the token can still attach within the reaper grace. PRD 04 (mount calls) stops the run instead (ans:Q9). |

### Tests changed on purpose

Four existing tests pinned "a SYNC request without a WebSocket returns 428". PRD 02 changes that
behavior (SY-H1). Each test now sends `Prefer: respond-async`, so it still pins the gate:
`test_rest.py::test_async_get_without_subscriber_is_428` (SYN-C1),
`test_ws.py::test_live_ws_enables_start_and_closing_it_restores_428`,
`test_ws_cache_policy.py::test_run_start_stays_gated_on_an_attached_subscriber`,
`test_client_provenance_wiring.py::test_rejected_admission_does_not_publish_version`,
`test_local_spine.py::test_a_run_without_an_attached_subscriber_is_refused`.

### Validation done

- Unit: `tests/unit/test_rest_sync_hold.py` (SYN-1..SYN-9, SYN-11), with the real registry and
  reaper; SYN-4 drives the ASGI app with a raw `http.disconnect`.
- Integration: `tests/integration/test_sync_without_ws.py` (SYN-10) on a real JetStream.

### Not done in phase 2

- Kind case K2 (needs the kind environment).
- The latency measurement of the hold (< 1 ms p95, report only).

## Phase 3 — warm child pool

### Built

- `child_protocol.py` (stdlib only): `READY {"pid","world"}` and `ACK` on a control pipe, one
  RUN_SPEC JSON line on stdin (max 1 MiB, `spec_version` "2").
- `worker/warm_pool.py`: `WarmChildPool` keeps `size` warm children, hands a run to one, retries
  once when a child dies before its ACK, backs off 1, 2, 4 … 30 s after warm failures, kills a
  child that is not READY in 60 s, and terminates idle children first on drain.
- `runner/main.py`: `run --warm` → `warm_up` (per-process work), READY, read one spec, ACK, then
  the normal run with the already-connected publisher. Stdin EOF before a spec → exit 0.
- The supervisor starts a run through a launcher port. The io budget is read at hand-off, and
  the hard wall starts when the launcher returns (after the ACK).
- Setting `worker_warm_children` (default: one per slot, capped at the slots), chart value
  `runnerPool.warmChildren`, four metrics (`worker_warm_children`,
  `worker_warm_spawn_failures_total`, `worker_handoff_latency_s`, `worker_child_boot_s`).

### Deviations

| # | PRD text | Built | Reason |
|---|---|---|---|
| W1 | "the world is built" in the warm phase | The warm phase does the imports, the broker connection (and stream declaration) and the world-config parse. The world itself is still built lazily on the run's first `execute`. | `build_executor` and the world depend on per-run keys: `TOPIC` (the io wrapper), `EXTRA_MODELS` (the routes), and the request scope (identity, profile, seed). Building them before the spec breaks WRM-4. A world that is split into a per-process part and a per-run part is a refactor of `world/factory.py`, and it is not in this phase. |
| W2 | WC-D10: "one code path" | Production always uses the pool (`size=0` included: spawn on claim through the same protocol). The supervisor's `spawn=` test seam keeps `DirectLauncher` (a cold spawn with the whole environment). | About 56 existing supervisor tests drive fake processes through `spawn=`. The supervisor logic under them (dedupe, heartbeat, hard wall, classification, cancel) did not change. The pool has its own tests, and the worker spine runs a real process through the pool. |
| W3 | C5: "fd 3" | The control pipe's fd number travels in `URL4_CLOUD_CONTROL_FD`. | `pass_fds` keeps the parent's fd number, which is not 3. |
| W4 | (gap) | A new line, `REFUSED <code>`. A refused spec is not retried, and the terminal frame carries the code (`unsupported_spec_version`, `spec_malformed`, `spec_too_large`). | A new child would refuse the same spec. An exit code alone cannot tell a refusal from a crash before the ACK. |

### Design review fixes (before commit)

- A cancel during the hand-off (spec written, no ACK yet), during a READY wait, or while an idle
  child is taken now kills the child. Before, the child could ACK and run with no supervisor,
  and the message would redeliver and run it again.
- An ACK timeout is final (`spawn_failed`), not retried: a slow child may have ACKed and started.
- A spec over 1 MiB is refused before any child sees it (`spec_too_large`); the spec JSON keeps
  non-ASCII characters unescaped, so its encoded size matches its content.
- The replenisher wakes when an on-demand spawn ends, catches every error (an escape would
  cancel the supervisors at drain), and a spawn in flight at drain is killed.
- Warm failures on the claim path are counted; a child that dies before READY has its stderr
  logged; kills tolerate a child that is already gone, and reaps are bounded (5 s).
- The launcher reads the io budget through a callable, at the real hand-off (WRM-18).
- The supervisor takes exactly one of `launcher` (production) and `spawn` (its tests).
- The run no longer inherits `URL4_CLOUD_CONTROL_FD` after the control pipe is closed.

Open (recorded, not fixed): the supervisor keeps `_child_env` for four tests that pin the cold
environment; an early unexpected control line is not rejected at ERROR as erd.md §4 says (it is
read as the hand-off answer and fails the launch); `handoff_latency_s` starts at the launch call,
a few microseconds after the claim gates.

### Measurement (report only, ans:Q3)

Ad-hoc on the development Mac, 10 samples, warm disk cache, world build excluded (W1):

| Step | Median | Max |
|---|---|---|
| Cold boot: spawn → READY (Python start-up, imports, broker connect) | 224 ms | 232 ms |
| Warm hand-off: spec write → ACK | 0.13 ms | 0.27 ms |

This is not the B2/B3 benchmark of the test plan (that needs the kind environment).

### Validation done

- Unit: protocol (WRM-2, WRM-15), warm phase with sentinel env (WRM-4), pool state table
  (WRM-5, 6, 7, 10, 11, 12, 13, 16, 19), supervisor over a launcher (WRM-14, 17, 18), metrics
  (WRM-20), chart (WRM-21).
- Integration: the real `run --warm` process (WRM-1, WC-D3, WC-D9, stdin EOF), and the worker
  spine with a warm child on Linux. The child OOM cap with the warm handshake (WRM-8) on Linux.

### Not done in phase 3

- Kind cases K7, K8, K9 and the B3 benchmark (need the kind environment).
- The idle warm child's RSS (needed to size `warmChildren × RSS` against the pod memory).

## Phase 4 — mount call as a direct run

### Built

- url4 (public, `url4.peer`): `dispatch_direct(node, target, observer=…)`, `describe_routes`,
  `http_status(code, permanent=)`, and the error code `direct_eval_refused`. An observed direct
  call emits RunStarted, one NodeStarted/NodeFinished pair with the handler's Usage and
  ModelResponse on that span, and RunFinished — what a one-node DAG run emits.
- Run message: `URL4_CLOUD_RUN_SHAPE` (`direct` only when direct; absent = expression) and
  `URL4_CLOUD_SPEC_VERSION` "2" on every message. A worker refuses an unknown major version with
  `failed / unsupported_spec_version`.
- Run child: `Url4Executor(run_shape="direct")` calls `dispatch_direct` on the world node; the
  existing `_RunState` maps its events to the same span and cost frames; the route's media type
  reaches the result frame.
- App: `world.serving.derive_mount_table` (plain descriptors through `describe_routes`) and
  `rest/mounts.py`: one FastAPI `GET` route per mount, tag `Mounts`, in `/openapi.json`. The
  handler validates (403 / 400 / 414), queues a direct run, holds the topic (PRD 02), waits
  `min(Prefer wait, 30 s)`, and answers from the terminal frame with url4's error envelope and
  the node's status (`world.serving.mount_http_status`). Bound passed or caller gone → the run is
  stopped first (504). Counters `mount_calls_total{path,status}` and `mount_unsigned_spill_total`.
- `create_app_from_env` installs the mounts; the node-tier forwarder is no longer installed.

### Deviations

| # | PRD text | Built | Reason |
|---|---|---|---|
| M1 | ans:Q10: one 1 MiB inline limit for every shape | The mount RESPONSE limit is 1 MiB (200 inline up to it, 303 over it). The result FRAME cap stays 512 KiB; a result between the two is spilled by the child and served inline by the App from the artifact store. | OME-949: a frame near 1 MiB exceeds the broker's default 1 MiB `max_payload` once the CloudEvent envelope is added, and the publish fails after every model call is paid for. |
| M2 | MNT-1: "refuses the eval path" | `dispatch_direct` calls ONLY a registered handler, and an unregistered target in the eval path gets `direct_eval_refused`. A registered mount under `/v1` (`/v1/chat/completions`) is served. | The engine's real mounts (and the PRD's own examples) live under the eval path `/v1`. A prefix refusal would refuse every one of them. |
| M3 | (gap) | A direct run's reclaim grace is 2 s (`DIRECT_STREAM_GRACE_S`), not 60 s. | The child holds a worker slot through the grace; nobody attaches to a mount run. Found by the end-to-end spine (62 s → seconds). |
| M4 | MC-D6: "same status and problem `code`" | Same status, and url4's error envelope `{"error": {"code", "message"}}` — the node tier's body, not RFC 9457 problem+json. | That is what the node tier answered; changing the body would break mount callers. |
| M5 | (open question §6) | The mount set is the node-tier forwarder's set (the world built without benchmarks). | Parity first; exposing benchmark endpoints is the owners' decision. |

### Validation done

- url4 unit: MNT-1..MNT-4 and the observed direct call (1357 url4 tests green).
- Engine unit: MNT-6, 7, 8 (unit half), 9 (MNT-C2 table, parametrized), 10–14, 16–23.
- End-to-end on Linux (`tests/integration/test_mount_direct_run_spine.py`): App → queue →
  worker → warm `run --warm` child → world data route → 200 `text/plain`; the eval path 404.

### Not done in phase 4

- MNT-24 / MC-D13: local mode still serves mounts through `_LocalNodeMount`.
- MNT-15 redeem half (303 → artifact fetch 200 on a real store) and MNT-8 on a model endpoint
  with a real gateway: need the kind environment (K3, K4, K5).
