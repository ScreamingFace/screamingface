# screamingface-engine — execution-flow diagrams

Static reference for the execution flow through the screamingface-engine codebase and the
purpose of each source file. Companion to `docs/request-workflow.md` (the
narrative) and `docs/protocol.md` (the wire contract).

---

## 1. End-to-end execution flow (`serve` + `run` — one image, two modes)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  CLIENT (browser / CLI)                                                      │
└──────┬──────────────────────────────────────────────────────────────────────┘
       │  ① POST /token                          ② WS /ws?ticket=<jwt>
       ▼                                          ▼
┌─────────────────────────── CONTROL PLANE (screamingface_engine) ───────────────────────┐
│  entered as `screamingface-engine serve` — the default subcommand, the image's CMD     │
│  rest/routes.py ──mint_token──► auth/jwt.py  ──sign──► {token}               │
│                                                                              │
│  ws/endpoint.py ──verify ticket──► ws/registry.py .add(topic)  ◄── 428 GATE  │
│                  └─► ws/bridge.py  (EventStream → WS, single-writer)         │
│                                          ▲                                   │
│  rest/routes.py  GET /?q=                 │ same JetStream stream            │
│   ├─ _require_q            (400)          │   (sync scanner + WS bridge are  │
│   ├─ rest/interest.py      (428 if no WS) │    independent consumers)        │
│   ├─ trace.parse_traceparent (drop bad)   │                                   │
│   ├─ _forwarded_credential (CF→Bearer)    │                                   │
│   ├─ _schedule ─► JobRunner (abstract)    │                                   │
│   │      └─ exists? (409) else schedule   │                                   │
│   │            ┌─────────────┴── ADAPTER ──┐                                  │
│   │            ▼                                                               │
│   │   adapters/queue_runner.py (the deployed adapter)                          │
│   │   durable run queue + fixed worker pool (OME-1092)                         │
│   │   the worker forks each run as a child of its own image                    │
│   │            │                                                               │
│   └─ _run_sync (sync) OR _accepted (202)                                       │
└──────────────────────────────────────────────────┼────────────────────────────┘
                                                   │
                                                   ▼
┌─────────────────────────── RUN MODE (screamingface_engine.runner) ─────────────────────┐
│  the SAME image, entered as `screamingface-engine run` — serves no port, exits at end   │
│                                                                               │
│  runner/main.py  ◄── entrypoint (screamingface-engine run)                              │
│   ├─ params_from_env   ──► RunnerParams(topic,url4,nats)                      │
│   └─ build_executor    ──► world_config.py load_config (url4.toml)            │
│         ├─ [aigateway] ► runner/connector.build_aigateway_world ─► Url4Executor│
│         └─ no table    ► runner/executor.deny_by_default_world  ─► Url4Executor│
│                                                                               │
│  url4.streaming.lifecycle.run(bus, executor, topic, url4, tp)  ◄── ORCHESTRATOR│
│   │  trace.py.parse_traceparent → run-root trace context                      │
│   │  Started → (telemetry…) → CostUsage{subtree} → Result → Terminated        │
│   │            │                                                               │
│   │            ▼ async for step in executor.execute(url4, trace=…)            │
│   │  ┌──────────────────────────────────────────────────────────────────┐     │
│   │  │ runner/executor.Url4Executor                                       │     │
│   │  │   _Bridge  (sync Observer ─► async generator, priority-drop)      │     │
│   │  │   _RunState (engine events ─► Traced Span/Cost/Log + subtree)     │     │
│   │  │   drives url4.dag.run(io = aigateway Url4Node world) ─────────┐   │     │
│   │  └──────────────────────────────────────────────────────────────│───┘     │
│   │                                                                 ▼         │
│   │              runner/connector ── POST /v1/chat/completions ──► aigateway  │
│   │                              └─ optional Tavily web_search/web_fetch loop │
│   └─► bus.publish(topic, CloudEvent)  ── one per frame, monotonic sequence    │
└──────────────────────────────────────────────────┬────────────────────────────┘
                                                  │
                                                  ▼  NATS JetStream (shared append-log)
                          ┌───────────────────────┐
                          │ adapters/jetstream.py │
                          │ Publisher (run) ⇄     │
                          │ Consumer (serve)      │
                          │ — a SHARED leaf       │
                          └───────────┬───────────┘
                                      │ frames flow back up
                                      ▼
   ws/bridge.py ──► WS frames to client   AND   rest/routes.py._run_sync (inline 200)
```

---

## 2. Run mode — execution flow (`screamingface_engine/runner/`)

```
                         ┌─────────────────────────────────────┐
   entrypoint ──────────►│  runner/main.py                     │
   screamingface-engine run        │   params_from_env() → topic/url4    │
   (via cli.py, lazily)  │   build_executor()  ────────────┐   │
                         └────────────────────────────────┬──┘
                                                          │
                         ┌────────────────────────────────┘
                         ▼
                    ┌──────────────────────────────┐   no [aigateway]
                    │  runner/connector.py         │◄─────────────┐
                    │  build_aigateway_world()     │             │
                    │  → Url4Node world (routes    │   deny_by_default_world()
                    │     DECLARED by url4.toml →  │             │
                    │     POST /v1/chat/completions│             │
                    │     [+ Tavily tools])        │             │
                    └──────────────┬───────────────┘             │
                                   │  io=world.node              │
                                   ▼                             │
                    ┌──────────────────────────────┐             │
                    │  runner/executor.py          │◄────────────┘
                    │  Url4Executor.execute()      │
                    │   ├─ _Bridge  (sync Observer │
                    │   │   ─► async generator)    │
                    │   ├─ _RunState (engine evt → │
                    │   │   Traced Span/Cost/Log)  │
                    │   └─ drives url4.dag.run(io) │
                    └──────────────┬───────────────┘
                                   │ async yield ExecStep
                                   ▼
                    ┌──────────────────────────────┐
   orchestrator ◄───│  url4.streaming.lifecycle    │
   (shared, in      │   .run()                     │◄─── url4.streaming.trace
    packages/url4)  │   establish root trace       │     parse_traceparent()
                    │   Started → telemetry… →     │
                    │   CostUsage{subtree} →       │
                    │   Result → Terminated        │
                    └──────────────┬───────────────┘
                                   │ bus.publish(CloudEvent)
                                   ▼
                          JetStream ──► control plane ──► client

   ┌─────────────────────────────────────────────────────────────┐
   │  url4.streaming.interfaces.executor                         │
   │                the PORT — Executor, ExecStep,               │
   │                Traced, Completed, Telemetry, TraceContext   │
   │                (lifecycle + runner/executor both depend     │
   │                 on it, and on nothing of each other)        │
   └─────────────────────────────────────────────────────────────┘
```

`world_config.py` is the single parser for the DECLARED model world. The control plane uses it to
project discovery and the run mode uses it to build routes, so the two cannot disagree.
`url4.toml` ships in the image at `/etc/url4/url4.toml`, baked from
`apps/screamingface-engine/url4.toml`.

### Run-mode call sequence (one run)

```
runner/main.py::main()
 │
 │  ① params_from_env(env) ───────────────────► trace.py (not here; pure env parse)
 │
 │  ② build_executor(env)
 │        │  load_config(env) → url4.toml; [aigateway] table?
 │        ├─ yes ─► runner/connector.build_aigateway_world()
 │        │              └─► routes_for(declared models) → Url4Node  (+ Tavily client)
 │        │           Url4Executor(world_factory=…)  ◄── world resolved on first execute
 │        └─ no  ─► Url4Executor over deny_by_default_world()
 │
 │  ③ url4.streaming.lifecycle.run(bus, executor, topic, url4, traceparent)
 │        │
 │        │  trace.parse_traceparent(traceparent) → trace_id (or mint fresh)
 │        │  TraceContext + _Sequencer ;  bus.ensure_stream(topic)
 │        │  publish StartedEvent
 │        │
 │        │  async for step in executor.execute(url4, trace=ctx):   ◄── ④
 │        │     │
 │        │     │  ┌── inside Url4Executor.execute() ──────────────┐
 │        │     │  │ url4.dag.run(io=Url4Node, observer=_Bridge)   │
 │        │     │  │   engine → runner/connector route →           │
 │        │     │  │     POST /v1/chat/completions (± Tavily loop) │
 │        │     │  │   engine calls _Bridge.on_event() INLINE/sync │
 │        │     │  │ _RunState.map() → Traced(Span/Cost/Log)       │
 │        │     │  │ finally: cancel task, _aclose_world()         │
 │        │     │  └───────────────────────────────────────────────┘
 │        │     │
 │        │     ├─ Telemetry/Traced → _trace_fields + _wrap_telemetry → publish
 │        │     └─ Completed         → break
 │        │
 │        │  publish CostUsage{subtree} → ResultEvent → TerminatedEvent{succeeded}
 │        └─ except ─► publish TerminatedEvent{failed} + ErrorInfo
 │
 └─  asyncio.run(_main())
```

---

## 3. File purpose — one line each

### Run mode (`src/screamingface_engine/runner/`)

```
┌─ entrypoint ──────────────────────────────────────────────────┐
│ runner/main.py   env → publisher + executor → lifecycle.run() │
├─ orchestrator (shared: url4.streaming) ───────────────────────┤
│ lifecycle.py  drives executor, wraps frames as CloudEvents,   │
│               publishes the Started…Terminated lifecycle      │
├─ adapter (the only url4 importer) ────────────────────────────┤
│ runner/executor.py   Url4Executor: _Bridge (sync→async),      │
│                      _RunState (events→Traced), drives the DAG│
├─ world builder ───────────────────────────────────────────────┤
│ runner/connector.py   declared routes + credential → Url4Node │
│                       (+ optional Tavily web tools)           │
├─ declared world ──────────────────────────────────────────────┤
│ world_config.py    parses url4.toml (/etc/url4/url4.toml)     │
├─ boundary doc ────────────────────────────────────────────────┤
│ runner/__init__.py   states the layering rule the gate proves │
└───────────────────────────────────────────────────────────────┘
```

| File | Purpose |
|---|---|
| `runner/main.py` | `screamingface-engine run` entrypoint: read env (names from `screamingface_engine/job_env.py`) → wire `JetStreamPublisher` + executor → call `lifecycle.run` |
| `runner/executor.py` | The **only** url4-engine adapter (`_Bridge` sync→async, `_RunState`, `Url4Executor`) |
| `runner/connector.py` | Builds the `Url4Node` "world" of declared routes → aigateway chat (+ optional Tavily tools) |
| `world_config.py` | Parses `url4.toml` once for both control-plane discovery and Runner execution |
| `runner/__init__.py` | No re-exports — it carries the layering rule (what this half may and may not import) |

### Control plane (`src/screamingface_engine/`)

| File | Purpose |
|---|---|
| `cli.py` | The one console script, `screamingface-engine` — argv picks `serve` (default) or `run`; imports each mode lazily and is the only module exempt from the layering gate |
| `app.py` | FastAPI factory — `create_app` (DI) / `create_app_from_env` (prod) |
| `config.py` | `Settings` + replay-window TTL validation |
| `rest/routes.py` | REST control plane — `POST /token`, `GET /?q=` (sync/async), `DELETE /` |
| `rest/interest.py` | `SubscriberGate` **port** behind the 428 gate |
| `ws/endpoint.py` | `GET /ws` — verify ticket, register interest, start bridge |
| `ws/bridge.py` | `Bridge` — EventStream→WS streaming, single-writer, `Attach`/`Stop`, heartbeats, nacks |
| `ws/registry.py` | `ConnectionRegistry` — live-WS counts per topic (the real 428 source) |
| `adapters/queue_runner.py` | Prod adapter — durable run queue + worker pool (OME-1092); the queue message carries the per-run env, never a credential |
| `testing/memory_stream.py` | `InMemoryEventStream` — the headless suite's stream double (no broker) |
| `adapters/jetstream.py` | **Shared leaf** — `JetStreamPublisher` (run mode writes) + `JetStreamConsumer` (control plane reads); one binding, no second copy to keep in sync |
| `job_env.py`, `subjects.py` | The other two **shared leaves** — the Job env-var contract (per-run + per-deploy sections in one module) and the NATS subject/stream naming |
| `adapters/factory.py` | Composition root — `URL4_CLOUD_RUNNER` → queue adapter or `None` |
| `auth/*` | `JwtCodec`, RFC 9457 `Problem` handlers, FastAPI `VerifiedClaims` dependency |
| `schemas/*` | OpenAPI/AsyncAPI/CloudEvents Pydantic models (`type` `oneOf`) |
| `metrics.py`, `ops.py` | OpenMetrics `/metrics`, `/livez` `/readyz` probes |
| `testing/mock_runner.py` | Test executor/runner doubles |

### Shared (`url4.streaming`, from packages/url4)

| Package | Purpose |
|---|---|
| `url4.streaming` | The shared CONCEPTS: the wire `protocol`, the abstract `EventPublisher`/`EventConsumer`/`Executor`/`JobRunner`, and the pure logic over them (`lifecycle`, `codec`, `trace`, `job_name`). No broker and no framework — ever (it ships alongside the engine but imports none of it). The Job env-var names are NOT here — they are screamingface-engine's, and since the merge they live in exactly one module, `screamingface_engine/job_env.py`, with nothing left to keep in parity |

---

## 4. Key invariants

- The **run mode produces** the CloudEvents lifecycle; the **control plane only bridges/schedules** — it never re-shapes a frame.
- The two halves talk through **`url4.streaming`** — the wire models, the `EventPublisher`/`EventConsumer`/`Executor`/`JobRunner` abstractions and the run lifecycle — plus three shared leaves of this app's own vocabulary (`job_env`, `subjects`, `adapters.jetstream`). Neither knows how the other is built.
- **One image, three modes, chosen by argv.** The worker pool's Deployment pins `["screamingface-engine", "worker"]`, and the worker forks each run as a child that execs `screamingface-engine run` — so a pod missing its env fails loudly at boot instead of silently starting a web server nothing will dial. `serve` is the default, which is what keeps the image `CMD` and the chart's Deployment command unchanged.
- **The import graph is the boundary.** Two distributions used to make a cross-import uninstallable; one venv makes it merely a typo that type-checks. `.claude/scripts/check_layering.py` replaces that structure: `screamingface_engine.runner.*` must not import the control plane and vice versa, `cli.py` excepted. Verified empirically — importing `screamingface_engine.runner.main` loads none of fastapi, uvicorn, starlette, kubernetes, jwt or prometheus_client, which is what holds a Job's cold start to the engine + httpx + nats-py.
- `lifecycle.run` ↔ `runner/executor.py` talk **only** through the `Executor` port; the lifecycle never imports `url4`, which is why the control plane could run it in-process too.
- Only `runner/connector.py` + `runner/main.py` construct a `Url4Executor`; everything else treats it as an opaque `Executor`.
- The run mode is a 4-layer pipeline: **entrypoint → orchestrator → adapter → (url4 engine + aigateway world)**, all typed by one `Executor` abstraction; the orchestrator is shared code in `url4.streaming`, only the ends are this app's own.
