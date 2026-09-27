# PRD: Mount call as a direct run (with OpenAPI projection)

**Source:** prompt, ans:Q1, ans:Q5, ans:Q9, ans:Q10, ans:Q12 · **Priority:** P1 (the change that makes the path uniform)
**Lifecycle:** existing (characterize + delta)
**Owner:** unassigned

## 1. Summary and user story

As an API caller that knows the engine's declared endpoints, I want to call
`GET /<mount>?q=(context)!intent` and see every mount in `/openapi.json`, so that a simple
request uses the same queue, worker and child as an ensemble run, with the same limits,
events and cost records.

## 2. Background and constraints

- "the app must actually somehow project the real available endpoints so it appears in the
  openapi.json. (even though all of them would be routed to the same workflow" `[stated ans:Q5]`
- "our workflow becomes uniform, no matter if the request is an ensemble or a simple
  request" `[stated prompt]`
- When the 30 s bound runs out: 504, and the App stops the run at once. `[stated ans:Q9]`
- One inline limit, 1 MiB. Over it: 303 to a signed artifact URL. `[stated ans:Q10]`
- A new public url4 API does the direct dispatch. It serves endpoints and data routes only
  and refuses the eval path. `[stated ans:Q12]`
- Identity only, no token, for mounts (D4). `[existing docs/plans/00-overview.md §3 D4]`
- D1 guarantee: a mount call runs one handler. No grammar, no DAG, no URL-valued context.
  `[existing docs/plans/00-overview.md §3 D1; packages/url4/src/url4/peer/_dispatch.py:178-182]`
- Components used: shared events stream (PRD 01), sync hold (PRD 02), warm child pool
  (PRD 03). Entities: RUN_MESSAGE `shape=direct`, MOUNT_DESCRIPTOR, ARTIFACT_TICKET.

### 2.1 Current behavior

- With `node_base_url` set, the App derives the mount set at startup from the world module
  (`derive_forward_contract` → `node_mount_paths` = endpoints + data routes) and installs
  `NodeMountRoute`, which matches those paths only. `[existing rest/forwarder.py:155-192, 349-369; world/serving.py:93-107, 288]`
- `NodeMountRoute` is a Starlette `BaseRoute`, so no per-mount operation with parameters
  and responses appears in `/openapi.json`. `[existing world/serving.py:288; schemas/openapi.py:123]`
- `forwarded_headers` drops every inbound header except an allowlist and sets `X-User-Email`
  from the verified value. `[existing rest/forwarder.py:132-151]`
- The forwarder maps: missing identity → 403, node unreachable → 503 (`Retry-After: 1`),
  timeout → 504. One retry only when the request never reached the node.
  `[existing rest/forwarder.py:195-330]`
- The node tier: in-flight cap 2 per worker, 30 s request timeout, 28 s gateway timeout,
  spill over 512 KiB to S3 with a 303 to `/artifacts/{id}?exp&sig`. It emits no NATS event
  and no cost record. `[existing world/node_tier/tier.py:241-346; world/node_tier/settings.py:81]`
- url4 dispatch of a mount: `dispatch_expression` → `call_endpoint` for an endpoint path;
  data routes return their provider. The eval path (`/v1`) runs `node._run_text` (full DAG).
  These functions are package-private. `[existing packages/url4/src/url4/peer/_dispatch.py:123-176]`
- The forwarder never forwards the eval path in production. `[existing rest/forwarder.py — no eval_path reference]`
- Local mode (`serve --local`) mounts the node ASGI app in process through
  `_LocalNodeMount`. Its mount set is `direct_mount_paths(world) | {eval_path}`, so local
  mode exposes the eval path and hides benchmark, candidate, corrective and judge endpoints.
  `[existing local.py:230-358; world/factory.py:110-126]`
- The node-tier tests hold the behavior that must survive: `test_node_tier.py`,
  `test_node_tier_review_round.py`, `test_node_tier_dispatch_fixes.py`,
  `test_node_tier_build_fixes.py`, `test_node_tier_spill.py`, `test_node_mount_route.py`,
  `test_node_healthz_config_digest.py`, and the local-mode tests. `[existing tests/unit/]`

**Delta.**

1. url4 gets a public API: `url4.peer.dispatch_direct(node, target) -> DirectResult` and
   `url4.peer.describe_routes(node) -> list[RouteInfo]`.
2. The App registers one FastAPI `GET` route per MOUNT_DESCRIPTOR, with
   `include_in_schema=True`, tag `Mounts`, a `q` query parameter, and documented responses.
3. The route handler puts a `shape=direct` RUN_MESSAGE on the queue, holds the topic (PRD 02
   mechanism), and waits for the result.
4. The run child evaluates `shape=direct` with `dispatch_direct`, inside the same request
   scope and trace scope as any run.
5. The App maps the result to 200, 303, 4xx, 502 or 504 (ans:Q9 → 504 and stop).
6. Local mode serves mounts through the same routes, backed by `InProcessJobRunner`.
7. The `NodeForwarder` is no longer installed. PRD 05 deletes it.

## 3. Scenarios and acceptance criteria

### 3.1 Happy path

- **MC-H1 OpenAPI lists mounts.** Given `url4.toml` declares endpoints `/v1/chat/completions`
  and a data route `/v1/benchmarks/data/foo`, when a client reads `/openapi.json` after
  startup, then it contains a `GET` operation for each path, with tag `Mounts`, a `q` query
  parameter, and responses 200, 303, 400, 403, 404, 502, 503 and 504. `[stated ans:Q5]`
- **MC-H2 one workflow.** Given the same config, when a client calls
  `GET /v1/chat/completions?q=('hi')!'answer'` with a verified `X-User-Email`, then the App
  publishes one RUN_MESSAGE with `shape=direct` to `url4-runq`, a worker child runs it, and
  the App returns 200 with the handler's body and media type. `[stated ans:Q5]`
- **MC-H3 events and cost.** Given the call in MC-H2, then subject `url4-cloud.<topic>` holds
  `Started`, `Result` and `Terminated(succeeded)` `[implied — uniform path]`, and at least
  one `span` and one `cost.usage` frame for the model call `[proposed]`. Today these two
  frame kinds come from the url4 DAG observer (`runner/executor.py` `_Bridge`), which a
  direct dispatch does not run. So the GREEN step for MNT-8 must attach the same observer
  to the direct call. If url4 cannot report the call without a DAG, the implementer stops
  and records the gap before going on.
- **MC-H4 spill.** Given the handler returns 1.5 MiB, and a signing key is set, then the App
  returns 303 with `Location: /artifacts/<sha256>?exp=<t+600>&sig=<hex>`, and `GET` on that
  URL returns the full body. `[stated ans:Q10]`
- **MC-H5 below the limit.** Given the handler returns 700 KiB, then the App returns 200 with
  the body inline (the node tier returned 303 at this size). `[stated ans:Q10]`

### 3.2 Error paths (from the answers)

- **MC-E1 bound runs out.** Given the run takes longer than `min(Prefer wait, 30 s)`, then the
  App returns 504 with a problem body and calls `job_runner.stop(topic)` before it answers.
  The subject ends with `Terminated(stopped)`. `[stated ans:Q9]`
- **MC-E2 eval path refused.** Given a client calls `GET /v1?q=<expression>` in production,
  then the App returns 404 (no route), and nothing reaches the queue. `[stated ans:Q12]` +
  `[existing D1]`
- **MC-E3 url4 refuses the eval path.** Given `dispatch_direct(node, "/v1?q=...")`, then it
  raises `ResolutionError` with code `direct_eval_refused` and `permanent=True`.
  `[stated ans:Q12]`

### 3.3 Derived scenarios (risk order)

| ID | Title | Tag | I×L |
|---|---|---|---|
| MC-D1 | Tampered queue message with the eval path | [implied — D1 defense in depth] | H×L |
| MC-D2 | Missing identity | [existing rest/forwarder.py 403] | H×M |
| MC-D3 | Client-supplied identity header is not trusted | [existing rest/forwarder.py:132-151] | H×M |
| MC-D4 | Client disconnects during the wait | [implied — ans:Q9 reasoning] | M×M |
| MC-D5 | Admission refuses | [existing adapters/queue_runner.py:85-90] | M×M |
| MC-D6 | Handler error status mapping keeps node-tier parity | [existing test_node_tier_dispatch_fixes.py] | H×M |
| MC-D7 | Mount collides with an engine route | [existing world/serving.py:127 F4] | M×L |
| MC-D8 | OpenAPI is generated before mounts are registered | [proposed — gap §per-flow/ordering] | M×M |
| MC-D9 | No signing key and a result over 1 MiB | [proposed — gap §per-connection/sync] | M×L |
| MC-D10 | Answer-seed header is invalid | [existing local.py:230 AnswerSeedError → 400] | M×L |
| MC-D11 | Direct target larger than 8 KiB | [proposed — gap §per-flow/boundary] | L×M |
| MC-D12 | Worker dies mid-run (redelivery) | [existing runner_queue.py max_deliver=2] | M×L |
| MC-D13 | Local mode serves mounts through the same routes | [proposed] | M×M |
| MC-D14 | Data route without `q` | [existing packages/url4/src/url4/peer/_dispatch.py:123-146] | M×M |

- **MC-D1.** Given a RUN_MESSAGE with `shape=direct` and `EXPRESSION="/v1?q=..."` reaches a
  child, then the child publishes `Terminated(failed)` with code `direct_eval_refused`, and no
  model call happens.
- **MC-D2.** Given no `X-User-Email`, then the App returns 403, and nothing reaches the queue.
- **MC-D3.** Given the edge sets `X-User-Email: a@x` and the request also carries a second
  `X-User-Email: b@x`, then the RUN_MESSAGE carries `a@x` only. The route reads identity from
  the same verified source as `GET /?q=`. No other inbound header (Cookie, Authorization,
  URL4-Capability) reaches the RUN_MESSAGE.
- **MC-D4.** Given a mount call is waiting, when the client disconnects, then within 1 s the
  App stops the run. No one can attach to a mount run, so the reaper grace does not apply.
- **MC-D5.** Given the caller is at its in-flight cap, then the App returns 503 with
  `Retry-After` (30–300 s), as for `GET /?q=`.
- **MC-D6.** Given the node-tier tests pin a status for a handler failure (for example a bad
  `q` encoding → 400, an unknown endpoint inside the node → 404, an upstream failure → 502,
  gateway deadline → 504), then the direct path returns the same status and problem `code`.
  The implementer first lists every pinned status in a characterization table (MNT-C2).
- **MC-D7.** Given a declared mount path equals an engine route (for example `/token`), then
  App startup fails, as today.
- **MC-D8.** Given a client reads `/openapi.json` during startup before the mount set is
  derived, then the App answers 503, or it serves a schema that already holds the mounts. It
  never caches a schema without mounts. The route registration resets `app.openapi_schema`.
- **MC-D9.** Given `URL4_CLOUD_ARTIFACT_SIGNING_KEY` is empty and the result is over 1 MiB,
  then the App streams the artifact in a 200 response (the `GET /?q=` behavior), and it
  increments `screamingface_engine_mount_unsigned_spill_total`.
- **MC-D10.** Given `X-Answer-Seed: not-a-seed`, then the App returns 400, and nothing
  reaches the queue.
- **MC-D11.** Given the path plus raw query is longer than 8 KiB, then the App returns 414,
  and nothing reaches the queue.
- **MC-D12.** Given the worker pod dies after ACK, when JetStream redelivers after 60 s, then
  the second worker sees no terminal frame and runs the call again. The App still answers
  within its bound, or it returns 504 and stops the run (MC-E1). A duplicate model call is
  possible in this case. The events stream shows both attempts.
- **MC-D13.** Given `serve --local`, when a client calls a declared mount, then the call goes
  through the same route code, `InProcessJobRunner` and `InMemoryEventStream`, and
  `/openapi.json` lists the local mounts. `_LocalNodeMount` is gone.
- **MC-D14.** Given a data route `/v1/benchmarks/data/foo`, when a client calls it with no
  `q`, then the App returns the data with its media type (today's url4 dispatch behavior).

## 4. Non-functional requirements

- **Latency (report only).** Phase 0 measures the node-tier mount call. This PRD measures the
  direct-run mount call with the same stub gateway latency. Both numbers go into the
  measurement report. `[stated ans:Q3]`
- **Capacity.** Mount calls share worker slots and the per-caller cap with all runs.
  `[stated ans:Q8]`
- **Observability.** Mount calls now produce run frames, spans and cost records. New counter
  `screamingface_engine_mount_calls_total` (labels `path`, `status`), and
  `screamingface_engine_mount_unsigned_spill_total`. `[proposed]`
- **Security.** Trust boundaries: client → App (identity only from the verified header), App
  → queue (the App validates the target), queue → child (the child validates again through
  `dispatch_direct`). The `q` value is untrusted input for the handler, as today. `[implied]`

## 5. Out of scope

- A token or WebSocket for mount calls. `[existing D4]` + `[stated ans:Q9]`
- Methods other than `GET` for mounts. `[existing docs/plans/00-overview.md D1 "GET /<mount>?q="]`
- The eval path as a production mount. `[existing D1]`

## 6. Open questions

These emerged after the decision round, while the implementation detail was read.

1. **Local and production mount sets differ today.** Local mode exposes the eval path and
   hides benchmark, candidate, corrective and judge endpoints. Production exposes all served
   routes and hides the eval path. `[existing local.py:355; world/serving.py:93]`
   **Recommended default:** keep each set as it is (characterize both in MNT-C4). In local
   mode, serve the eval path as a `shape=expression` sync run through the same route code, so
   local mode stays uniform. Ask the owners if production should also hide the benchmark
   endpoints for the answer-seed reason noted in `world/factory.py:110-126`.
   **Resolved 2026-09-27 (owner):** "production" meant the node tier, which is off in dev,
   staging and prod, so those environments served NO mount before this change. They now
   serve every model and data mount (117 routes with the current `url4.toml`), each a paid
   model call gated by `X-User-Email` only, like `GET /?q=`. The owner accepted this surface
   with no chart switch. The benchmark, candidate, corrective and judge endpoints stay
   hidden: the App derives its table without them, and the child refuses any served route
   that is not a recorded mount.

## 7. TDD plan

Order: core-out. First the url4 API (the D1 guard lives there), then the child, then the App
route, then OpenAPI and local mode.

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| MNT-C1 | CHAR `forwarder_identity_strip_and_403` | unit | [existing rest/forwarder.py:132] | H×M | passes today |
| MNT-C2 | CHAR `node_tier_status_table` (one row per pinned status in the 7 node-tier test files) | unit | [existing tests/unit/test_node_tier*.py] | H×M | passes today; this table is the parity oracle for MNT-9 |
| MNT-C3 | CHAR `mount_collision_fails_startup` | unit | [existing world/serving.py:127] | M×L | passes today |
| MNT-C4 | CHAR `local_and_prod_mount_sets` | unit | [existing local.py:355; world/serving.py:93] | M×M | passes today |
| MNT-1 | url4: `dispatch_direct_refuses_eval_path` | unit (url4) | [stated ans:Q12 — MC-E3] | H×H | new public function; new `ErrorCode.DIRECT_EVAL_REFUSED` |
| MNT-2 | url4: `dispatch_direct_calls_one_endpoint_handler` | unit (url4) | [stated ans:Q12] | H×M | wraps `call_endpoint`; no `_run_text` |
| MNT-3 | url4: `dispatch_direct_serves_data_route_with_media_type` | unit (url4) | [existing _dispatch.py:123 — MC-D14] | M×M | returns `DirectResult(body, media_type)` |
| MNT-4 | url4: `describe_routes_lists_endpoints_and_data_routes` | unit (url4) | [stated ans:Q5] | M×M | public `RouteInfo(path, kind, media_type)` |
| MNT-5 | `engine_imports_no_private_url4_dispatch` | unit (layering) | [stated ans:Q12] | M×M | grep/AST check for `url4.peer._dispatch` in engine |
| MNT-6 | child: `direct_shape_runs_dispatch_direct_not_dag` | unit | [stated ans:Q5 — MC-H2] | H×H | branch in executor on `RUN_SHAPE` |
| MNT-7 | child: `tampered_eval_target_fails_direct_eval_refused` | unit | [implied — MC-D1] | H×L | error from MNT-1 mapped to terminal code |
| MNT-8 | child: `direct_run_publishes_started_cost_result_terminated` | integration | [implied — MC-H3] | M×M | same lifecycle as expression runs |
| MNT-9 | App: `mount_status_mapping_matches_node_tier_table` | unit | [existing — MC-D6] | H×M | map terminal error codes with the MNT-C2 table |
| MNT-10 | App: `mount_call_publishes_direct_run_and_returns_200` | unit | [stated ans:Q5 — MC-H2] | H×H | route handler → `_schedule(shape=direct)` → sync hold → wait |
| MNT-11 | App: `bound_elapsed_returns_504_and_stops_run` | unit | [stated ans:Q9 — MC-E1] | H×M | call `job_runner.stop` before responding |
| MNT-12 | App: `missing_identity_403_nothing_queued` | unit | [existing — MC-D2] | H×M | reuse the verified identity dependency |
| MNT-13 | App: `only_verified_identity_reaches_message` | unit | [existing — MC-D3] | H×M | build the message from verified fields only |
| MNT-14 | App: `disconnect_stops_mount_run_within_1s` | unit | [implied — MC-D4] | M×M | PRD 02 disconnect poll + stop |
| MNT-15 | App: `result_over_1mib_returns_signed_303` | integration | [stated ans:Q10 — MC-H4] | M×M | reuse `artifacts/signing.py`; TTL 600 s |
| MNT-16 | App: `result_700kib_returns_inline_200` | unit | [stated ans:Q10 — MC-H5] | M×M | one limit via `decide_result_delivery` |
| MNT-17 | App: `no_signing_key_streams_artifact_200` | unit | [proposed — MC-D9] | M×L | fallback + counter |
| MNT-18 | App: `openapi_lists_every_mount_with_params_and_responses` | unit | [stated ans:Q5 — MC-H1] | H×M | `APIRoute` per descriptor; tag `Mounts` |
| MNT-19 | App: `openapi_never_cached_without_mounts` | unit | [proposed — MC-D8] | M×M | reset `app.openapi_schema` after registration |
| MNT-20 | App: `eval_path_is_404_in_production` | unit | [existing D1 — MC-E2] | H×M | no route for the eval path |
| MNT-21 | App: `invalid_answer_seed_400` | unit | [existing — MC-D10] | M×L | reuse `bind_sync_request` validation |
| MNT-22 | App: `target_over_8kib_414` | unit | [proposed — MC-D11] | L×M | length check before publish |
| MNT-23 | App: `admission_503_for_mount_calls` | unit | [existing — MC-D5] | M×M | same `_schedule` path |
| MNT-24 | local: `local_mounts_use_inprocess_runner_and_openapi` | integration | [proposed — MC-D13] | M×M | delete `_LocalNodeMount` |
| MNT-25 | kind: `mount_call_spine_and_spill` | e2e (kind) | [stated ans:Q4] | H×M | see test-plan §5 |
| MNT-26 | kind: `worker_kill_mid_mount_call_redelivers_or_504` | e2e (kind) | [existing — MC-D12] | M×L | `kubectl delete pod` during the call |

**Refactor notes.** After MNT-10 is green, remove the `install_forwarder` call from
`create_app_from_env`. Keep `derive_forward_contract` (rename it `derive_mount_table`); PRD 05
deletes the forwarder code.
