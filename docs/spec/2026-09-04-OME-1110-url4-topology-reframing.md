---
title: "url4 topology — endpoint, node, discovery, addressing, transport"
subtitle: "Sharp definitions before the Engine grows further"
status: proposed — owner review; one decision left open in §5; reconciled 2026-09-15 with Kevin's Part A §1.4 refresh, PR #19 commit 2a939bff (draft, unmerged) — see §12 and Appendix D
created: 2026-09-04
ticket: OME-1110
owner: Sergey Bershadsky (execution and telemetry architecture)
grammar-owner: Kevin McDonough (URL4 spec, Parts A/B)
spec-pointers: URL4.ai Specification v0.5 DRAFT — Part A §1.4 at PR #19 (2a939bff), Parts A/B on main, Parts C–I drafts on url4-refactor
---

# 0. The eight answers

This document fixes the words we use for the pieces of url4. It is short on purpose.
Each section states a definition, says where the spec agrees or is silent, and stops.

**Reconciled 2026-09-15.** Kevin's Part A §1.4 refresh — `screamingface-design` PR #19, commit
`2a939bff`, still a **draft** — adopted most of what this document proposed, so much of what
follows now cites the spec rather than arguing with it. Where the two differ, Kevin's text wins
and the difference is recorded as a delta. §12 lists what changed; Appendix D is the term-by-term
crosswalk.

| # | Question | Answer |
|---|---|---|
| 1 | What is an endpoint? What is a node? | An endpoint is a stateless function behind a path (`/claude`): it takes `(context)!intent`, returns a result, and can evaluate a full url4 expression. A node is the origin that serves a set of endpoints, `/` being its default. |
| 2 | Who owns what? | The node owns discovery, credentials and outbound traffic (§4, §11). Endpoints own nothing but their function. Every requester that runs an evaluator is itself a node (§4, §13). |
| 3 | Swarm? Composition? | Not protocol words. The expression **is** the composition. The nodes it touches are its request tree. "Swarm" is only a deployment word for one operator's nodes. |
| 4 | `.well-known` or OPTIONS? | Three mechanisms now: the node document (Part G §27.1), the `Capabilities` response header (also §27.1), and OPTIONS (ours). §5 documents all three; the owner picks there. |
| 5 | `/name` vs `url4://name`? | `/name` is an endpoint on the node that is evaluating. `url4://name` is node `name`'s default endpoint `/`. Spec Part B §5.4 already says this. |
| 6 | Where does an ensemble run? | Wherever an evaluator runs: the SDK on a laptop, or a node. A local node may mount remote endpoints under local names (proxy mounts). |
| 7 | Can I test a node first? | One fetch of the node's capabilities document, or one OPTIONS per endpoint (§5). A **dry run** — evaluate without executing, envelope and no result — is now the spec's own word (Part A §1.4.3); only its shape is open (§10). |
| 8 | Streaming fallback? | One GET asks for the richest mode; the endpoint answers with the best it has: WebSocket, then SSE, then sync (§6). Sync is the only MUST. The spec now carries this as the **response ladder** and lists `websocket` as a fourth `delivery` value (Part A §1.4.4); Part C has yet to catch up. |
| 9 | Text in, text out? | A habit, not a rule. Every edge carries a **typed payload** (text, image, audio, video, embeddings) named by its media type. Text is the default. No grammar change (§8). |

**What changes against today**

- The Engine becomes a url4 **node**. Today no url4 endpoint is reachable over HTTP; the SDK's endpoint-to-endpoint code is unused.
- Every endpoint speaks the same GET. The endpoint picks the richest delivery it supports: **WebSocket → SSE → sync**, in one round trip. Sync is the only MUST.
- We keep the spec's two words: a **node** is an origin that serves a set of **endpoints** (`/claude`, `/codex`, …). No rename is asked of Kevin. Part A §1.4.2 has since added a **host system** — the machine a node runs on — which we do not need and do not use; §1 says why "host" stays out of this document.
- An endpoint is a **universal inference processor**: image generation, speech, video and multimodal ensembles become ordinary expressions on the same engine, telemetry and cost accounting (§8).
- **Most of this is no longer a proposal.** `Mount`, `Evaluator`, `Dry run`, `Degradation`, the response ladder, `Scheme adapter`, `Flow constraints`, `Attribution`, `Run handle` and the `application/url4-envelope+json` envelope switch are all in Part A §1.4 as of PR #19. What is left open is in the companion PDF.

# 1. Terms

Eleven words. Each has one meaning. **Almost all of them are now the spec's own:** Kevin's Part A
§1.4 refresh (PR #19, `2a939bff`, still a draft) adopted most of what this document proposed, so
the "spec word today" column has largely stopped saying *not defined*. Appendix D records the
crosswalk term by term; what follows is the short list a reader needs to get through §2–§9.

| Our word | Meaning | In the spec (Part A §1.4 @ 2a939bff) | In the SDK | In the Engine |
|---|---|---|---|---|
| **Endpoint** | A logical interface on a node that evaluates url4, reached at an endpoint path. | §1.4.2, same word — now *an interface*, distinct from the path that names it | an entry in `Url4Node`'s endpoint registry | a route such as `/anthropic/<model>` |
| **Endpoint path** | The URI path (`/claude`) identifying an endpoint relative to the node address. | §1.4.2, **new** — the spec now separates interface from path | the registry key | the route |
| **Node** | An origin that serves a set of endpoints, `/` being the default, and answers discovery. | §1.4.2, same word | `Url4Node` | the App, after this change |
| **Node address** | The node's network address: a URI scheme plus an RFC 3986 authority. | §1.4.2, **new** | `Url4Node`'s origin | the App's origin |
| **Target** | The absolute or relative endpoint URI an expression is addressed to: node address + endpoint path. | §1.4.3, sharpened — it was "an absolute/relative URI defining the Node + Endpoint" | `FetchRequest`'s destination | the route the Runner calls |
| **Mount** | The binding of an endpoint path to its evaluator: `local` (in-process), `command` (subprocess), `proxy` (declared target). | §1.4.3, **adopted verbatim from this document** (was *not defined*) | `endpoint()`, `[commands]`, — | in-process handlers only |
| **Evaluator** | Whatever runs an expression: resolves sources, fans out, reduces, runs the intent. | §1.4.3, **adopted** — and widened: it *may or may not* also be the intent processor | `url4.dag.run` | `Url4Executor` in the Runner |
| **Intent processor** | What turns resolved context plus intent into a result: a model call, a script, a command. | §1.4.3, same word | endpoint handler | one `httpx` call to aigateway |
| **Requestor** | Whoever submits an expression to a target for evaluation. | §1.4.3, same word | `Client` | product client |
| **Request tree** | The nodes and endpoints one expression touches. | §1.4.3, **adopted with a change** — the spec now says an evaluator *may expand* the tree and drops "strict tree, never a graph" (Part H §29.1). Appendix A delta 14 asks whether that is deliberate. | the compiled DAG, per endpoint | one run |
| **Capabilities document** | JSON a node publishes to say which endpoints, mounts, features, delivery modes and schemes it offers. | §1.4.5 and Part G §27.1–§27.2 — now also naming the `Capabilities` response header | none | none |

Words we do not use in the protocol: *ensembler*, *orchestrator*, *swarm*, *composition*, *fusion*.
"Fusion" stays product copy. *Plan* has left this list: the spec now defines **dry run** (§1.4.3),
and §10 asks only what shape it takes.

**"Host" is not one of our words.** Part A §1.4.2 now defines a **host system** — a physical or
virtual machine supporting one or more nodes — which is a useful deployment word and changes
nothing here. But §1.4.4 and the §1.4.3 `Scheme adapter` row then use "host" to mean the *node*:
it is the node that negotiates delivery, picks a ladder rung and holds scheme credentials. A host
system negotiates nothing. This document keeps "host" out entirely; Appendix A delta 13 proposes
the same for those four rows.

Naming note: Parts C–I on the `url4-refactor` branch still use the older `abc://` scheme and
`ABC-*` headers; Parts A/B use `url4://`. This document writes `url4` and `URL4-*` throughout and
assumes the rename Kevin lists as his open question 19 (Part I §43).

# 2. Addressing

Three address forms, plus any other scheme as data. The spec fixes their meaning in Part B §3.1.1,
§3.5 and §5.4; we add one rule about the root.

Part A §1.4.2–§1.4.3 now names the parts: a **node address** is the scheme plus RFC 3986 authority,
an **endpoint path** identifies an endpoint relative to it, and a **target** is the two together —
the endpoint URI an expression is addressed to. The forms below are targets.

![addressing](../diagrams/url4-topology-addressing.svg)

- `/claude(ctx)!'go'` — an endpoint on the node that is evaluating. Resolves to `url4://<current node>/claude` (Part B §5.4).
- `url4://beta.example/claude(ctx)!'go'` — an endpoint on another node. That node evaluates the sub-expression itself (Part B §3.1.1; SDK invariant OME-535).
- `url4://beta.example` — the node's default endpoint. **Our rule: `url4://node` ≡ `url4://node/`.**
- `https://data.example/rows` — plain HTTP data. No url4 headers, no envelope, `@` is an error (Part B §3.5).

**Root and version.** `/` is the node's default endpoint. The spec makes `/v1` the protocol-version path (Part D §19.1) but its own examples already write `abc://thepost?q=…` with no path at all (Part I §41.27). We keep both: `/` serves the current version; `/v1` is an explicit alias. Two tensions to settle with Kevin: Part D §19.4 gives the `v` parameter precedence over the path, and §19.3 says a nested expression takes its version from the path it targets, which a bare node address does not carry. The SDK's `url4 serve` (`/v1`) and `Client` (default `/v1`) move to `/` (Appendix B).

**Scheme inheritance.** A bare relative data URI inherits the scheme of the request that carried it (Part B §5.4.1). Under `url4://` it is a url4 read; under `https://` it is a plain read.

**Any scheme is a source — now the spec's own rule.** This document proposed generalising the
spec's `s3://` line into a **scheme adapter**; Part A §1.4.3 adopted it, as "a non-url4 source
reader mounted on a node for fetching non-HTTP scheme data (`s3://`, `pg://`, `sqlite://`), typing
its result, and advertised in the node's capabilities document", generalising Part B §3.5. The
rules below therefore describe the spec, not a proposal. Two notes on the adopted row: it says the
adapter uses "the **host's** own credentials" where it means the node's (Appendix A delta 13), and
it carries a stray trailing period. The SDK already has the slot: `FetchRequest.kind` is `url4`,
`http`, `relative`, or `other`.

```
(sales=pg://warehouse/analytics.monthly_sales,
 logo=s3://brand-assets/logo.png;accept=image/png,
 notes=sqlite:///srv/app/notes.db/notes,
 policy=https://data.example/policy.md)!'Draft the Q3 update. Use the logo.'
```

Rules:

- **The evaluating node resolves it, with its own credentials.** `pg://warehouse` names a connection the node knows; the expression never carries a secret, because the expression is the shareable audit artifact (Part A §1.2). The spec's delegated-credential token can only target `abc_node` or `http_source` (Part H §31.4), so node-owned credentials are the only way a non-HTTP scheme gets any.
- **The adapter types the result** (§8): an S3 object carries its stored `Content-Type`; a table or query returns `application/json` rows, or `text/csv` when asked with `;accept`. Rows are a collection, so `pg://warehouse/analytics.monthly_sales*(row)!'summarise $item'` iterates them (Part B §5.3).
- **Advertised, or refused.** The node lists its schemes in the capabilities document; an unlisted scheme is `unsupported_mode`, permanent (Part B §3.5). Access control and consent apply as for any source (Part B §5.6.4). Such a source is not url4-aware: the envelope marks it `abc_aware: false` and attribution stops at it (Part G §26.4), the same as for any plain HTTP read.
- **Hexagonal.** A scheme adapter is an `IOLayer` adapter registered by scheme; the core never imports it. `url4 serve` gains a `[schemes]` table beside `[data]`.

What a scheme's path means (bucket and key; database, schema and table; file and table) is the adapter's contract, not the grammar's. The grammar only sees `scheme://authority/path`.

# 3. Endpoint contract

An endpoint is a function. That is the whole idea.

Part A §1.4.2 now says it more precisely than we did: an endpoint is *a logical application
interface, supporting url4 evaluation, exposed by a node and identified relative to the node
address by an **endpoint path***. The interface and the path that names it are two words now, and
this document follows the spec: "endpoint" for the function, "endpoint path" for `/claude`.

![anatomy](../diagrams/url4-topology-anatomy.svg)

An endpoint:

- **MUST** answer `GET <path>?q=<expression>` and evaluate the expression. Every endpoint evaluates url4; an endpoint may walk a DAG before it reaches its own intent processor. There is one grade of endpoint, not two.
- **MUST** be stateless per invocation. It keeps nothing between calls. Its own data is reached through `@` (Part B §5.6) and lives behind it, not in it. The one exception the spec defines is an agent session (Part G §28): the *coordinating* node holds the session and its transcript for the session's life; *participant* endpoints stay stateless because the transcript travels with every turn. `;coord=` selects a coordination mode (`session`, `debate`, `roundrobin`, `freeform`); the session id is endpoint-issued (`Session-Id` header), not requestor-supplied.
- **MUST** return the envelope (Part D §17) and state the delivery mode it actually used (Part C §11.4).
- **MUST NOT** resolve `@` inside a sub-expression addressed to another node (Part B §5.6.3.1).
- **MUST** answer sync. **SHOULD** offer stream (SSE), WebSocket, and async, and advertise which (§5, §6). When asked for more than it has, it answers with the richest mode it does have; that is never an error.
- **MAY** be mounted on any node, or be its own origin. A Lambda-style function with its own URL is a node with one endpoint.
- Speaks GET. A WebSocket, when offered, is the same GET with `Upgrade: websocket` (§6). Other verbs are 405, except the ones this document adds: `DELETE` on a run handle (§6) and, if adopted, `OPTIONS` (§5).

Endpoints share nothing. An endpoint knows another endpoint only by address, and only because the expression named it.

# 4. Node contract

A node is an origin. It routes; it does not evaluate.

- Mounts one or more endpoints at paths. `/` is the default endpoint.
- Mount kinds: `local` (a function in the process), `command` (a subprocess), `proxy` (forwards to a declared target on another node). **Part A §1.4.3 adopted `Mount` and these three kinds verbatim**, alongside the spec's own intent-processor types `internal`/`function`, `code` and `abc_delegate` (Part G §27.3). One correction to pass back: the adopted row annotates `command` as "(subprocess, **N4**)", but N4 is a doctrine item in `.claude/skills/url4-engine/SKILL.md`, not a spec anchor (Appendix A delta 15). A proxied relative call is exactly the spec's delegation: the caller has already resolved the context, so what crosses the wire is materialised sources plus the intent, never a raw sub-expression. A `command` mount is code execution and inherits the pinning and signing rules of Part H §36.
- Declares proxy mounts with their targets in its capabilities document. Attribution and consumer disclosure (Part H §29.2.1) need the real target, so proxies are never hidden; a source may also cap redistribution depth or name permitted consumers (Part H §29.2.2), and a proxy target is a consumer.
- Serves discovery (§5) and the version alias `/v1` (§2).
- A local SDK process that mounts remote endpoints under local names is a node. That is how "run the ensemble on my laptop, but call `/claude` as if it were mine" works.

# 5. Discovery — the open decision

Three ways for a requestor to learn what a node can do. The draft Part G specifies the first two: a
capabilities document (SHOULD) and a `Capabilities` response header that MAY point to it (Part G
§27.1). OPTIONS is ours; it appears nowhere in the spec. The spec also reaches for `.well-known`
for the policy registry (`/.well-known/abc-policy`, Part H §30.2), so two well-known documents will
coexist.

**One thing settled since 2026-09-08.** Part A §1.4.5 now writes the path as
`/.well-known/url4-capabilities` — the url4-named form this document has used throughout, where
Part G still says `abc-capabilities`. That is Kevin's open question 19 (Part I §43) resolving in
passing for this one document. §1.4.5 also states the `Capabilities` header in the same row, which
is mechanism C below; the choice between A, B and C is still the owner's, and the recommendation
stays A + C.

![discovery](../diagrams/url4-topology-discovery.svg)

| | A · node document `GET /.well-known/url4-capabilities` | B · per endpoint `OPTIONS /<endpoint>` | C · `Capabilities` response header |
|---|---|---|---|
| "Can this node run my expression?" | one call, whole answer | one call per endpoint named in the expression | pointer only; still one fetch of A |
| Standalone function with its own origin | works: the document sits at that origin's root | works | works |
| Endpoint behind a shared, non-url4 gateway | invisible unless the gateway lists it (RFC 8615: root of the origin only) | works: the endpoint answers for itself | works: any ordinary response can carry the pointer |
| Caching | ordinary GET: `ETag`, CDN, browser cache | not cached by CDNs or browsers | rides on the cached response |
| Browsers and CORS | plain GET | preflight uses the same verb; CORS middleware often answers first (RFC 9110 §9.3.7 allows a body, browsers ignore it) | plain header |
| Gateways and serverless platforms | fine | some strip or auto-answer OPTIONS | fine |
| Proxy mount targets (attribution) | listed in one place | per endpoint | via A |
| Spec status | Part G §27.1, SHOULD; schema Part G §27.2 | not in the spec | Part G §27.1, MAY |

Both share one hazard: the Engine's JWT header is called `URL4-Capability`. The document is "capabilities". Appendix B proposes renaming the header.

**Capabilities document: the spec's shape, plus our additions.** Part G §27.2 already defines the top level: `abc_version`, `node` (one canonical URI: our *node*), `self_ref_support`, `collections[]` (`id`, `path`, `description`, `element_schema`, `formats`, …), `behaviors`, `intent_processors[]` (`id`, `type` ∈ `internal | abc_delegate | http_delegate | code | function`, `endpoint`, `capabilities`), `processor_policy`, `mode_support`, `agent_profiles`. Content types come from Part F §25.4 as `consumes` / `produces`. Sub-paths are read as *collections* (Part G §27.4). Our additions, marked, are what makes a processor addressable as an endpoint:

```json
{
  "abc_version": 1,
  "node": "url4://alpha.example",
  "default_processor": "summarize",                       // ours
  "intent_processors": [
    { "id": "summarize", "type": "internal", "path": "/summarize",   // path: ours
      "consumes": ["text/plain"], "produces": ["text/plain"],
      "delivery": ["sync", "stream"] },                                 // delivery: ours
    { "id": "upper",     "type": "code",     "path": "/upper" },
    { "id": "claude",    "type": "abc_delegate", "path": "/claude",
      "endpoint": "url4://beta.example/claude" }
  ],
  "schemes": ["s3", "pg", "sqlite"],                        // ours (§2)
  "collections": [ { "id": "science", "path": "/science", "self_ref_eligible": true } ],
  "self_ref_support": true
}
```

One point to settle with Kevin: the spec's document describes one node whose processors are addressed by `id` and whose sub-paths are collections; our endpoints need a path each. `intent_processors[].path` is the smallest change that gives both.

> **Owner decision (open).** Pick one:
>
> - [ ] **A only** — node document is a MUST; nothing per endpoint.
> - [ ] **B only** — OPTIONS per endpoint is a MUST; no node document.
> - [ ] **A MUST + C SHOULD** — the spec's pair, one level stronger than its SHOULD/MAY.
> - [ ] **A MUST + B SHOULD** — the document indexes the node; an endpoint may also answer OPTIONS with its own entry.
>
> Recommendation, revised after reading Part G: **A MUST + C SHOULD**, B dropped. The `Capabilities` header solves the gateway case that motivated OPTIONS, and it is already in the draft.

# 6. Delivery and transport

**This section is no longer a proposal.** Part A §1.4.4 has adopted both halves of it. `Delivery
mode` now lists four values — `sync` (one body), `stream` (SSE on the same GET), `async` (202 plus
`poll_url`) and **`websocket`** (101 on the same GET) — with `sync` the only one every endpoint
MUST support. And the **response ladder** is now a spec term in its own right: "the mechanism by
which a node responds with the richest delivery mode it supports, WebSocket → SSE → sync… answering
below a requested mode level is reported as a degradation, not an error", recorded as an extension
of Part C §10.2. `Degradation` itself is likewise now defined (§1.4.4).

Two things to carry forward. Kevin's own row is annotated **"SPEC SECTION NEEDS UPDATING"** — Part
C §11 still describes three modes and two ladder edges, so §1.4.4 and Part C disagree until that
lands; Appendix A delta 4 is now about closing that gap rather than proposing the ladder. And both
new rows say a "**host**" responds, where it is the node that negotiates and answers (Appendix A
delta 13).

Part I §43 question 26 rules `ws://` *sources* out of scope; that is a different question from a
WebSocket *answer* on the endpoint's own GET, and adopting `websocket` as a delivery value settles
it in our favour.

![delivery](../diagrams/url4-topology-delivery.svg)

**One request, the endpoint picks.** The evaluator sends the richest ask it can, once:

```
GET /claude?delivery=stream&q=(ctx)!'go'
Upgrade: websocket
Accept: text/event-stream, application/json
```

The endpoint answers with the best it supports. RFC 6455 lets a WebSocket handshake ride an ordinary GET; RFC 9110 lets a server ignore `Upgrade` and answer normally. So one round trip covers the whole ladder:

| Endpoint answers | Meaning | Telemetry travels as |
|---|---|---|
| `101 Switching Protocols` | **WebSocket**: bidirectional; cancel and attach in-band | frames, same names as the SSE events |
| `200 text/event-stream` | **stream**: SSE on the same GET (Part C §11.2) | SSE events, then `result`, then `envelope` |
| `200 text/plain` or `application/json` | **sync**: bare answer, or the envelope, by `Accept` | envelope `meta` (below) |
| `202` + `poll_url` | **async**: `delivery=async`; the 202 body carries `job_id`, `rid`, `poll_url` (Part C §12.5); `GET` it for status, `DELETE` it to cancel | on the handle |

Rules:

- **sync is the only MUST.** SSE, WebSocket and async are SHOULD, advertised per endpoint in the capabilities document (§5). A serverless function that offers only sync and SSE is conformant.
- **Ladder, not error.** WebSocket → SSE → sync. An endpoint answering below the ask is normal; the envelope's `delivery` field says what happened (Part C §11.4), and the degradation is reported like any other (Part C §10.2.2). Part C §11.4 still lists only two edges, `stream → sync` and `sync → async`; Part A §1.4.4 now carries the full WebSocket → SSE → sync ladder and the `any → sync` rule, so the two parts disagree until Part C is updated.
- **Async is one of the spec's four `delivery` values** (§1.4.4: `sync`, `stream`, `async`, `websocket`). It is requested with `delivery=async` (Part C §9.1), or entered by the endpoint when a sync run would outlive the timeout (Part C §11.4 `sync → async`). The Engine's `Prefer: respond-async` becomes an alias. The run handle is the `poll_url` field of the 202 body; a `Location` header mirroring it is our addition.
- **Browsers go SSE-first.** A browser cannot attach `Accept` to a WebSocket handshake, so a browser evaluator asks for SSE and upgrades only where the capabilities document says WebSocket is offered.
- **The Engine's product session** keeps its WebSocket at `/ws`. It is one instance of the WebSocket rung, not a separate protocol.
- **Telemetry is always in-band.** Whatever the mode, the caller receives logs, spans and cost on the same connection or in the envelope. A remote node's own OTLP export is its business, never something the caller depends on (§7).

**Telemetry per mode.** WebSocket and SSE carry it *in place*: an SSE body is a sequence of named events (`event: log`, `event: span`, `event: cost.usage`, then `event: result`, `event: envelope`), in order, on the one response. The spec already builds on this (Part C §12.5 is an SSE event catalog); our three signals are three more names. What SSE lacks against WebSocket is only the return path: no in-band cancel or attach.

Sync has no room for that: the body is the answer. The spec always returns the JSON envelope and uses `Accept` to negotiate the *result's* content type (Part C §9.1, Part F §25.2). We add one wrapper switch on top, named so it cannot collide with that:

| Knob | Governs | Values |
|---|---|---|
| `Accept` header | the wrapper, by one dedicated type | `application/url4-envelope+json`: the envelope (Part D §17). Anything else: the bare answer in the negotiated content type, no logs, no telemetry, what `url4 serve` returns today. **Adopted** — Part A §1.4.4's `Envelope` row now states exactly this |
| `meta` param | how much the envelope carries | `none`: result and status. `summary`: counts, latency, cost. `full`: per-source detail, nested child envelopes (Part D §17.3), and a `telemetry` block with logs and spans. The `telemetry` block is ours; per the Hybrid Rule it is present and `null` at `summary` (Part D §17.2.2) |
| `fmt` param | the shape of the answer *content* | `text`, `markdown`, `json` (Part C §9.1); orthogonal, a JSON envelope can wrap a markdown answer |

An envelope answer with no `meta` gets `summary` (the spec's default is `none`, Part C §9.1), so asking for the envelope always buys the cheap insight; `meta=full` is the explicit debug switch. What an endpoint exposes is its decision (Part D §18.4): a production endpoint may answer `meta=full` with the `telemetry` block redacted, but it MUST keep the structure and use `null` or `"redacted"`, never drop fields silently. A development endpoint hands over everything. Same envelope, same evaluator code, different policy.

**Cancel.** The spec calls cancellation a gap and offers two shapes, `DELETE <poll_url>` or a `cancel=<rid>` parameter (Part C §16.2). We take the first: over WebSocket, cancel is in-band; otherwise `DELETE` on the `poll_url`, which the Engine already does. New terminal state `cancelled`; SSE event `request.cancelled`; partial result returned when quorum was already met, as §16.2 asks. Note for Kevin: `status: "cancelled"` is not yet in the status enum of Part D §17.4.

# 7. Telemetry

Three signals, one trace, as in the doctrine skill. What changes is where a one-shot GET puts them.

Part A §1.4.3 now defines **attribution** in the terms this document used — "a per-source influence
score of the impact of each source on the response body, reported in the envelope, shaped by the
request's source weights and budgets" — so what follows sits on a defined word rather than an
implied one.

- **sync**: in the body, only when the caller asked for the envelope (`Accept: application/url4-envelope+json`, §6). `meta` sets the level (`summary` by default, `full` adds logs and spans; Part D §17.2). At `meta=full` a child's envelope nests in `source.envelope` (Part D §17.3). Each endpoint aggregates only what it saw itself (Part D §18.1). A bare `text/plain` answer carries nothing.
- **stream** and **WebSocket**: as events: logs, spans, `cost.usage` (self and subtree), then `result`, then `envelope`. Same names in both.
- **durable**: OTLP export to the trace backend. There is no separate "Enclave" store; the exporter superseded it.
- **What the spec already carries**: 21 SSE event types (Part C §12.5), `meta.total_cost` and `budgets_spent` in the envelope (Part D §17.1.2.8, Part E §24), and an endpoint-local audit log (Part H §34). Our logs, spans and `cost.usage` events are additions on top of that catalog, not replacements; cost stays a separate event, and `total_cost` is its roll-up. Every streamed event with content already MUST carry `content_type` (Part C §12.5), which is what §8 builds on.

This closes doctrine item F4. **Idempotency:** a url4 GET is idempotent in the HTTP sense (RFC 9110 §9.2.2): repeating it has no extra server-side effect. Results need not be identical; Part C §15.1 conflates the two (Appendix A). One real exception the spec lists: a repeat that would exceed a consumed budget fails with `budget_exceeded` (Part C §15.2).

# 8. Typed payloads: an endpoint is a universal inference processor

We have treated an endpoint as text in, text out. That is a habit, not a spec rule. The spec defines a source as "a URI, text, or nested expression" and an intent processor as whatever executes the intent on behalf of the endpoint (Part A §1.4). Nothing says the payload is a string.

![payloads](../diagrams/url4-topology-payloads.svg)

**Proposal.** Every edge in an expression carries a **typed payload**, the way a ComfyUI edge carries an image, a latent or a mask. The type system is the media type: `text/plain`, `image/png`, `audio/wav`, `video/mp4`, `application/json` for embeddings and structured data. Text stays the default and the most common type. No grammar change.

```
(shot=/flux('a red fox at dawn')!'render';accept=png,
 alt=/claude($shot)!'write alt text')!/tts
```

Edges: text → image → text → audio. Three endpoints, three processors, one expression, one trace, one cost roll-up.

**What the spec already gives us**

- `;accept` is a source-level execution annotation (Part B §4.2) that takes a **short alias** (`json`, `csv`, `markdown`, …), never a MIME type, because `/` would read as a relative URI (Part F §25.5). The registry has no image, audio or video rows yet; `png`, `jpeg`, `wav`, `mp4` are proposed in Appendix A. `ct_mismatch` has four values, `fail | ignore | transform_ignore | transform_fail`, default `ignore`, and only applies when `;accept` was declared (Part G §26.3). The spec calls input negotiation out of scope and treats an unusable format as an intent-execution failure, not a source failure (Part F §25.10).
- The spec already has a weighted `image/png` source feeding a text intent (Part I §41.20), and Part G §26.2.3 already says how binary content travels in LLM mode: a data URI, `data:<mediatype>;base64,…`, with raw bytes for RDS intents. The SDK carries a media type on every fetch (`FetchRequest.media_type`) and parses collections by declared type (Part B §5.3.7). The Engine already forks results by size: inline, spilled to a content-addressed artifact, or refused above a hard cap.

**Three rules the spec does not yet give (Part F, §25)**

1. **A source declares its type.** A URI source has the `Content-Type` it was fetched with; absent that, the endpoint infers from the path or sniffs, and falls back to `application/octet-stream` (Part G §26.2). Inline text is `text/plain`. A nested expression has the `result.content_type` its endpoint emitted (Part D §17.1.2.1). `;accept` says what the consumer wants; `ct_mismatch` says what to do when the two differ.
2. **A binary result travels inline when small, by reference when large.** Bare sync: the response body *is* the bytes, with its `Content-Type` (Part F §25.5 permits raw binary outside the envelope). Envelope: `result.content` carries a small payload as a data URI with `result.content_type` set, the spec's own form; a large payload becomes `result.artifact`, an `https://` URL that the next endpoint fetches as plain data (Part B §3.5). The inline threshold is the endpoint's, advertised in its capabilities. Over WebSocket a binary frame carries the bytes; over SSE a large payload always goes by reference. Two cautions from the drafts: this is not truncation, which Part G §26.2.1 forbids; and an artifact URL is a redistribution, so it inherits the source's flow constraints and depth cap (Part H §29.2.2).
3. **A processor advertises what it accepts and emits.** The spec's names are `consumes` and `produces` (Part F §25.4), per processor in the capabilities document. An evaluator can then type-check an expression before it spends anything, which is what the plan question in §10 builds on.

```json
{ "id": "flux",   "type": "internal", "path": "/flux",
  "consumes": ["text/plain"], "produces": ["image/png"], "inline_max_bytes": 262144 },
{ "id": "claude", "type": "internal", "path": "/claude",
  "consumes": ["text/plain", "image/png", "image/jpeg"], "produces": ["text/plain"] },
{ "id": "tts",    "type": "internal", "path": "/tts",
  "consumes": ["text/plain"], "produces": ["audio/wav"] }
```

**Why it matters.** Image generation, text-to-speech, speech-to-text, video evaluation and multimodal ensembles all become ordinary url4 expressions on the same engine, with the same telemetry, the same cost accounting and the same attribution. aigateway stays the provider boundary; it already fronts image and audio providers. The Engine's artifact store is rule 2 as built.

**Open.** A media type for embeddings (`application/json` with a profile, or a vendor type); how attribution weights and `tokens=` budgets apply to non-text sources (Part E is silent; no `bytes=` or `seconds=` budget key exists). Settled by the draft: `fmt` stays a structure hint and a future version MAY retire it in favour of `Accept` (Part F §25.8).

# 9. The Engine as a node

![engine](../diagrams/url4-topology-engine.svg)

| | Today | Target |
|---|---|---|
| App | control plane: `POST /token`, `GET /?q=`, `DELETE`, `/ws` bridged from NATS | a **node**: `/` evaluator endpoint (`GET ?q=` with WebSocket, SSE, sync and async answers, `DELETE`), model endpoints over HTTP, capabilities, `/ws` kept for the product client |
| Runner | k8s Job with one in-process `Url4Node`; model routes are in-process handlers | the evaluator process the `/` endpoint spawns per run |
| Model endpoints | `/anthropic/<model>` reachable only inside the Runner | reachable over HTTP on the node; later each one a standalone function, proxy-mounted |
| aigateway | provider boundary | unchanged |
| Endpoint-to-endpoint | unused SDK code | the normal path |

**Phases.** (1) Node surface on the App: discovery per §5, `GET /?q=` answering SSE and sync (WebSocket via `Upgrade` where the App already has it), `DELETE`. (2) Model endpoints over HTTP. (3) Standalone model functions, proxy-mounted, listed in the capabilities document.

**Serverless posture.** An endpoint is a function; it needs no origin of its own. Only the node needs one. The Runner is already function-shaped. The App is not: it holds an audience count in memory, runs two perpetual tasks, and gates runs on an attached WebSocket. Those belong to the product session, not to the endpoint surface, and stay in the App.

# 10. Deferred, and two questions to move forward

**Authentication as a node concern (question, not a decision).** Keeping node and endpoint distinct makes a safe place for authentication possible, because it gives the credentials exactly one owner. The spec's inter-node auth (Part H §31, "under active development") propagates per-destination encrypted tokens in `ABC-Auth-Token` headers, and Part B §3.5 names a `URL4-Auth-Token` with a target type. The SDK defers all of it: `url4 serve` ships no authn or authz and asks for a reverse proxy in front. The Engine already has the shape we want: the App mints a per-run capability token and the Runner only carries it.

The idea to test: **the node, through its evaluator, is the only party that holds, validates and issues credentials. Endpoints never see a raw credential.** An endpoint receives a node-issued session, a capability scoped to one run (`rid`, request tree, purpose, expiry), and uses it for whatever it needs: reading `@` holdings, calling a sibling endpoint, asking the node to fetch an `s3://` source. Outbound, the node forwards the requestor's per-destination tokens and holds the ones addressed to it (Part H §31.5); inbound, the node validates before any endpoint runs. A standalone serverless function is its own node and validates for itself, so the rule holds at every size. The draft already fixes the token's bindings: `rid`, a timestamp with a window of at most 300 seconds, and the destination identity (Part H §31.2).

Questions to answer before this becomes a section:

1. **Session shape.** Is the endpoint-side session the Engine's JWT topic capability generalised (`sub` = run, `iat` window), or the spec's `URL4-Auth-Token`? One token type, or a node-internal one plus the spec's wire one?
2. **Where the identity lives.** `@alice` access control and consent (Part B §5.6.4) need the requestor's identity at the endpoint. Does the session carry it, or does the endpoint ask the node? Part H §33.1 asks the mirror question, whether identity is per server or per endpoint; "per node" is our answer.
3. **Proxy mounts.** For `/claude → url4://beta.example/claude`, which side validates the requestor, and does beta see our identity or a delegated one (Part H §31.2 encrypts to the destination)?
4. **Token destination.** Part H §31 addresses tokens to a node and matches on authority (§31.5). Is the destination always the node, never an endpoint path?
5. **Agent sessions.** The coordinating node issues the `Session-Id` (Part G §28.5). Is that session bound to the run capability, and does the transcript URL it exposes fall under the same access control?
6. **What an endpoint may do with a session.** Only call back into its own node, or reach other nodes directly with a node-minted, destination-bound token?

Recommendation to explore first: node-issued run capability for endpoints (the Engine's pattern), spec §22 tokens between nodes, identity carried in the capability claims. Attribution, consent and audit (Parts E and H) then attach to the same run identity.

**A dry-run endpoint on the node (narrowed 2026-09-15: the word is settled, the shape is not).**
Deferred in the design session; reopened because three later additions gave it inputs it did not
have: per-endpoint `accepts` and `emits` (§8), per-endpoint `delivery` and `schemes` (§5, §2), and
a node egress that already resolves every target's policy before spending (§11). Today the SDK's
`Graph.validate()` checks syntax only and the Engine's preflight checks routes on one node.

**Kevin has now defined it.** Part A §1.4.3 carries **dry run** — "the process of evaluating an
expression *without* executing the intent, returning only the envelope without a result body" —
which is precisely the semantic proposed below. So the *what* is no longer a question, and this
document stops arguing for it. What Part A does not say is *how you ask for one*, what it costs, or
what happens across nodes; questions 1, 2, 4 and 5 below survive unchanged, and question 3 is now a
question about the spec's own term rather than about ours.

The shape, in full, so the questions have something to bite on. The draft already obliges an endpoint to do most of it: compute the consumer set by static analysis before resolving anything (Part H §29.2.1), be ready to show a source the full call tree (Part H §30.2), and estimate before executing under a hard budget (Part E §24). Steps 3 and 4 of §11 without step 5: parse, resolve mounts, type-check every edge against `accepts`/`emits`, check schemes and delivery modes, consult policy and budgets, and return the request tree with per-source verdicts and an estimated cost. Spend nothing. The answer is the envelope (Part D §17) with `sources[]` and `meta` filled in and no `result`; a refused source carries its error code, so "can this node run my expression?" becomes one call with a structured no.

Questions:

1. **Shape.** `Prefer: dry-run` on the ordinary GET (the RFC 7240 pattern we already use for `respond-async`), a `dry_run` protocol parameter beside `q=`, or a separate path? The header keeps the address identical for dry run and run, which suits caching and audit. Part A §1.4.3 defines the operation and says nothing about how it is requested, so this is the open half.
2. **Does a plan spend?** Policy-registry consults and budget reservations are real calls. Is a plan free by definition, with `meta.total_cost` as an estimate from `pricing_version`, or may it reserve?
3. **Is the result an artifact?** A dry-run id returned as a handle, so a later run can say "execute this" and skip re-evaluating. That ties to idempotency (§7) and to the token binding of §11. Note the spec's definition returns "only the envelope without a result body", which does not by itself give the caller anything to hold on to.
4. **Federation.** For a remote subtree, does the node forward the dry run to the other node and merge its answer, or answer only from that node's capabilities document? The first is exact and costs a round trip; the second is instant and approximate. Part A §1.4.3 is silent, and a dry run that silently stops at the first remote edge is worse than one that says it did.
5. **Ownership.** The Engine's preflight admission (OME-880) becomes this endpoint's single-node case. Does the SDK gain `url4 dry-run`, calling the same thing?

Recommendation to explore first: `Prefer: dry-run` on the same GET, envelope-only answer, cacheable like any GET, forwarded to remote nodes that advertise it and approximated from capabilities where they do not. The word `plan` is retired from this document — the spec's word is **dry run**.

**Deferred**


- **Swarm** as a protocol noun. Would need membership and trust rules that belong to the unwritten governance parts.
- **Endpoint grades** (processor-only vs evaluator). Rejected: every endpoint evaluates.

# 11. Networking sketch: endpoints act on behalf of the node

A brainstorm, not a decision. It answers one question from §10 concretely: **how does an endpoint make an outbound request without holding a credential?**

![auth network](../diagrams/url4-topology-auth-network.svg)

**Three candidate mechanisms**

| | A · Node egress | B · Delegated token | C · Sidecar |
|---|---|---|---|
| Who opens the outbound connection | the node | the endpoint, with a node-minted token | a per-endpoint proxy process |
| Where credentials live | node only; it forwards the requestor's destination-encrypted tokens and holds those addressed to it (Part H §31.5) | the requestor's destination-bound token (Part H §31.2) carried by the endpoint | sidecar only |
| Policy, disclosure, cache, budgets, rate limits | one place: the node's egress (Part H §29.2.1, §16.3, §20, §31) | at mint time on the node; enforcement split | in the sidecar |
| Serverless endpoint | nothing to configure | needs network egress and key handling per function | platform-dependent |
| Cost | an extra hop; large payloads through the node, or by reference (§8) | none | one process per endpoint |
| What it is today | how the SDK already works: an in-process endpoint fetches through the node's `IOLayer` | the Engine's per-run JWT, generalised | not built |

**Recommendation to explore first: A for endpoints, B between nodes.** An endpoint never talks to the network. It talks to its node. The node talks to other nodes with the spec's tokens. A standalone serverless function is its own node, so the same two rules cover it: the parent node reaches it node-to-node (B), and inside it the function is an endpoint using its own node's egress (A). C is a deployment shape of A, not a third protocol.

**The flow the diagram draws**

1. The requestor calls Node A with its `URL4-Auth-Token` (Part B §3.5). Node A's auth gate validates it.
2. The gate mints a **run session S**: `rid`, the request tree, purpose, expiry, the requestor's identity. Every endpoint in the run receives S and nothing else. In-process endpoints get it as an object; command mounts get it in the environment.
3. An endpoint that needs `url4://beta.example/gemini` or `s3://brand-assets/logo.png` hands the target and S to the node's **egress**. It does not open a connection.
4. Egress does the node's work once, in one place: consults the policy registry and discloses consumers (Part H §29.2.1), checks budgets and rate limits (Part E §24, Part C §14), serves from cache when allowed, keyed by requestor identity and consumer set so a shared cache is not a policy bypass (Part H §29.3), and either fetches with the node's own credentials (`s3://`, `pg://`) or forwards the requestor's token **T(B)**, encrypted to Node B, on the sub-request (Part H §31.2, §31.3). The node mints nothing for other nodes: the spec has the *originator* encrypt every token so that intermediaries cannot read or replace them. What the node mints is internal: the run session S.
5. Node B's gate validates T(B), mints its own session S′, and runs `/gemini`. Its result and envelope come back on the same connection.
6. A proxy-mounted standalone function is Node C: same as step 5 with T(C).
7. Node A's telemetry relay merges what came back into the run's one trace (doctrine F1).

**What is new on the wire, and what is not**

- Requestor to node, and node to node: nothing new. The spec's tokens and `traceparent`.
- Endpoint to node: **nothing on the wire for in-process endpoints**; it is a function call through the node's `IOLayer`, which is what `Url4Node` does today. For out-of-process endpoints (command mounts, containers) an explicit node endpoint is needed, something like `GET /.node/egress?u=<absolute URI>` with `URL4-Session: S`. Its path and shape are open.

**Open questions this sketch adds**

- Does egress return bytes to the endpoint, or a reference (§8)? For large sources, by reference keeps the node out of the data path.
- The spec binds T(B) to `rid`, a timestamp (≤ 300 s) and the destination (Part H §31.2). Does the node-internal session S need the same three bindings?
- Delegated credentials only target `abc_node` or `http_source` (Part H §31.4). For `s3://` and `pg://` the node's own credentials are the only path; should `target_type` widen, or is node-credential-only the rule?
- Can an endpoint ever be granted direct egress (mechanism B at endpoint level)? Probably only for trusted local mounts, and only by node policy.
- Where does the egress endpoint live for command mounts: a Unix socket, a loopback port, or the node's public origin with S as the credential?

# 12. Alignment with the spec (2026-09-08 drafts, 2026-09-15 Part A)

The `url4-refactor` branch of `OpenMined/screamingface-design` carries draft Parts C–I (cut 2026-04-28 from the v0.4 text, not yet reviewed) and a v0.4 monolith that renumbers everything after §20. This document was first written from the v0.2 monolith. Every citation has been re-anchored to the Part numbering. The table records what the drafts changed, and how this document resolved it.

| Topic | We wrote | The draft says | Resolution |
|---|---|---|---|
| Capabilities document | schema unwritten | Part G §27.2 specifies it: one `node`, `collections`, `intent_processors`, `processor_policy`, `mode_support` | §5 rewritten as spec shape + marked additions (`path`, `delivery`, `schemes`, `default_processor`) |
| Discovery mechanisms | `.well-known` vs OPTIONS | `.well-known/abc-capabilities` SHOULD, `Capabilities` header MAY (Part G §27.1); no OPTIONS | header added as mechanism C; recommendation moved to A + C |
| Sub-paths | `/name` is an endpoint | sub-paths are collections (Part G §27.4); processors are addressed by `id` | proposed `intent_processors[].path`; vocabulary realigned to the spec's Node/Endpoint (2026-09-08) |
| Mounts vs delegation | `proxy` forwards a sub-request | `processor=` delegation, five forms, `abc_delegate` receives materialised sources (Part G §27.3) | mounts mapped onto processor types (§4); no new mechanism |
| Async | `Prefer: respond-async`, `Location` handle | `delivery=async`; 202 body with `poll_url` (Part C §9.1, §12.5) | adopted; `Prefer` and `Location` become aliases |
| Wrapper switch | `Accept: application/json` = envelope | `Accept` negotiates the result's type; envelope is always JSON (Part C §9.1, Part F §25.2) | dedicated `application/url4-envelope+json` (§6) |
| Ladder | WS → SSE → sync, ours | two edges only (Part C §11.4); degrade-not-fail is a rule (Part C §10.2) | kept as delta, anchored in §10.2 |
| `;accept` values | MIME types | short aliases only; registry has no image/audio/video rows (Part F §25.5) | examples fixed; alias rows proposed |
| Binary results | `result.media_type` | `result.content_type`; data URI in LLM mode, raw for RDS (Part G §26.2.3) | adopted; `result.artifact` stays a delta |
| `ct_mismatch` | fail / convert / pass | four values, default `ignore`, only with `;accept` (Part G §26.3) | adopted |
| Telemetry events, cost event | ours | 21 SSE types (Part C §12.5); `total_cost` scalar, `budgets_spent` (Part D §17, Part E §24) | kept as additions, roll-up mapped to `total_cost` |
| Statelessness | every endpoint keeps nothing | the coordinating node owns an agent session and transcript (Part G §28) | §3: state on the node, endpoints stay stateless |
| Node-minted tokens | egress mints T(B) | originator encrypts every token; intermediaries forward or hold (Part H §31.2, §31.5) | §11 corrected: node forwards, mints only its internal session |
| Non-HTTP credentials | node's own | `target_type` is `abc_node \| http_source` only (Part H §31.4) | stated; question for Kevin |
| Artifacts and proxies | free to forward | flow constraints and redistribution depth (Part H §29.2.2) | cautions added to §4 and §8 |
| Root `/` | ours | unaddressed; examples use bare `abc://node?q=` (Part I §41.27); `v` param outranks the path (Part D §19.4) | kept; tensions listed in §2 |
| Cancel | `DELETE` on `Location` | `DELETE <poll_url>` or `cancel=<rid>` (Part C §16.2); `cancelled` not in the status enum (Part D §17.4) | `DELETE <poll_url>`; enum gap flagged |
| Naming | `url4://`, `URL4-*` | C–I still `abc://`, `ABC-*`; consolidation is open question 19 (Part I §43) | kept `url4`; assumption stated in §1 |

Confirmed by the drafts without change: the three trust relationships and token bindings (Part H §31), the strict request tree (Part H §29.1), `/name` ensembles on one node (Part I §41.9), a weighted image source (Part I §41.20), consumer disclosure before resolution (Part H §29.2.1), the idempotency wording we dispute (Part C §15.1), and every element of our cancel shape (Part C §16.2).

## Kevin's Part A §1.4 refresh (2026-09-15, PR #19 `2a939bff`, draft)

A week after the round above, Kevin rewrote Part A §1.4 in response to it. The flat 26-row
terminology table became five sub-tables — **1.4.1 Grammar**, **1.4.2 Network**, **1.4.3 Expression
Processing**, **1.4.4 Transport**, **1.4.5 General** — and most of Appendix D was absorbed into the
spec. Where his text differs from ours, his wins; the table records what we changed in response.

| Topic | We wrote | Part A §1.4 now says | Resolution here |
|---|---|---|---|
| `Mount` | ours: `local`/`command`/`proxy`, "not defined" in the spec | §1.4.3, **adopted verbatim**, alongside the processor types | §1 and §4 cite the spec; delta 1 retired; the stray "N4" annotation becomes delta 15 |
| `Evaluator`, `Evaluation` | ours (§1) | §1.4.3, adopted and **widened**: the evaluator may or may not also be the intent processor | §1 adopts the wider reading |
| `Dry run` | our open question, called "plan" (§10) | §1.4.3, **defined**: evaluate without executing; envelope, no result body | §10 narrowed to shape, cost, federation; "plan" retired as a word |
| Response ladder | ours, WS → SSE → sync | §1.4.4, **adopted**, marked "SPEC SECTION NEEDS UPDATING" | §6 rewritten as adopted; delta 4 becomes "close the Part C gap" |
| `websocket` delivery | our fourth rung, an addition | §1.4.4, a fourth `delivery` value beside `sync`/`stream`/`async` | §6; settles Part I question 26 for answers |
| Envelope switch | ours: `application/url4-envelope+json` | §1.4.4, **adopted**, with the `meta` parameter | §6 marked adopted; delta 7 retired |
| `Scheme adapter` | ours (§2) | §1.4.3, **adopted**, "generalizes Part B §3.5" | §2 cites the spec; says "host's credentials" → delta 13 |
| `Degradation`, `Flow constraints`, `Attribution`, `Run handle`, `Collection`, `Holdings` | ours or implied | §1.4.3–§1.4.5, all now defined | Appendix D becomes a crosswalk rather than a parallel glossary |
| `Request Tree` | strict tree, never a graph (Part H §29.1) | §1.4.3: "the full set of all sources and targets… an **evaluator may expand the tree**" — strictness dropped | §1 flags the change; delta 14 asks whether it is deliberate. §13's peer-to-peer question depends on the answer |
| "Host" | deleted from this document 2026-09-08 | §1.4.2 adds `Host system` (a machine); §1.4.4 and the Scheme adapter row then use "host" to mean *node* | §1 keeps "host" out; delta 13 proposes `s/host/node/` in those four rows |
| Capabilities path | `/.well-known/url4-capabilities` | §1.4.5 now writes exactly that, where Part G still says `abc-capabilities` | §5: question 19 resolving in passing |
| `Self-reference`, `Identity-reference` | two rows in the old §1.4 | dropped as rows; folded into `Holdings` | delta 16 asks for confirmation; `Holdings` also carries `Collection`'s anchors |
| Branch | Parts C–I live on `url4-refactor` | PR #19 targets **`main`**, where C–I are stubs, but its rows cite Part C §10.2, Part G §27.3, Part H §31 | delta 17: those anchors do not resolve on the branch the PR merges into |

**Status of that PR.** It is a **draft**, one commit, opened 2026-09-15, no reviews. Everything above
is pinned to `2a939bff` and may move. Appendix B carries the re-review item.

# 13. url4 as a network protocol: submit, not call (question)

Raised 2026-09-08. Today a url4 expression is *called*: one requester sends a GET to one node and waits. The question is whether the same expression can be *submitted* to a network that resolves it over time, the way a torrent is fetched or a transaction is mined: every requester is a node, capable nodes claim the endpoints an expression names, and the result finds its way back.

**What the spec already gives such a network**

- **The expression is the address, and it can be content-addressed.** `urn:sha256:` is the accepted form for content addressing (Part I §43, question 1). The canonical rendering of an expression hashes to a stable work id.
- **Submit and collect are already decoupled.** `delivery=async` returns a handle and the result arrives later (Part C §11.3); `resume=<rid>` continues from the last known state (Part C §9.1); results carry `result_version` and `is_final`, so an answer may improve over time (Part C §12.5).
- **Redundant evaluation has a vocabulary.** Quorum and triggers already say how many of N must succeed before an answer counts (Part C §12). Run the same endpoint on several nodes and quorum becomes agreement.
- **Discovery can be a record.** A node's capabilities document (Part G §27.2) is a self-description that can live in a distributed table as well as at `/.well-known`.
- **Every requester is a node.** A local SDK process that evaluates is a node in this document already (§4).
- **Attribution is an incentive model.** Attribution scores and the still-undefined settlement (Part E, Part I §37) are where a Bitcoin-like reward would attach.

**What is genuinely new**

- **Claiming work.** Which node evaluates a submitted expression, and how two nodes avoid doing the same work, or are made to on purpose.
- **Verifying results without determinism.** A torrent piece is verified by hash; an LLM result cannot be. Candidates: agreement across redundant evaluations (quorum), attested execution (Part I §38), reputation, or accepting unverifiable results for some intents.
- **Consent in an open swarm.** A source may name its permitted consumers and cap redistribution depth (Part H §29.2.2); an anonymous claimer is neither known nor permitted. Either sources opt into open resolution, or the swarm is a closed membership.
- **The context travels.** Submitting an expression means its resolved sources travel to whichever node claims it, the opposite of the "code to the data" posture of RDS mode (Part A §1.1).
- **Liveness and economics.** Who guarantees an expression is ever resolved, and who pays. Part I §37 is TBD.

**A sketch to argue with.** The requester canonicalises the expression and publishes `urn:sha256:<hash>` with the expression to the network. Nodes whose capabilities cover an endpoint the expression names claim that endpoint and evaluate it against their own holdings and credentials, as §11 describes for one node. Each returns a signed envelope keyed by the hash. The requester's `poll_url` becomes a lookup of that key; quorum decides when the answer is good enough; `is_final` closes it. Nothing in the grammar changes; the transport changes from point-to-point to publish-and-claim.

**Questions**

1. Is this a fourth delivery mode (`delivery=network`) or a different transport beneath the same three?
2. Which verification candidate is acceptable for which kind of intent?
3. Can consent and flow constraints be expressed for an open set of claimers, or is membership required?
4. Does the requester's evaluator keep fan-out and reduce, with the network resolving only leaf endpoints? That keeps §11's egress intact and makes the swarm a resolver, not an orchestrator.

# Appendix A — proposed spec deltas for Kevin

Each item names the anchor and the change. All are proposals. Re-triaged 2026-09-15 against Part A
§1.4 at PR #19 (`2a939bff`, draft).

## Landed in PR #19

Kept as the record of what was proposed and taken. Nothing is asked here.

| # | Was | Where it landed |
|---|---|---|
| 1 | **Part A §1.4 — endpoint kinds.** Name the binding kinds `local \| command \| proxy`. | §1.4.3 `Mount`, **verbatim**. Superseded in one respect: no rename was needed — Node and Endpoint stayed, and §1.4.2 added `Node address` and `Endpoint path` instead. |
| 4 | **Part C §10.2, §11.4 — ladder and floor.** WebSocket → SSE → sync in one round trip; sync the only MUST; answering below the ask is a reported degradation. | §1.4.4 `Response ladder` and `Degradation`, plus `websocket` as a fourth `delivery` value. **Still open below** — Part C itself is unchanged, as Kevin's own row notes. |
| 7 | **Part D §17 — envelope for sync callers.** `application/url4-envelope+json` selects the envelope; `meta` sets the depth. | §1.4.4 `Envelope`. The `telemetry` block and the `meta=summary` default are not stated there; delta 12 still stands. |
| 9 | **Part B §3.5 — other schemes.** Any non-HTTP scheme is a read through a node-mounted adapter, advertised in capabilities. | §1.4.3 `Scheme adapter`, "generalizes Part B §3.5". Says "host's own credentials"; see delta 13. |
| 10 | **Part G §27.2 — capabilities document.** Add `delivery`, `schemes`; `url4_*` naming. | §1.4.5 `Capabilities document` now lists delivery modes and schemes and writes `/.well-known/url4-capabilities`. `intent_processors[].path`, `inline_max_bytes` and `default_processor` are **still open** below. |

## Still open

- **2. Part B §3.1.1, Part D §19 — root.** `url4://node` ≡ `url4://node/`; `/` is the node's default endpoint at the current version; `/v1` is a version alias. Your own examples already do this (Part I §41.27). Also resolve §19.1 (path primary) against §19.4 (`v` outranks path). Untouched by PR #19.
- **3. Part C §11.2 — bindings.** `delivery=stream` is SSE on the same GET, requested with `Accept: text/event-stream` (§11.2 names SSE but no media type). Part A §1.4.4 now says `stream` is "SSE events on the same GET", so this is a Part C catch-up.
- **4. Part C §10.2, §11.4 — make Part C match Part A.** §1.4.4 now carries the four delivery modes and the full ladder; Part C §11 still describes three modes and Part C §11.4 two degradation edges. Your own §1.4.4 row is annotated *SPEC SECTION NEEDS UPDATING*. Add a `delivery` list per processor to the capabilities document at the same time.
- **5. Part C §15.1 — idempotency.** Replace "the protocol does not guarantee idempotency" with: GET is idempotent per RFC 9110 §9.2.2; results are not guaranteed deterministic. §15.2's `budget_exceeded` row stays as the stated exception.
- **6. Part C §16 — cancellation.** Take your first option: `DELETE <poll_url>`; drop `cancel=<rid>`. Terminal state `cancelled`; SSE event `request.cancelled`; propagates to in-flight children; partial result when quorum was met. Add `cancelled` to the status enum in Part D §17.4 and to the state machine in Part C §13.4.
- **8. Part F §25, Part G §26 — typed payloads.** Add image, audio and video rows with aliases (`png`, `jpeg`, `wav`, `mp4`) to the §25.5 registry; extend §26.2.3's data-URI rule to results (`result.content` + `result.content_type`); add `result.artifact` for by-reference results above an endpoint-declared `inline_max_bytes`, subject to §29.2.2 flow constraints. Part E: say how weights and budgets apply to non-text sources. Slot §41.24 is free for a multimodal example.
- **11. Part H §31.4 — credential targets.** Either widen `target_type` beyond `abc_node | http_source`, or state that non-HTTP schemes are resolved with the node's own credentials only (§2). §1.4.3's `Scheme adapter` now assumes the latter without saying so.
- **12. Part D §17.2.2, §20 — additions must respect the Hybrid Rule and `propagated`.** Our `telemetry` and `session` blocks are present-and-null at `summary`; unknown fields pass through unaggregated.

## New, raised by PR #19

- **13. Part A §1.4.2, §1.4.4 — host vs node.** `Host system` is welcome in §1.4.2 as a deployment word: a machine supporting one or more nodes. But §1.4.4 `Delivery mode` ("the negotiated method by which a **host** responds") and `Response ladder` ("the mechanism by which a **host** responds with the richest delivery mode"), and the §1.4.3 `Scheme adapter` row ("using the **host's** own credentials"), all use "host" where the actor is the **node**. It is the node that negotiates delivery, picks a rung and holds scheme credentials; a host system negotiates nothing, and on a machine running two nodes the sentence has no referent. Proposal: `s/host/node/` in those rows and keep `Host system` to §1.4.2 alone.
- **14. Part A §1.4.3 — `Request Tree` lost its strictness.** The new row reads "the full set of all **sources** and **targets** defined in an **expression**. An **evaluator** may expand the tree during **source** **resolution** and sub-expression **evaluation**." Part H §29.1 says the request tree is strictly a tree, never a graph, and this document relies on that in §3, §7 and §13. Is the relaxation deliberate — is a node allowed to converge two branches onto one sub-expression — or is "expand" only meant to say the tree is discovered lazily? The answer decides whether §13's publish-and-claim model is a transport change or a model change.
- **15. Part A §1.4.3 — a doctrine reference leaked into the spec.** The `Mount` row annotates `command` as "(subprocess, **N4**)". N4 is an item in our internal doctrine skill (`.claude/skills/url4-engine/SKILL.md`), not a spec anchor; a reader of Part A cannot resolve it. Drop it, or replace it with Part H §36, which is the rule that actually governs command mounts.
- **16. Part A §1.4.1 — `Holdings` anchors, and two dropped rows.** `Holdings` carries `Part B §5.3, Part G §27.4`, which are `Collection`'s anchors; holdings and the `@` token are Part B §5.6. Separately, `Self-reference` and `Identity-reference` were rows in the old §1.4 and are now gone, apparently folded into `Holdings` — please confirm that is intended, because `@alice` carries an access-control and consent rule (Part B §5.6.4) that the single `Holdings` line does not state.
- **17. Branch and anchors.** PR #19 targets `main`, where Parts C–I are "Not yet written" stubs. Its new rows nonetheless cite Part C §10.2, Part C §11, Part C §12.5, Part G §27.3 and Part H §31 — anchors that resolve only on `url4-refactor`. Either the drafts merge first, or Part A §1.4 ships with references a reader of `main` cannot follow.
- **18. Part A §1.4 — typos and markup.** `Inter-host tone` should be `Inter-host token` (and, per delta 13, *inter-node token*). `Request identifer` ×2 → `identifier`. `Extention` → *extension*. Unclosed bold in "nested **Expression\*" (§1.4.1 `Source`) and "one or more **nodes\*" (§1.4.2 `Host system`). "one **ore** more" (§1.4.3 `Resolution`). "without executing **then** intent" (§1.4.3 `Dry run`). "advertising **a its** collections" (§1.4.5 `Capabilities document`). A stray `.` before "Generalizes" in `Scheme adapter`.

# Appendix B — follow-up work items

To file after owner review, one per landing.

| Landing | Item |
|---|---|
| screamingface-engine | Node surface phase 1: discovery per §5, `GET /?q=` with SSE, `DELETE` on the run handle |
| screamingface-engine | Model endpoints reachable over HTTP (phase 2); standalone model functions, proxy-mounted (phase 3) |
| screamingface-engine | Rename the `URL4-Capability` JWT header to avoid the "capabilities" collision |
| url4-sdk | Delivery negotiation in `Url4Node.asgi()`: `Upgrade`/`Accept` handling, `application/url4-envelope+json`, SSE body, `delivery=async` with `poll_url`, optional WebSocket answer; evaluator-side single-request ladder in `HttpIOLayer` |
| url4-sdk | Capabilities document and/or OPTIONS responder, after the §5 decision; advertise `delivery` per endpoint |
| url4-sdk | `url4 serve` default path `/`; `Client` default path `/`; `/v1` alias |
| url4-sdk | `proxy` mount kind in `url4.toml` |
| url4-sdk | Scheme adapters (`s3://`, `pg://`, `sqlite://`, …) as `IOLayer` adapters registered by scheme; `[schemes]` in `url4.toml`; `schemes` in capabilities |
| url4-sdk | Typed payloads: bytes + media type through `IOLayer`/`FetchRequest`, `;accept`/`ct_mismatch` enforcement, `result.artifact` by-reference fetch |
| screamingface-engine | Non-text processors over aigateway (image, speech); artifact store as the by-reference path; `accepts`/`emits` in capabilities |
| url4-sdk | `Url4Node` → node naming retrofit with a deprecation alias |
| repo | Doctrine skill synced in this unit (T1, N1, F2, F4, term table) |
| repo | Re-review this document when PR #19 leaves draft: every "adopted" claim here is pinned to `2a939bff` and the PR has had no review yet |
| Kevin | Review Appendix A — deltas 2, 3, 4, 5, 6, 8, 11, 12 still open; 13–18 raised by PR #19 itself |

# Appendix C — where the spec lives

- Parts A and B, v0.5 DRAFT (2026-07-10): `secondbrain/kevin-mcdonough/docs/adrs/URL4-Spec-A.md`, `URL4-Spec-B.md`.
- **Part A §1.4 as cited throughout this document** is not that file but the version in `OpenMined/screamingface-design` **PR #19** (`url4/terminology-refresh`, commit `2a939bff`, opened 2026-09-15), which is a **draft against `main`** and has had no review. Every "§1.4.x" anchor here resolves there and nowhere else yet.
- Parts C–I: draft markdown on the **`url4-refactor` branch** of `OpenMined/screamingface-design`, `kevin-mcdonough/docs/adrs/refactor/URL4-Spec-{C…I}.md`, cut 2026-04-28 from the v0.4 text, not yet reviewed, never merged to `main` (where the site shows "Not yet written" stubs). Cited here as "Part X §N". The same branch holds the v0.4 monolith (commit `f28608a`); the v0.2 monolith this document was first written from is `8a052dc`, and its numbering diverges from §21 on.
- Public docs: `public-docs/src/pages/learn/Url4Page.vue`. They use "fusion" and "typed DAG"; the spec uses neither.
- Doctrine: `.claude/skills/url4-engine/SKILL.md`, updated with this document.

# Appendix D — Vocabulary crosswalk

Until 2026-09-15 this appendix was a glossary of its own, written because Part A §1.4 was a flat
26-row table that left most of this document's vocabulary undefined. PR #19 changed that: §1.4 is
now five sub-tables and **most of these terms are the spec's own**. A second glossary would only
drift from it, so what remains is the crosswalk — for each term, where it lives in Part A §1.4 as of
`2a939bff`, and whether anything is still owed.

Read the definitions in the spec. Read this to know which of them came from here, which changed on
the way, and which are still only ours.

**Status key.** *adopted* — in Part A §1.4, saying what we meant · *changed* — adopted, but the
meaning moved; see the delta · *spec's own* — the spec's word before this document existed ·
*ours* — not in the spec; this document is the only definition.

## Adopted from this document

| Term | Part A §1.4 | Status | Still owed |
|---|---|---|---|
| **Mount** | §1.4.3 | adopted | The row annotates `command` with "N4", our doctrine numbering (delta 15). |
| **Evaluator**, **Evaluation** | §1.4.3 | adopted, widened | The evaluator "may or may not" also be the intent processor — wider than §1's reading, and we take the wider one. |
| **Dry run** | §1.4.3 | adopted | The operation is defined; how you ask for one, what it costs and how it federates are open (§10). |
| **Response ladder** | §1.4.4 | adopted | Part C §11.4 still lists two edges. Kevin's own row says *SPEC SECTION NEEDS UPDATING* (delta 4). |
| **Degradation** | §1.4.4 | adopted | — |
| **Scheme adapter** | §1.4.3 | adopted | Says "the **host's** own credentials"; it is the node's (delta 13). |
| **Envelope** | §1.4.4 | adopted | Carries the `Accept: application/url4-envelope+json` switch and `meta`. The `telemetry` block and the `meta=summary` default are still deltas (12). |
| **Run handle**, `poll_url` | §1.4.4 | adopted | — |
| **Flow constraints** | §1.4.5 | adopted | — |
| **Attribution** | §1.4.3 | adopted | — |
| **Delivery mode** | §1.4.4 | adopted | `websocket` is now the fourth value; `sync` the only MUST. |
| **Request tree** | §1.4.3 | **changed** | Strictness is gone: "an evaluator may expand the tree". Part H §29.1 says strictly a tree. §3, §7 and §13 depend on which is true (delta 14). |
| **Inter-node token** | §1.4.4 | **changed** | Appears as "Inter-host **tone**" — a typo, and "host" for "node" (deltas 13, 18). |

## The spec's own, before this document

| Term | Part A §1.4 | Note |
|---|---|---|
| **Expression**, **Source**, **Intent** | §1.4.1 | `Intent` is newly spelled out: a prompt, a code pointer, a URI, or an expression that must resolve to one of the first two. |
| **Collection**, **Holdings** | §1.4.1 | `Holdings` is new as a row and folds in the old `Self-reference` / `Identity-reference`; its anchors are `Collection`'s (delta 16). |
| **Broadcast**, **Expansion** | §1.4.1 | Unchanged. |
| **Node**, **Endpoint** | §1.4.2 | `Endpoint` is now *an interface*, named by an **endpoint path** — see below. |
| **Requestor**, **Target** | §1.4.3 | `Target` is now explicitly node address + endpoint path. |
| **Intent processor** | §1.4.3 | Unchanged in substance. |
| **Resolution**, **Execution** | §1.4.3 | Unchanged. |
| **Terminal state**, **Quorum**, **Trigger** | §1.4.3 | `Trigger` now says *intermediate* result. |
| **Agent session** | §1.4.3 | The basis for the statelessness carve-out in §3. |
| **Policy registry**, **Data owner**, **Purpose**, **Jurisdiction**, **Settlement**, **Attestation** | §1.4.5 | Governance vocabulary; unchanged. |
| **URL4-aware**, **Non-URL4 source** | §1.4.5 | Unchanged. |
| **Capabilities document** | §1.4.5 | Now written `/.well-known/url4-capabilities` and naming the `Capabilities` header (§5). |
| **Idempotent** | Part C §15 | Not in §1.4. Wording still disputed (delta 5). |

## New in PR #19, adopted here

| Term | Part A §1.4 | How this document uses it |
|---|---|---|
| **Node address** | §1.4.2 | §2: scheme + RFC 3986 authority. |
| **Endpoint path** | §1.4.2 | §1, §2, §3: `/claude` is the path; the endpoint is the interface it names. |
| **Host system** | §1.4.2 | **Not used.** A machine supporting one or more nodes is a fine deployment word and has no protocol role here; §1 and delta 13 explain why "host" stays out. |

## Still only ours

Nothing in Part A §1.4 defines these. Each is a live proposal with a delta behind it.

| Term | Definition | Where |
|---|---|---|
| **Typed payload** | Every edge carries a value named by its media type; text is the default. Sources declare by `Content-Type`, results by `result.content_type`. | §8, delta 8 |
| **Artifact** | A large result returned as an `https://` URL the next endpoint fetches as data, above an endpoint-declared `inline_max_bytes`; inherits flow constraints. | §8, delta 8 |
| **Run session** | A node-issued capability scoped to one run (`rid`, tree, purpose, expiry, identity) that endpoints carry instead of credentials. | §10, §11 |
| **Egress** | The node component that performs every outbound request for its endpoints: policy, disclosure, cache, budgets, credentials, token forwarding. | §11 |
| **Telemetry signals** | Logs, spans (tokens live here), and `cost.usage` events (money lives here). In-band in every mode; OTLP is the durable copy. | §7, delta 7 |
| **OPTIONS discovery** | One answer per endpoint, mechanism B of §5. Appears nowhere in the spec, and PR #19 did not add it. | §5 |
