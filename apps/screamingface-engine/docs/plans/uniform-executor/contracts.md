# Contracts: uniform executor

One section per connection. Each names its shape, its policies, the failure behavior on
both sides, and the tests that pin it (PRD + test ID). Tags as in `erd.md`.

## C1 — Sync run: Client → App, sync, HTTP `GET /?q=`

- **Shape.** Request: `q` (url4 expression), header `URL4-Capability: <jwt>` (required),
  optional `Prefer: wait=<s>` or `respond-async`, `traceparent`, `X-Answer-Seed`. Identity
  header `X-User-Email` comes from the edge. A nonblank `X-Profile` is refused with 400
  `x_profile_unsupported` before anything is scheduled; absent or blank, it is ignored
  (OME-1381).
  `[existing rest/routes.py:497]` Response: 200 result body (media type from `ResultData`),
  202 (`Location`, `Link`, `Preference-Applied`), 401, 409, 428 (async only after this
  change), 502, 503 (`Retry-After`), 504. `[existing rest/routes.py]` + delta `[stated ans:Q1]`
- **Policies.** Timeout: `min(wait, sync_max_wait_s=30)`. No server retry. Not idempotent: a
  second call with the same token returns 409. `[existing]`
- **Failure behavior.** Caller gone → App releases the hold within 1 s, and the reaper grace
  (120 s) applies. Bound passes → 202, and the client may attach a WebSocket within 120 s.
  `[implied]`
- **Contract tests.** PRD 02: SYN-C1..C3, SYN-1, SYN-3, SYN-4, SYN-10.

## C2 — Mount call: Client → App, sync, HTTP `GET /<mount>`

- **Shape.** Request: path from the MOUNT_DESCRIPTOR set; `q` (required for endpoints,
  optional for data routes); `X-User-Email` (edge-verified, required); optional
  `traceparent`, `X-Answer-Seed`, `Prefer: wait=<s>`. No token. A nonblank `X-Profile` is
  refused with url4's envelope 400 `x_profile_unsupported`, after the identity check and
  before anything queues; absent or blank, the direct run carries no profile (OME-1381).
  `[existing D4]` + `[stated ans:Q5]` Response: 200 (handler body, handler media type), 303
  (`Location: /artifacts/{id}?exp&sig`), 400, 403, 404 (unknown path), 414, 502, 503
  (`Retry-After`), 504. Every mount is a `GET` operation in `/openapi.json`, tag `Mounts`.
  `[stated ans:Q5]`
- **Policies.** Timeout: `min(wait, 30 s)`. On timeout: 504 and stop the run. `[stated ans:Q9]`
  No server retry. Inline limit 1 MiB. `[stated ans:Q10]`
- **Failure behavior.** Caller gone → the App stops the run within 1 s. `[implied — ans:Q9]`
  Status mapping for handler errors equals the node-tier table (MNT-C2). `[existing]`
- **Contract tests.** PRD 04: MNT-9..MNT-23, MNT-25.

## C3 — Publish run: App → NATS `url4-runq`, async, JetStream publish

- **Shape.** RUN_MESSAGE (`erd.md` §2): JSON env mapping, plus `URL4_CLOUD_RUN_SHAPE` and
  `URL4_CLOUD_SPEC_VERSION` (new). Headers `Nats-Msg-Id=<topic>`, `Url4-Enqueued-At`.
  Subject `url4-runq.<bucket>`. `[existing runner_queue.py:245-490]` + `[proposed]`
- **Policies.** Dedup window 120 s. Admission before publish: depth ≤ 10 000 and caller
  in-flight < cap, else 503. `[existing]`
- **Failure behavior.** Publish fails → the App returns 503 and releases the hold. An old
  worker must never read a `shape=direct` message: the drained rollout ensures this.
  `[stated ans:Q7]`
- **Contract tests.** PRD 04: MNT-10; PRD 03: WRM-2 (codec property).

## C4 — Claim run: Worker ← NATS `url4-runq`, async, pull consumer

- **Shape.** Unchanged. Durable consumer per bucket, explicit ack, `ack_wait=60 s`,
  `max_deliver=2`, round-robin across buckets. `[existing runner_queue.py:171-192, 503-636]`
- **Policies.** At-least-once. The worker dedupes with three gates before it spawns.
  `[existing worker/supervisor.py:296-470]` Heartbeat `in_progress` every 20 s. Ack only after
  the terminal frame. `[existing]`
- **Failure behavior.** Worker dies → redelivery after 60 s, once. `[existing]`
- **Contract tests.** Existing `test_worker_claim.py`, `test_queue_*` (characterization, no
  change); PRD 04: MNT-26.

## C5 — Run hand-off: Worker → warm child, sync, process spawn + pipes

- **Shape.** Spawn: `python -m screamingface_engine.worker.exec_wrapper <budget>` →
  `screamingface-engine run --warm`; fd 3 inherited as the control pipe. Child → worker on
  fd 3: `READY {"pid":<int>,"world":"ok"|"error"}\n`, then later `ACK\n`. Worker → child on
  stdin: one RUN_SPEC JSON line (≤ 1 MiB). stdout/stderr: logs, as today. `[proposed]`
- **Policies.** READY timeout 60 s. ACK timeout 10 s after the spec write. One RUN_SPEC per
  child. Retry before ACK: once, on a new child. No retry after ACK. `[proposed]`
- **Failure behavior.** Worker side: see the WARM_CHILD state table (`erd.md` §4). Child
  side: bad spec → exit 2 before ACK. Worker gone → the child's stdin closes → the child
  exits 0 if it has no spec yet. `[proposed]`
- **Contract tests.** PRD 03: WRM-1, WRM-5, WRM-7, WRM-12, WRM-15, WRM-16.

## C6 — Run frames: Child → NATS `url4-events`, async, JetStream publish

- **Shape.** EVENT_FRAME (CloudEvent JSON) on subject `url4-cloud.<topic>`. Headers
  `Nats-Msg-Id=<topic>:<seq>`, `Url4-Seq=<seq>`. `[proposed]`
- **Policies.** The producer sequence is gap-free (I-EV1). The child is the only writer while
  it runs (I-EV3). Publish retry uses the same `Nats-Msg-Id`. Stream limits: `erd.md` §5.
- **Failure behavior.** NATS down → the publisher reconnects. If a frame cannot be published,
  the run ends `failed/stream_failed`. A silent gap is not allowed. Store full → oldest frames
  are dropped, and the gauge rises. `[stated ans:Q11]`
- **Contract tests.** PRD 01: EVT-3, EVT-7, EVT-8, EVT-11, EVT-12, EVT-16.

## C7 — Non-child frames: App / Supervisor → NATS `url4-events`, async, conditional publish

- **Shape.** Same as C6, plus `Nats-Expected-Last-Subject-Sequence=<stream seq of the last
  frame on the subject, or 0>`. Sequence = last producer sequence + 1. `[proposed]`
- **Policies.** On "wrong last sequence": read again; if the new last frame is terminal, write
  nothing; else retry, max 3. `[proposed]`
- **Failure behavior.** After 3 conflicts: log ERROR, increment
  `events_publish_conflicts_total`, and ack the queue message anyway. The run already has a
  terminal frame from another writer, or it will get one from max_age expiry. `[proposed]`
- **Contract tests.** PRD 01: EVT-4, EVT-5, EVT-6.

## C8 — Read frames: App ← NATS `url4-events`, async, ordered ack-less consumer

- **Shape.** Consumer on stream `url4-events`, `filter_subject=url4-cloud.<topic>`,
  `DeliverPolicy.ALL`, `AckPolicy.NONE`. Decode with no sequence override. For resume, drop
  frames with `sequence < from_sequence`. `[proposed]`
- **Policies.** The WS bridge and the sync wait use this consumer. `[existing ws/bridge.py; rest/routes.py:293]`
- **Failure behavior.** Consumer error → `ai.url4.error{stream_failed}` to the WS client, as
  today. `[existing packages/screamingface/src/screamingface/_engine/contract.py:127]`
- **Contract tests.** PRD 01: EVT-C1, EVT-C2, EVT-1, EVT-2.

## C9 — Cancel: App → Worker via NATS `url4.runctl.<topic>`, async, request/reply

- **Shape and policies.** Unchanged. `[existing adapters/queue_runner.py:345-415; subjects.py:37]`
- **Delta.** The cancel handler knows the `assigned` state (spec written, no ACK). It kills
  the child and publishes one `Terminated(stopped, cancelled)`. `[proposed]`
- **Contract tests.** PRD 03: WRM-17; existing `test_queue_runner_cancel.py`.

## C10 — Model call: Child → aigateway, sync, HTTP `POST /v1/chat/completions`

- **Shape and policies.** Unchanged: headers `X-User-Email`, `traceparent`; no
  `Authorization` and no `X-Profile`. `[existing world/connector.py:1048-1080]`
- **Delta.** Direct runs now make this call from a child process instead of from a node pod.
  The aigateway NetworkPolicy already admits the runner pods (`url4-runner`).
  `[existing apps/aigateway/charts/aigateway/values-prod.yaml:66-72]`
- **Contract tests.** Existing connector tests; PRD 04: MNT-25 (kind, stub gateway).

## C11 — Direct dispatch: Engine child → url4, dependency, in-process API

- **Shape.** `url4.peer.dispatch_direct(node, target: str) -> DirectResult(body: str,
  media_type: str)`; `url4.peer.describe_routes(node) -> list[RouteInfo(path, kind,
  media_type)]`. Errors: `ResolutionError` with codes `direct_eval_refused` (new),
  `endpoint_not_found`, and the existing subrequest decode codes. `[stated ans:Q12]`
- **Layering rule.** The engine imports only the public `url4.peer` API. It never imports
  `url4.peer._dispatch`. Enforcement: MNT-5 (AST check in the test suite, or a rule in
  `check_layering.py`). `[stated ans:Q12]`
- **Version window.** url4 is an editable workspace package, so both change in one PR.
  `[existing Dockerfile editable packages/url4 install]`
- **Contract tests.** PRD 04: MNT-1..MNT-5.

## C12 — Artifact fetch: Client → App, sync, HTTP `GET /artifacts/{id}`

- **Shape and policies.** Unchanged: signed params (`exp`, `sig`) or a capability token;
  404 if swept. `[existing rest/artifacts.py:75-110; artifacts/signing.py]`
- **Delta.** The App signs the URL for mount spills. The node tier no longer signs.
  `[stated ans:Q10]`
- **Contract tests.** PRD 04: MNT-15, MNT-17; PRD 05: DEC-3.

## C13 — Removed: App → Node tier (HTTP forward)

This connection goes away in PRD 05. No contract. Tests DEC-4 and DEC-5 prove it is gone.

## C14 — Layering (dependency)

- `screamingface_engine/child_protocol.py` imports stdlib only. Both `worker/` and `runner/`
  may import it. `[proposed]`
- `runner/` still never imports FastAPI, uvicorn or the Kubernetes client. `[existing .claude/scripts/check_layering.py]`
- Enforcement: `check_layering.py` rules, run in the quality gate. Tests: WRM-1 (runtime
  import), DEC-4.
