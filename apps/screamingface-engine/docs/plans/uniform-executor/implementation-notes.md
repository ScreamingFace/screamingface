# Implementation notes: uniform executor

This file records where the build deviates from the PRDs, and why. It also records the
residual risks that the build accepts. Read it with the PRD of each phase.

Status: phases 1–4 built on branch `exp/uniform-executor`. Exploratory work: the SDLC
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
| W1 | "the world is built" in the warm phase | RESOLVED after the kind measurements: the warm phase now BUILDS the world (`build_world` from per-process config) and hands it to the run as a `SharedWorld`; a run whose `EXTRA_MODELS` it does not route builds its own (`shared_world_serves`). First built without it: | `build_executor` and the world depend on per-run keys: `TOPIC` (the io wrapper), `EXTRA_MODELS` (the routes), and the request scope (identity, profile, seed). Building them before the spec breaks WRM-4. A world that is split into a per-process part and a per-run part is a refactor of `world/factory.py`, and it is not in this phase. |
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
| M3 | (gap) | A direct run's reclaim grace is 5 s (`DIRECT_STREAM_GRACE_S`), not 60 s. A succeeded run whose Result frame the App could not read answers 502 `result_unavailable`, never an empty 200. | The child holds a worker slot through the grace; nobody attaches to a mount run. Found by the end-to-end spine (62 s → seconds). |
| M4 | MC-D6: "same status and problem `code`" | Same status, and url4's error envelope `{"error": {"code", "message"}}` — the node tier's body, not RFC 9457 problem+json. | That is what the node tier answered; changing the body would break mount callers. |
| M6 | MC-H2 step 3: the handler "holds the topic (PRD 02 mechanism)" | A mount call takes NO audience hold. On every exit without a terminal frame (bound, disconnect, a failed or cancelled wait) the handler stops the run itself, before it answers. | Nobody can attach to a mount run. A hold only armed the orphan reaper on release: one broker round trip per call, for a run already over (review C11). |
| M5 | (open question §6) | The mount set is the node-tier forwarder's set (the world built without benchmarks). | Parity first; exposing benchmark endpoints is the owners' decision. |

### Design review fixes (before the final phase 4 commit)

- A spilled result is read through `ArtifactReader.content()` for every surface
  (`rest.artifacts.artifact_response`). `path_for` exists only on the filesystem store, so on S3
  (the store every queue deployment uses) a mount result between 512 KiB and 1 MiB — and a sync
  `GET /?q=` result over 512 KiB, a defect that predates this work — answered 500.
- Status parity: a permanent failure with a non-url4 code (`aigateway_http_401`,
  `provider_refused`) answers 502, as the node tier's `_remap` did.
- A non-GET request to a mount gets the node's `405 method_not_allowed` envelope (AC14).
- Every mount answer is url4's envelope and is counted; the 414 check measures raw bytes; a
  mount path with `?`, `{` or `}` fails startup; `wait_terminal_or_gone` is shared with the sync
  `GET /?q=`; topics come from `auth.token.new_topic`.
- A worker checks a message's terminal frame BEFORE its version, so an older worker never adds a
  second terminal frame to a run a newer one finished.
- url4: an observed direct call keeps the handler's log records; the code-to-status fallback
  and the data-route lookup each have one owner.
- MNT-5 is an AST test: the engine imports no private `url4.peer` module.

### Validation done

- url4 unit: MNT-1..MNT-4 and the observed direct call (1357 url4 tests green).
- Engine unit: MNT-6, 7, 8 (unit half), 9 (MNT-C2 table, parametrized), 10–14, 16–23.
- End-to-end on Linux (`tests/integration/test_mount_direct_run_spine.py`): App → queue →
  worker → warm `run --warm` child → world data route → 200 `text/plain`; the eval path 404.

### Not done in phase 4

- MC-D13 in part: local mode serves its MOUNTS through the same route code (direct runs on the
  in-process runner, in `/openapi.json`; `tests/integration/test_local_mount_direct_run.py`),
  anonymously as before (`require_identity=False`, loopback only). The EVAL PATH stays on
  `_LocalNodeMount`: serving it as a `shape=expression` sync run needs the url4 expression
  decoder, which the control plane may not import (the owners' open question, PRD 04 §6).
- MNT-15 redeem half (303 → artifact fetch 200 on a real store) and MNT-8 on a model endpoint
  with a real gateway: need the kind environment (K3, K4, K5).

## Findings from the kind environment (phase 0, run after phases 1–4)

The kind suite and the latency harness found five defects that no unit or integration test had
shown. Each is fixed, with a regression test.

| # | Finding | Evidence | Fix |
|---|---|---|---|
| F1 | Every finished run held its worker SLOT for 60 s: the child slept its reclaim grace before it exited. Under load every slot sat in grace and claims stopped (looked like a wedge). Predates this work (OME-1089); the uniform path makes it fatal. | K6: `slots_busy` 2/2 for 60 s, no claims, stub answers in 200 ms. | The worker owns the reclaim (`RECLAIM_OWNER=worker`): the child exits at its terminal frame; the supervisor purges after the run's grace in a detached task. |
| F2 | `ensure_events_stream` called `add_stream` on an EXISTING stream, which reserves its bytes twice: a restart failed with 10047 once `max_bytes` passed half the store (8 GiB default vs the bundled 10 GiB). | App start failure in kind. | `stream_info` first; `add_stream` only for a missing stream. |
| F3 | The bundled Garage pods carried the App's selector labels, so the App Service also selected them. | A port-forward to the App landed on Garage. | Garage has its own selector labels (`<name>-garage`). |
| F4 | The App got the artifact-signing key only with `node.enabled`, so with the tier off no mount result over 1 MiB got its 303 (PRD 05 DC-D3). | K4: 200 with the 1.5 MiB body. | The key follows the configuration (`signingKey` / `existingSecret`); the chart no longer mints a random key. |
| F5 | The warm pool refilled one child at a time (1.4 s boot in kind), slower than back-to-back calls used it, and the world was built per run (~600 ms). | B4 frame times: request→Started 1.4–1.6 s without a warm child; Started→first span ~800 ms with a 200 ms stub. | Parallel refill; the world is built in the warm phase (W1 resolved). |

Also found: `up.sh` did not restart pods onto reloaded images (same `:kind` tag) — fixed.

### F6 — fixed: the queue claim dominated a simple call's latency

After F5, a mount call's own work is ~210 ms (Started → first span, with the 200 ms stub). The
rest of its ~1.5–3 s was between the App's publish and the child's `Started`: the worker's claim.
With the queue idle, `RunQueue.pull` rotated over all 16 caller buckets and spent the 5 s pull
timeout as a slow pass across them (OME-1091 fairness), so a message that landed mid-pull waited
until the rotation reached its bucket — roughly uniform in [0, 5 s].

Fixed 2026-09-27 (the owner lifted the test-plan §7 stop rule for it): the App's queue publish
also sends a core-NATS wake-up on `<prefix>-wake` (`url4-runq-wake`) — a subject OUTSIDE the
queue stream's `<prefix>.>` filter, so it is never stored — with the bucket subject as payload;
`release_held` sends one with an empty payload ("all") after it gives runs back. An idle worker's
pull subscribes to it before its fast pass, and after the fast pass waits on it instead of the
slow rotation; a wake runs one pass over only the woken bucket(s), and a productive pass on the
wake path runs one top-up over the buckets that came back full, then returns. A pull whose wake
subscription cannot be made behaves exactly as before. Measured on a real broker: publish → claim
~5 ms (was 0–5 s); a mount call's B4 p50 in the deployments' shape went from 1519 ms to 350 ms
(`measurements/2026-09-27-B4-prod-shape.md`). What remains is the hand-off when no idle warm child
is left (a ~2 s boot). RPC cost: every idle pod receives every wake, so one publish costs about one
fetch per idle pod plus one fast rotation on the winner (`RunQueue.pull` docstring); at a high
publish rate over many idle pods that can exceed the old poll's RPCs, which is the trade for
millisecond claims. Not covered end to end: `release_held`'s wake reaching another pod (the race
it targets cannot be forced deterministically against a real broker); its NAK, flush and wake are
unit-tested on a fake.

### F7–F11 — found by the chaos cases (K7, K8, MNT-26) and the PRD 05 design review

| # | Finding | Evidence | Fix |
|---|---|---|---|
| F7 | An idle warm child holds its BUILT world: about 430 MiB with the builtin benchmarks (60 MiB without). The chart request `perRunCharge.memoryMi` (256) is below it; the limit (1024) covers it. | `/proc/<pid>/status` in a runner pod: worker 53 MiB, `run --warm` 434 MiB; world build measured with and without benchmarks. | `runnerPool.warmChildCharge.memoryMi` (450) is now added to the pod's memory request once per warm child (2026-09-27 follow-up, below). |
| F8 | The pool kept `warmChildren` idle children ON TOP of the running runs, so a pod with every slot busy held `slots + warmChildren` children. One run near its memory budget then OOM-killed the whole pod, and the redelivered run OOM-killed the next pod. | K8: both runner pods `OOMKilled` (2304 Mi limit) 8–10 s into the case. | Idle + running ≤ `workerSlots`: the pool refills only into free slots (`WarmChildPool(slots=, busy=)`; the worker wakes it when a run ends). |
| F9 | At pod boot, claims that found no idle child spawned their OWN child beside the warm children already booting: `size + claims` children built their worlds at once. | K8 right after a rollout: both new pods `OOMKilled` 5 s after start; 4 messages ack-pending until `ack_wait`, every call 504. | A claim waits for a warm spawn in flight that no other claim waits for (`WarmChildPool._take`); it spawns its own only when there is none (or it failed). |
| F10 | A draining worker left deliveries its held pull subscriptions had buffered after their last pull: never run, never returned, redelivered only after `ack_wait` (60 s) — past the 30 s sync bound. | Consumer info during a rollout: ack-pending messages with no reader. | `RunQueue.release_held()` at drain start: wait out the last fetch window, NAK the buffered deliveries, unsubscribe. |
| F11 | A mount call became a DIRECT run with `origin="run"`: the caller's valid `X-Answer-Seed` no longer reached aigateway (the connector applies it on `origin == "sync"` or in a candidate invocation), and no request deadline bounded its aigateway retries (the node tier set both). | Design review of PRD 05; `test_a_direct_mount_call_sends_the_callers_seed_to_aigateway` fails without the fix. | `request_scope_from_env`: a direct run is `origin="sync"` with `deadline = start + JOB_DEADLINE_S`. |

The kind cases themselves also needed fixes: `('STUB_SLEEP_MS=…')!'go'` names no model on `GET /?q=`,
so the stub never slept (K7, K10 now put the model route first); K10's NATS port-forward waited only
30 s for the restarted pod (now 120 s); a pod listed a moment ago can be gone (`_slots_busy`); and
K8 and MNT-26 use their own callers, so a redelivered run of an earlier case does not count against
their per-caller in-flight cap. K6 now sends its 50 runs as 50 callers (one caller's 50 runs are
mostly refused with 503 by the per-caller cap, by design), `read_until_terminal` has an overall
deadline (heartbeats kept a receive alive, so a refused WebSocket run hung the suite for hours),
and the App/NATS port-forwards are per test (K12's `helm upgrade` replaces the App pod, which killed
a session-wide forward).

B2 and B3 measured `('hi')!'go'` on `GET /?q=`, which names no model: they time the engine path
with NO aigateway call. B4 (a model mount) includes the stub's 200 ms. Compare B2/B3 with B4 with
that in mind.

Two limits of F9 (design review, low severity), fixed 2026-09-27, after a second review found a
busy loop in the first attempt: the claim/spawn hand-off is now one future per waiting claim,
resolved by the spawn that finishes (its child, or `None` when it failed) — waiting claims never
wake each other. At drain, the pool does not cancel the spawns that claims wait for and does not
wait for them either: each finishes on its own and hands its child to its claim, or kills it when
no claim waits, so the drain never holds up the worker's grace. A claim waits for a warm spawn in
flight at most `WARM_SPAWN_WAIT_S` (10 s) counted from that spawn's START, then spawns its own
child with the full READY timeout. Tests: `test_waiting_claims_do_not_wake_each_other_when_a_spawn_fails`,
`test_a_drain_does_not_wait_for_a_claim_it_hands_a_warm_spawn_to`,
`test_a_child_handed_to_a_cancelled_claim_is_killed`,
`test_a_claim_behind_a_hung_warm_spawn_spawns_its_own_after_the_wait_bound`.

F7 follow-up (2026-09-27): the runner pod's memory request now adds
each warm child's excess over its free slot's charge, `runnerPool.warmChildCharge.memoryMi` (450)
− `perRunCharge.memoryMi` (256) = 194 Mi; the limit is unchanged. Dev, staging and prod: 1540 Mi
per runner pod (was 1152 Mi).
