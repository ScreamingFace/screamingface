---
name: url4-engine
description: >-
  Use when DESIGNING or REVIEWING the url4 engine / AI-ensemble execution protocol — how a
  url4 node resolves an expression, WS(stream) vs HTTP-GET(transactional) transport, recursive
  fan-out/reduce DAG execution, subprocess leaves, and how logs / OTel gen_ai.* spans /
  cost.usage taxonomy forward upstream. PROPOSED design-stage invariants (engine currently
  legacy-tag-only, reviving as packages/url4-python-sdk): url4-expression-as-address,
  node-selects-transport, one trace_id per tree, cost.usage as a separate event, hybrid
  relay ↑ + OTLP durable export, run handle (Location / Link rel=self) for async fetch. Companion to
  sdlc-python (build loop) and working-in-this-repo (routing).
---

# url4 Engine — Ensemble Execution & Telemetry Doctrine

**Announce at start:** "Using the url4-engine skill — design-stage doctrine for the url4
ensemble execution protocol."

> **STATUS — PROPOSED / DESIGN-STAGE. Terms and transport locked 2026-09-04 (OME-1110).**
> The SDK is `packages/url4`; the runtime is `apps/screamingface-engine`. The invariants below
> are the **agreed mental model**, not enforced law. Treat each as a design default to apply and
> defend, and STOP-and-ask before hardening any of them into code. Kevin owns the url4
> grammar/AST (spec Parts A/B, v0.5 DRAFT); this skill owns the *execution & telemetry*
> architecture around it. **Read first:**
> `docs/spec/2026-09-04-OME-1110-url4-topology-reframing.md` — it defines the words used here
> and supersedes this skill where they disagree. F4 is **resolved** there (§7).

## Terms (OME-1110, locked)

| Word | Meaning | Spec word (Part A §1.4) |
|---|---|---|
| **Node** | a stateless function at a path; `GET <path>?q=<expr>`; every node evaluates url4 | *Endpoint* |
| **Host** | an origin that mounts nodes at paths; `/` is its default node; answers discovery | *Node* |
| **Mount** | `local` (in-process) · `command` (subprocess, N4) · `proxy` (declared target) | — |
| **Evaluator** | whatever runs an expression; every node contains one | "the node executes" |
| **Request tree** | the hosts and nodes one expression touches (strict tree, v0.2 §16.1) | request/call tree |

Not protocol words: ensembler, orchestrator, swarm, composition, plan, fusion.

This doctrine is the CLAUDE.md hexagonal mandate applied to a *recursive network of
processes*: the url4 grammar/AST/resolver is a **port** (the SDK); the engine wires backends
via a registry and **never imports them directly**; and every node is a small process
addressed by a url4 expression. `apps/aigateway` (LiteLLM-based, port 9105, SSE) is the
upstream-provider boundary a leaf node calls; it is not itself a url4 node.

## The mental model (two diagrams)

![Architecture — telemetry-forwarding url4 node tree](../../../docs/diagrams/ensemble-node-architecture.png)

![Sequence — one 4-level nested run](../../../docs/diagrams/ensemble-node-sequence.png)

Rendered diagrams (SVG source + PNG): `docs/diagrams/ensemble-node-architecture.*` (the node
tree + telemetry planes) and `docs/diagrams/ensemble-node-sequence.*` (one nested run:
descent → leaf exec → live telemetry up + OTLP export → ascent/reduce). The canonical
4-level example both diagrams share:

```
L0  CLIENT (ensembler) ── opens WS ──▶ N1
L1  N1  root ensemble      [WS]   url4: (A, B)!reduce          fan-out → reduce
      ├─ L2  N2  sub-ensemble  [WS]   url4: (C, D)!reduce
      │       ├─ L3  N4  interior   [WS]
      │       │        └─ L4  N6  leaf  [HTTP GET] ── spawns local subprocess
      │       └─ L3  N5  leaf  [HTTP GET · cacheable]  + Link header
      └─ L2  N3  model node   [WS] ──▶ aigateway (upstream provider, SSE)
```

## Node model (N)

- **N1 — The url4 expression IS the address.** A node is reached over HTTP with its url4
  expression (`[name:weight:]path(context)!<intent>`) as the address. Because the address
  fully determines the work, a transactional call is a `GET` that is **idempotent in the
  RFC 9110 §9.2.2 sense** (no extra server-side effect on repeat) and cacheable at the node's
  discretion (v0.2 §16.3.7: intent outputs are the node's own work product). Results need not
  be deterministic. *This is why GET — not POST — is the transactional verb.*
- **N2 — The requestor asks, the node decides** (see T). Every node answers the same `GET`;
  the requestor asks for `delivery=stream|sync|async` and the node honours it or falls back
  (v0.2 §11.4 + the sync floor). Nothing outside the node dictates its mode.
- **N3 — Nodes are recursive; execution is a DAG.** An `intent` may itself be a relative
  url4 URL the engine resolves in-process, so a node fans out to child url4 nodes. The
  ensemble shape is **fan-out N backend-calls → reduce** (`(a,b,c)!reduce`, `!*` broadcast,
  `*source(body)!intent` collection-iteration). Bounded concurrency guards the
  collection-fan-out failure mode (see `aigateway/core/concurrency.py`).
- **N4 — A leaf may spawn local subprocesses** (e.g. a coding CLI). Subprocess stdio is
  telemetry like any other signal (O2) and forwards upstream (F).
- **N6 — Typed payloads (OME-1110 §8).** A node is a universal inference processor: every
  edge carries a typed value named by its media type (text is the default); binary results go
  inline below a node-declared threshold and by reference (`result.artifact`, plain https data
  URL) above it; nodes advertise `accepts`/`emits`. No grammar change.
- **N5 — Core never imports backends.** Grammar/AST/resolver live in `packages/url4-python-sdk`
  (a port); backend routes (`/claude`, `/codex`, `/gemini`) register as adapters; wiring is
  registry-driven. *Same hexagonal law as the rest of the monorepo.*

## Transport & modes (T)

- **T1 — One GET, the node picks the richest delivery it has (OME-1110 §6).** The evaluator
  sends `GET <node>?delivery=stream&q=…` with `Upgrade: websocket` and `Accept:
  text/event-stream, application/json`. The node answers `101` (WebSocket frames), or `200
  text/event-stream` (SSE, spec v0.2 §11.2), or `200 application/json` (sync), or `202 +
  Location` (async). Live events — log records, OTel spans, `cost.usage` (O2), then `result`,
  then `envelope` — carry the same names over WS and SSE. **sync is the only MUST**; SSE, WS
  and async are SHOULD, advertised per node in the capabilities document.
- **T2 — HTTP GET = transactional.** Sync: `Accept: text/plain` (default) returns the bare
  answer with no telemetry; `Accept: application/json` returns the envelope (`meta=summary`
  by default; `meta=full` adds a `telemetry` block with logs and spans, redactable per node
  policy, v0.2 §14.4). `fmt` is the answer's content format and is orthogonal.
  Async (`Prefer: respond-async`): `202 Accepted` + `Location` run handle (also as
  **RFC 8288 `Link rel=self`**) so the caller can poll status, read the durable record, or
  `DELETE` to cancel (F3).
- **T3 — Either edge may be either mode.** Client→node and node→node edges independently
  land on WS, SSE, sync or async. In **all** cases the three signals forward upstream (F) —
  mode changes the *delivery channel*, never *whether* telemetry propagates. Ladder:
  WS → SSE → sync, decided by the node in one round trip; `sync → async` on timeout; `any →
  sync` is always legal (sync is the universal floor).

## Observability — three signals, one trace (O)

- **O1 — One `trace_id` spans the whole tree.** Each node is a child span; the tree shares
  one W3C trace. A node links to its parent via the incoming `traceparent` span-id.
- **O2 — Three distinct signals, deliberately separate:**
  1. **logs** — structured records tagged `trace_id`/`span_id`.
  2. **spans** — OTel GenAI semantic conventions (`gen_ai.operation.name`,
     `gen_ai.provider.name`, `gen_ai.request/response.model`,
     `gen_ai.usage.input_tokens`/`output_tokens`). **Token counts live here.** Opt in with
     `OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental`.
  3. **`cost.usage`** — a **separate taxonomy event, NOT a span attribute.** *OTel keeps cost
     out of the span standard on purpose (cost is derived downstream from tokens × pricing);
     modeling it as its own event is the industry pattern (Langfuse `costDetails`).*
- **O3 — `cost.usage` schema + roll-up.** `{ trace_id, span_id, parent_span_id, node,
  provider, model, pricing_version, usage:{input_tokens, output_tokens, cache_read,
  cache_creation, reasoning}, cost:{…USD per type, total}, scope: "self"|"subtree" }`. Each
  parent emits its own `self` event **and** a `subtree` event = self + Σ(children.subtree).
  *The client sees per-node cost and one grand total.*
- **O4 — Context propagation is explicit per hop.** HTTP hops inject/extract
  `traceparent`/`tracestate` headers; SSE events and the product WS session carry
  `traceparent` inside each **event envelope**. Never open a span per raw event — span
  logical operations, sample the rest.

## Forwarding topology — HYBRID (F)

- **F1 — Live relay ↑.** Each non-leaf node **merges its children's telemetry with its own
  and re-emits upstream** over its own WS. The client's single stream to the root is the whole
  merged tree — the real-time *view*.
- **F2 — Durable export = OTLP.** Every node **also** exports its signals over OTLP to the
  trace backend — the *record of truth*. Relay is fast but lossy (a crashed mid-tree node
  drops its subtree's live events); the backend reconciles. (The design-only "Enclave store"
  is superseded; see `docs/observability-state-of-play.md`.)
- **F3 — The run handle resolves to the durable record.** An async caller reads status and
  the durable record via the `Location` / `Link rel=self` handle (T2), and cancels with
  `DELETE` on it.
- **F4 — RESOLVED (OME-1110 §7).** A one-shot `GET` returns its telemetry **in the body**:
  the envelope's `meta` (`none | summary | full`, v0.2 §13.2), with child envelopes nested at
  `meta=full` (v0.2 §13.3). Stream mode returns it as SSE events; OTLP is the durable copy.
  The older diagrams' "store-side only" assumption is withdrawn.

## Red flags — STOP

| Thought | Action |
|---|---|
| "Make the transactional call a POST." | STOP (N1). url4-expression-as-address ⇒ idempotent GET. |
| "The interior node calls the model backend directly." | STOP (N5). Backends are registry adapters; core never imports them. |
| "Put the dollar cost as a span attribute." | STOP (O2/O3). Cost is a *separate* `cost.usage` event; only tokens go on spans. |
| "Open a span per SSE event / WS frame." | STOP (O4). Span logical operations, not events. |
| "The child dumps telemetry only to the collector; parent reads it there." | STOP (F1). Live path is per-hop relay; the store is the *durable* second path, not the only one. |
| "A leaf can skip forwarding — it's a leaf." | STOP (T3). Every mode forwards all three signals upstream. |
| "Point the `Link` header at the node's own ephemeral buffer." | STOP (F3). It resolves to the durable record. |
| "Probe WS, then SSE, then sync with three requests." | STOP (T1). One GET with `Upgrade` + `Accept`; the node picks. |
| "Make WS or async a MUST for every node." | STOP (T1). Only sync is a MUST; a serverless function offering sync + SSE is conformant. |
| "Call the server a node and the path an endpoint." | STOP (Terms). Host = origin; Node = the function at a path. |
