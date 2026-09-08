# url4‑cloud request workflow (k8s scenario)

This document traces a single user request through the whole url4‑cloud stack — from the
browser/CLI, through the stateless **App** (FastAPI), over **NATS JetStream** (the durable run
queue plus each run's event stream), into the **runner pool** (long‑lived worker pods that fork
one child process per run), through the **aigateway connector**, and finally into the
**aigateway** service — and back to the client as a CloudEvents stream.

**Both ends of that trip are the same image.** `apps/screamingface-engine` ships one distribution
(`screamingface_engine`) and one image (`ghcr.io/screamingface/screamingface-engine`) with three
modes selected by argv: `screamingface-engine serve` is the App, `screamingface-engine worker` is
the runner pool, and `screamingface-engine run` is one run's child process. The halves are kept
apart by an import rule, not by packaging — see `.claude/scripts/check_layering.py`.

It is grounded in the actual source:
`apps/screamingface-engine/src/screamingface_engine/{cli,app,rest/routes,ws/{endpoint,bridge,registry},
adapters/{factory,k8s,jetstream},job_env,subjects}.py`,
`apps/screamingface-engine/src/screamingface_engine/runner/{main,executor,connector,config}.py`,
`packages/url4/src/url4/streaming/{interfaces/{stream,jobs,executor},lifecycle}.py`,
`apps/aigateway/src/aigateway/{main,routes/chat}.py`, and the helm chart
(`apps/screamingface-engine/deploy/helm/templates/*.yaml`).

## 1. Components in the k8s deployment

| Component | k8s object | Role |
|---|---|---|
| Client | (browser/CLI, off‑cluster) | Holds the topic capability JWT; opens the WS; issues `GET /?q=`. |
| Ingress | `Ingress` (Traefik in the kind chart) | TLS termination. |
| url4‑cloud App | `Deployment` + `Service` + `ServiceAccount` (no RBAC) | Stateless FastAPI control plane: mints tokens, hosts REST + WS, admits runs onto the durable queue, bridges NATS→WS. Configured by `ConfigMap` + `Secret` (`URL4_CLOUD_*`). |
| NATS JetStream | `nats-io` subchart (or external via `config.natsUrl`) | Per‑topic append log (each run's event stream) + the durable run queue (`url4-runq`, the admission point). Server‑assigned monotonic `sequence` = CloudEvents `sequence`. |
| Runner pool | `Deployment` (the runner pool, `replicas × workerSlots` slots) | **The App's own image**, `command: ["screamingface-engine", "worker"]`. Claims runs from the queue, forks each as a child (`screamingface-engine run`), supervises it to its terminal frame, acks. |
| aigateway | separate `Service`/`Deployment` | LiteLLM gateway; `POST /v1/chat/completions` + `GET /v1/models`. |
| Tavily | (external SaaS) | `web_search`/`web_fetch` tool backend, optional. |

The App holds **no run state**: a run's identity and its single‑use `409` guard are recomputed
from the token's topic every call via `job_name(topic) = "url4-" + sha256(topic)[:16]`
(`url4/streaming/interfaces/jobs.py`). The App calls **no k8s API** — the Job-scheduling
`Role`/`RoleBinding` were retired with the cutover (OME-1092); the only k8s objects the App
interacts with are its own Deployment/Service.

## 2. End‑to‑end sequence diagram

```mermaid
sequenceDiagram
    autonumber
    actor Client
    participant Edge as Ingress / CF Access
    participant App as screamingface-engine App<br/>(screamingface-engine serve)
    participant Reg as ConnectionRegistry<br/>(SubscriberGate)
    participant Bus as JetStream<br/>(run queue + per-run event streams)
    participant Worker as Runner pool pod<br/>(screamingface-engine worker)
    participant Child as Run child process<br/>(same image, screamingface-engine run)
    participant Conn as aigateway connector<br/>(Url4Node world)
    participant AGW as aigateway Service<br/>(LiteLLM)
    participant Tav as Tavily (web tools)

    Note over Client,Edge: Phase 0 — mint a capability token
    Client->>+Edge: POST /token
    Edge->>+App: POST /token
    App-->>Client: {token: HS256 JWT, sub=<fresh topic>}

    Note over Client,Reg: Phase 1 — attach WebSocket (the 428 interest gate)
    Client->>+Edge: WS /ws?ticket=<jwt> (subprotocol cloudevents.json)
    Edge->>+App: WS upgrade
    App->>App: JwtCodec.verify(ticket) → topic
    App->>Reg: registry.add(topic)   %% live interest now counts
    App->>+Bus: EventStream.subscribe(topic, from_sequence=None)  %% ensure_stream THEN bind
    Note right of App: Bridge: subscription task → outbound queue → writer (sole ws.send)
    App-->>Client: 101 Switching Protocols + heartbeats

    Note over Client,Bus: Phase 2 — start the run (REST control plane)
    Client->>+Edge: GET /?q=<url4 expr><br/>URL4-Capability: <jwt><br/>X-Profile: <opt><br/>traceparent: <W3C opt><br/>Prefer: respond-async|wait=<s>
    Note right of Edge: Envoy verifies Cloudflare Access,<br/>strips any client copy and re-injects X-User-Email
    Edge->>+App: GET /?q=...<br/>X-User-Email: <verified>
    App->>App: auth dep verifies URL4-Capability JWT → VerifiedClaims; topic = sub
    App->>App: _require_q(q); _require_subscriber(interest, topic)
    App->>Reg: interest.has_subscriber(topic)
    Note right of Reg: no WS attached ⇒ 428 Precondition Required
    App->>App: job_env.identity_from_headers(request.headers); profile
    App->>App: _schedule: admission gate — queue depth ceiling +<br/>per-caller in-flight cap ⇒ 503 + Retry-After
    App->>+Bus: RunQueue.publish(encode_message(...))<br/>Nats-Msg-Id = topic (broker dedupe ⇒ 409 on retry),<br/>Url4-Enqueued-At = acceptance wall-clock
    Bus-->>App: ack (durably accepted)
    alt async (Prefer: respond-async) OR sync bound elapsed
        App--xClient: 202 Accepted + Location/Link/Preference-Applied
    else sync (default)
        App->>+Bus: _scan_terminal(stream.subscribe(topic)) bounded by min(wait, SYNC_MAX_WAIT)
        Bus-->>App: Started…Result…Terminated
        App-->>Client: 200 Result body | 502/504/409 problem+json
    end

    Note over Worker,Tav: Phase 3 — the runner pool executes the run
    Worker->>+Bus: pull (round-robin across url4-runq.<bucket>)<br/>claim gates: terminal frame? ⇒ ack+skip;<br/>capability expired? ⇒ queue_expired frame
    Bus-->>Worker: message (topic, url4, deadline, per-run env)
    Worker->>Worker: fork child: screamingface-engine run<br/>(crash domain = one run)
    Worker->>Bus: in_progress heartbeats (extend ack_wait)
    Child->>Child: cli.main(["run"]) → lazily imports screamingface_engine.runner.main
    Child->>Child: params_from_env → RunnerParams(topic,url4,nats_url)
    Child->>Child: build_executor(env); load_config → /etc/url4/url4.toml
    alt [aigateway] declared (token required)
        Child->>+Conn: build_aigateway_world(cfg, token, profile, tavily_api_key)
        Conn->>Conn: routes_for(declared models) → one Url4Node route per model
        Conn-->>Child: AigatewayWorld(node, world_aclose)
    else no [aigateway] table
        Child->>Child: deny_by_default_world() (StaticIOLayer)
    end
    Child->>+Bus: JetStreamPublisher.connect; ensure_stream(topic)
    Child->>Bus: publish StartedEvent (seq 1, traceparent=root_tp)
    loop url4 DAG evaluation (Url4Executor.execute)
        Child->>Child: url4.dag.run(url4, io=node, observer=_Bridge)
        Note right of Child: sync Observer → async generator bridge
        Child->>+Conn: node dispatches processor route /<provider>/<model>
        Conn->>+AGW: POST /v1/chat/completions<br/>{model, messages[, tools]}<br/>X-User-Email, X-Profile
        opt web tools enabled (Tavily key present)
            AGW-->>Conn: choices[0].message.tool_calls
            par parallel tool execution
                Conn->>+Tav: POST /search {query}
                Tav-->>Conn: results (Title/URL/Content)
            and
                Conn->>+Tav: POST /extract {url}
                Tav-->>Conn: raw_content
            end
            Conn->>AGW: re-call with role:tool results (bounded loop)
        end
        AGW-->>Conn: completion text + usage
        Conn->>Conn: _report_usage → current_usage_sink (span)
        Conn-->>Child: completion string (+ ResolutionError on HTTP err)
        Child->>Child: _RunState maps ObservationEvent → Traced(SpanData/CostUsageData/LogData)
        Child->>Bus: publish each frame (per-span traceparent/tracestate)
    end
    Child->>Bus: publish CostUsage(scope=subtree)
    Child->>Bus: publish ResultEvent(body, media_type)
    Child->>Bus: publish TerminatedEvent(status=succeeded)
    Note right of Child: any exception ⇒ Terminated{failed} + ErrorInfo(code,permanent)
    Child->>Conn: world.aclose() (close httpx clients)
    Worker->>Bus: ack (the run's terminal frame is on the stream)

    Note over Bus,Client: Phase 4 — JetStream delivers the stream back over the WS
    Bus-->>App: frames (JetStream push, sequence per frame)
    Note right of App: Bridge._pump → outbound queue → _writer sends one CloudEvent per WS msg
    App-->>Client: Started → Log/Span/CostUsage… → CostUsage(subtree) → Result → Terminated
    Note right of Client: (sync path already returned the Result inline; WS frames are advisory there)

    Note over Client,App: Phase 5 — teardown
    Client->>App: WS close
    App->>Reg: registry.remove(topic)
    App->>Bus: (optional) DELETE / → control subject url4.runctl.<topic><br/>a running child is SIGTERM'd (Terminated{stopped});<br/>a queued run is tombstoned → 204
```

## 3. The two return paths (sync vs async)

`GET /?q=` selects the mode with RFC 7240 `Prefer` (`rest/routes.py`):

- **Synchronous (default).** After scheduling, the App itself subscribes to the topic via
  `_scan_terminal(bus, topic)` bounded by `min(wait, SYNC_MAX_WAIT)`. It consumes the stream
  until the terminal `TerminatedEvent`, then returns:
  `succeeded` → `200` Result body · `failed` → `502` · `timed_out` → `504` · `stopped` → `409`
  (all RFC 9457 `problem+json`). If the bound elapses first → degrades to `202 Accepted`.
- **Asynchronous (`Prefer: respond-async`, or sync bound elapsed).** Returns `202` immediately
  with `Location: /?topic=<topic>`, `Link` (RFC 8288 self), `Preference-Applied: respond-async`.
  The full CloudEvents lifecycle then arrives over the already‑attached WebSocket.

The WebSocket bridge and the REST sync scanner are **two independent consumers of the same
JetStream stream** — both can be attached to one topic at once (JetStream delivers each message
to every consumer). This is why the sync path can return inline while the WS still streams.

## 4. The CloudEvents lifecycle on the wire

Published by `url4.streaming.lifecycle.run` — shared code, not this app's — in this exact order,
each frame carrying a W3C `traceparent` (and optional `tracestate`) plus a monotonic integer
`sequence` assigned by the `_Sequencer`:

1. `StartedEvent` — `data.url4` = the expression
2. `LogEvent` / `SpanEvent` / `CostUsageEvent(scope=self)` — per DAG node, in evaluation order
3. `CostUsageEvent(scope=subtree)` — the pre‑result roll‑up (always `scope=subtree`)
4. `ResultEvent` — `data.body` (text) + `data.media_type`; truncated past `result_cap` bytes
5. `TerminatedEvent` — `status=succeeded` (normal) or `status=failed` + `ErrorInfo{code,permanent}`

Span frames with real per‑span identity get their **own** `traceparent` and a
`tracestate=url4.parent=<parent_span_id>`; everything else carries the run‑root `traceparent`.
The run‑root `trace_id` is adopted from a valid inbound `traceparent` (W3C "restart" rule:
malformed/absent never propagates — a fresh trace is minted instead), while `root_span_id` is
always freshly minted here.

## 5. Identity forwarding (the caller hop)

Who is calling — separate from the URL4‑capability topic token — rides the `GET /?q=` call into
the Runner and on to aigateway (`job_env.IDENTITY_HEADER_ENV`):

1. `X-User-Email` is the only source. Cloudflare Access authenticates at the edge, Envoy
   re-verifies that assertion against Cloudflare's JWKS, strips any client-supplied copy and
   re-injects the header from the verified claims — so a client cannot forge it.
2. It is NOT plain header pass-through: the App and the run's child process are different
   processes and the outgoing request does not exist yet. The App serializes it into the
   queue message's per-run env as `URL4_CLOUD_IDENTITY_USER_EMAIL` (plain env, not a Secret —
   identity authorizes nothing on its own), and the child re-renders it. `AIGATEWAY_PROFILE`
   comes from `X-Profile` the same way.
3. The run mode's `build_executor` (`runner/main.py`) branches on the declared world in
   `url4.toml`:
   - an `[aigateway]` table → `build_aigateway_world` builds a `Url4Node` whose declared routes
     call `POST /v1/chat/completions` with `X-User-Email` and `X-Profile`;
   - no table → the run's IO is `deny_by_default_world()` (empty `StaticIOLayer` — no routes,
     no holdings, no fetch map).
4. **No bearer token is carried anywhere.** aigateway runs `cloudflare_headers` when deployed
   (it reads the identity header) and `disabled` locally (every caller is anonymous); neither
   mode reads `Authorization`, and a deployed caller has no way to obtain a token because
   aigateway has no public ingress. aigateway remains the only consumer that decides whether the
   caller is acceptable — the App never inspects or verifies identity.

## 6. Web tools (optional Tavily agentic loop)

When `TAVILY_API_KEY` reaches the run's child process (a `secretKeyRef` on the runner pool's
Deployment — never a literal in the queue message, since a queue message is readable by any
worker), the aigateway connector
(`runner/connector.py`):

- declares `web_search` / `web_fetch` (OpenAI function‑calling shape) to the model,
- runs a **bounded** tool‑calling loop (`web_tool_max_iterations`, default 5):
  `tool_calls` → parallel `asyncio.gather` of Tavily `/search` & `/extract` → results appended
  as `role:"tool"` messages → model re‑called until a final answer or
  `ResolutionError(code="web_tool_loop_limit")`,
- feeds Tavily/tool failures back to the model as tool‑result text (dec:W2 — never raised),
- with no key, the request body stays byte‑identical `{"model","messages"}` (deny‑by‑default).

## 7. k8s‑specific hardening points

- **Stateless App, no RBAC (OME-1092).** The App Deployment runs under a `ServiceAccount` that
  exists for pod identity only — the Job-scheduling `Role`/`RoleBinding` are gone, so the control
  plane cannot create Pods. The worker pool's pods have `automountServiceAccountToken: false`.
- **Run‑once contract.** The worker forks each run as a child process (crash domain = one run);
  the queue's `Nats-Msg-Id` dedupe is the stateless single‑use replay guard, and the worker's hard
  wall (`deadline_s + stream grace + margin`) is the hard timeout surfacing as `timed_out`.
- **`enableServiceLinks: false`** on both the App Deployment and the runner pool — kubelet's
  legacy `{SERVICE}_PORT` injection would collide with the `URL4_CLOUD_` settings prefix.
- **Hardened runner pool.** `runAsNonRoot`, `runAsUser: 1000`, `allowPrivilegeEscalation: false`,
  `capabilities.drop: [ALL]`, `readOnlyRootFilesystem: true` + an `emptyDir` `tmp` mount,
  `seccompProfile: RuntimeDefault`.
- **One image, three modes — the mode comes from argv.** The worker pool's Deployment runs the
  App's own image with `command: ["screamingface-engine", "worker"]` (pinned in
  `deployment-runner.yaml`), and the worker forks each run as a child that execs
  `screamingface-engine run` — so the two can never be at different versions and a pod with a
  broken env fails loudly at boot rather than quietly starting a web server nothing will dial.
  What the separate slim runner image used to guarantee by construction — that a run never loads
  FastAPI, uvicorn or the kubernetes client — is now guaranteed by the import rule in
  `.claude/scripts/check_layering.py`.
- **Rollout safety.** App pods have a `preStop` sleep + `terminationGracePeriodSeconds` sized to
  cover endpoint propagation plus the worst‑case sync hold, so live WS streams and in‑flight sync
  holds aren't dropped mid‑request.
- **Config/Secret rollout.** Pod annotations `checksum/config` and `checksum/secret` force a
  roll on ConfigMap/Secret change (an otherwise‑silent stale‑env failure mode).

## 8. The 428 interest gate (why the WS must attach first)

Spec §4: no run begins with nobody listening. `rest/routes.py::_require_subscriber` calls
`SubscriberGate.has_subscriber(topic)`, which `ConnectionRegistry` backs by counting live WS
connections per topic (`ws/registry.py`). The WS endpoint (`ws/endpoint.py`) registers the topic
on accept and deregisters on close. Empty count ⇒ `428 Precondition Required` before scheduling.

This ordering is also why `JetStreamConsumer.subscribe` does `ensure_stream` **before** bind: a subscriber
legitimately arrives before the stream exists (the stream is only created when the run's child
first publishes), and a bind‑first would raise `NotFoundError` that the silent `_pump` task would
swallow — leaving the client staring at heartbeats forever.

## 9. Quick reference — files behind each arrow

| Arrow / phase | Source file |
|---|---|
| `POST /token` | `rest/routes.py::mint_token`, `auth/jwt.py::JwtCodec.sign` |
| `WS /ws?ticket=` | `ws/endpoint.py::ws_endpoint`, `ws/registry.py::ConnectionRegistry` |
| WS streaming | `ws/bridge.py::{Bridge,run_bridge}` |
| `GET /?q=` | `rest/routes.py::{start_run,_schedule,_run_sync,_scan_terminal}` |
| 428 gate | `rest/interest.py::SubscriberGate`, `ws/registry.py` |
| credential hop | `rest/routes.py::_forwarded_credential`, `runner_queue.py::encode_message`, `screamingface_engine/runner/main.py::build_executor` (names from the single `job_env.py` — a shared leaf, no longer a hand‑synced pair) |
| Run scheduling | `adapters/queue_runner.py::QueueJobRunner`, `runner_queue.py::{encode_message,RunQueue}` |
| Run runner wiring | `adapters/factory.py::build_job_runner`, `config.py::Settings` |
| mode dispatch | `screamingface_engine/cli.py::main` — `serve` (default) / `run` / `worker`, each imported lazily |
| Runner lifecycle | `screamingface_engine/runner/main.py::main`, `url4/streaming/lifecycle.py::run` |
| url4 engine bridge | `screamingface_engine/runner/executor.py::{Url4Executor,_Bridge,_RunState}` |
| aigateway connector | `screamingface_engine/runner/connector.py::{build_aigateway_world,_chat_completion_loop}`, `screamingface_engine/world_config.py::{load_config,routes_for}` |
| aigateway chat | `aigateway/routes/chat.py::chat_completions` (+ `chat_dispatch.py`) |
| stream ports + implementations | `url4/streaming/interfaces/stream.py` (the abstractions), `screamingface_engine/adapters/jetstream.py::{JetStreamPublisher,JetStreamConsumer}` (JetStream, shared leaf), `screamingface_engine/testing/memory_stream.py` (test double) |
| the layering rule | `.claude/scripts/check_layering.py`, `screamingface_engine/runner/__init__.py` |
