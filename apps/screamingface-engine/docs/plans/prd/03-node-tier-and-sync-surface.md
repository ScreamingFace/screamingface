# Unit 3 — Node tier, sync surface, and local mount

**Depends on:** units 1 and 2.
**Behaviour change:** a new public HTTP surface and a new Deployment.
**Reviewable as:** a new tier plus its ingress path.

## 1. User story

> As an API caller, I want to `GET` a url4 mount path and receive the model's answer
> in the response, so that a light single-model call does not require minting a
> token, opening a WebSocket and waiting on a queued run.

> As an operator, I want that traffic served by a tier I can scale and restart
> independently of the control plane, so that a slow or crashing sync call cannot
> take down the WebSocket relays that in-flight ensemble runs depend on.

## 2. What changes

### 2.1 A third CLI mode

`screamingface-engine node` builds the world once and serves `node.asgi()` wrapped
in url4's own admission and timeout middleware (`cli/_serve.py:265-305`). In effect
it is `url4 serve` with the engine's world.

| Setting | Value | Source |
|---|---|---|
| Per-request timeout | 30 s → `504` | `ans:Q5` |
| Max in-flight | 2 × worker count → `503` + `Retry-After` | `ans:Q5` |
| `eval_path` | `/v1`, url4's default, unchanged | `ans:Q3` |
| `allow_outbound` | `false` on this tier | `[proposed]` |
| aigateway timeout | 28 s, overriding the 600 s default | `[proposed]`, see `contracts.md` |

The tier is stateless. It holds one world, one shared `httpx.AsyncClient` to
aigateway, and nothing per caller.

### 2.2 The App forwarder

The App derives its forwardable mount set from the same `world` module the node uses
(F1), at startup, with no network call. A request whose path is in that set is
forwarded verbatim to the node Service. A request whose path is not is a `404` at the
App and never reaches the node. [`ans:Q6`, `contracts.md` C2]

The App keeps owning identity: it strips any client-supplied `X-User-Email` and sets
the edge-verified value before forwarding.

### 2.3 Local mode

`serve --local` mounts the same `node.asgi()` into the FastAPI app, registered after
every literal route so precedence resolves collisions (D3). The in-process run path
uses that same node as its `IOLayer`. No forwarder, no second process.

### 2.4 Large results

A response body over 512 KiB is written to the artifact store and the caller receives
`303 See Other` with `Location: /artifacts/{id}`. Above `result_hard_cap_bytes` the
request fails with `413`. [`ans:Q10`]

This makes `GET /artifacts/{id}` reachable by callers who hold no capability token,
so the `303` carries a **short-lived signed URL** (OQ-3.2 decision, option b):
the node signs artifact id + expiry with a shared HMAC key, the App verifies, and
the bare route stays token-only for everyone else. See `contracts.md` C6.

### 2.5 Deployment

New Helm resources: a `Deployment` for the tier, a `Service`, a `NetworkPolicy`
admitting only the App, a `PodDisruptionBudget`, probes, a metrics port, the S3
credentials Secret the spill path needs, and the **artifact-signing-key Secret
shared with the App** (the node signs the `303`, the App verifies — OQ-3.2).

## 3. Acceptance criteria

### Happy path

#### AC1 — a mount call returns the model's answer
> **Given** a deployed engine and a declared model mount
> **When** a caller sends `GET /anthropic/claude-haiku-4-5?q=('')!'Reply with exactly: PARIS'`
>   with an edge-verified identity
> **Then** the response is `200`, `text/plain; charset=utf-8`, body `PARIS`
> **And** the aigateway call carried that caller's identity and a `traceparent`.

#### AC2 — the ensemble path is untouched
> **Given** the existing token → WebSocket → `GET /?q=` flow
> **When** unit 3 is deployed
> **Then** every existing conformance test passes unchanged.

### Identity and trust

#### AC3 — concurrent callers never cross (concurrency)
> **Given** the node tier serving two concurrent requests from different identities
> **When** both reach aigateway
> **Then** each outbound call carries only its own caller's identity, profile, seed
>   and cache policy.

#### AC4 — a client cannot assert its own identity (security)
> **Given** a caller sending `X-User-Email: someone-else@example.com`
> **When** the App forwards the request
> **Then** the forwarded header carries the edge-verified value, not the client's
> **And** when no verified identity is present, the request is rejected rather than
>   forwarded anonymously.

#### AC5 — the node tier is unreachable except from the App (security)
> **Given** the deployed NetworkPolicy
> **When** any pod other than the App attempts to reach the node Service
> **Then** the connection is refused.

Without this, anything in the cluster can set `X-User-Email` freely and impersonate
any caller. The policy is a correctness requirement, not hardening. [implied]

### Failure paths

#### AC6 — a slow call times out cleanly
> **Given** a mount whose downstream call exceeds 30 s
> **When** the budget expires
> **Then** the caller receives `504`
> **And** the body names the ensemble path as the route for long work
> **And** the in-flight aigateway request is cancelled rather than left running.

The cancellation clause matters: an abandoned call still consumes a slot and still
bills. [`ans:Q5`]

#### AC7 — an overloaded tier sheds load
> **Given** in-flight requests at the cap
> **When** another arrives
> **Then** url4's `503` with `Retry-After` is returned
> **And** the App passes both the status and the header through unmodified.

#### AC8 — the node being down is not a 500
> **Given** the node Service is unreachable
> **When** a sync request arrives at the App
> **Then** the caller receives `503` with `Retry-After`, not `500`.

#### AC9 — the forwarder retries only what is safe
> **Given** a forwarded request
> **When** the node refuses the connection
> **Then** the App retries exactly once
> **And** when the node times out or returns `5xx`, the App does **not** retry.

A timeout may mean the node is mid-call and billing. Retrying doubles the cost for
one caller's single request. [proposed]

#### AC10 — aigateway failure surfaces as 502
> **Given** aigateway is unreachable or returns an error
> **When** the handler calls it
> **Then** the caller receives `502` in url4's error envelope.

### Edge cases

#### AC11 — a mount path with a missing `q` explains itself
> **Given** `GET /anthropic/claude-haiku-4-5` with no query string
> **When** the request is dispatched
> **Then** the response is `400` naming the required `q` parameter
> **And** not url4's default `404 endpoint_not_found`.

#### AC12 — an unknown path 404s at the App
> **Given** a path not in the forwardable mount set
> **When** the request arrives
> **Then** the App returns `404` and does not forward.

#### AC13 — a colon-bearing model id is addressable in encoded form
> **Given** a model id encoded by `encode_route_id` with a tilde
> **When** a caller requests the encoded path
> **Then** the mount resolves.

#### AC14 — a non-GET method is rejected
> **Given** `POST` to a mount path
> **When** dispatched
> **Then** `405`, per url4's GET-only contract.

#### AC15 — a large body spills and the redirect is fetchable
> **Given** a response exceeding 512 KiB
> **When** the request completes
> **Then** the caller receives `303` with a `Location` under `/artifacts/`
> **And** following the `Location` (which carries a valid short-lived signature)
>   returns the full body with no capability token
> **And** fetching the same id bare — no token, no signature — is refused.

#### AC16 — an oversized body fails rather than spilling
> **Given** a response exceeding `result_hard_cap_bytes`
> **When** the request completes
> **Then** `413`, and nothing is written to the artifact store.

#### AC17 — local mode preserves route precedence
> **Given** `serve --local` with the node mounted
> **When** `/v1/models` is requested
> **Then** the engine's catalog answers
> **And** when bare `/v1?q=<expression>` is requested, the node's eval path answers.

#### AC18 — readiness gates on a built world
> **Given** a starting node pod
> **When** the world has not finished building, or the collision guard failed
> **Then** the readiness probe fails and no traffic is routed to the pod.

#### AC19 — world build performs no network I/O
> **Given** aigateway is unreachable
> **When** the node tier starts
> **Then** the world still builds and the pod becomes ready
> **And** individual calls fail with `502` until aigateway recovers.

A tier that cannot start without its downstream turns one outage into two. If the
current build path does reach the network, that is a finding to fix in this unit.
[proposed]

## 4. Out of scope

- The eval path as a public sync surface, and async hand-off (D1).
- Exec mounts (D2).
- `.well-known/url4-*` documents and mount-table federation. The node tier is their
  natural home and should host them next.
- Routing traffic from the edge directly to the node tier (`ans:Q6` chose App
  forwarding).
- Per-caller holdings scoping (D8).

## 5. TDD plan

Risk order. A cross-caller identity leak and an impersonation hole are the two
outcomes that would be worst in production, so they are pinned before anything else.

### T1 — concurrent identity isolation, end to end (AC3)
**RED** — Drive two concurrent requests with different identities through a node
serving a stubbed aigateway; assert each outbound call carried its own. Fails before
the sync scope producer exists.
**GREEN** — Bind `RequestScope` per request in the ASGI middleware.
**Refactor** — Share header parsing with unit 1's child-boot producer.

### T2 — client-supplied identity is overridden (AC4)
**RED** — Send a forged `X-User-Email`; assert the forwarded value is the verified
one, and that a request with no verified identity is rejected.
**GREEN** — Strip and re-set in the forwarder.
**Refactor** — One helper, used by both the forwarder and local mode.

### T3 — local route precedence (AC17)
**RED** — Assert `/v1/models` returns the catalog and `/v1?q=` reaches the node.
Fails if the mount is registered before the literal routes.
**GREEN** — Mount last.
**Refactor** — Assert the ordering in the composition root so a future insertion
cannot silently reorder it.

### T4 — timeout returns 504 and cancels downstream (AC6)
**RED** — Stub aigateway to hang; assert `504`, the ensemble-path message, and that
the stub observed a cancellation.
**GREEN** — url4's timeout wrapper plus an explicit aigateway timeout below it.
**Refactor** — Centralise the ladder's numbers in settings, not literals.

### T5 — spill produces a fetchable redirect (AC15)
**RED** — Force a >512 KiB response; assert `303`, then fetch the `Location` with
edge identity only and compare bytes. The fetch fails until OQ-3.2 is resolved,
which is precisely why this test is written early.
**GREEN** — Spill writer plus the signed-URL issuance (node) and verification
(App), per the OQ-3.2 decision.
**Refactor** — Reuse the run path's writer; do not fork it.

### T6 — hard cap rejects without writing (AC16)
**RED** — Force a response above the hard cap; assert `413` and that the store was
not written.
**GREEN** — Check the hard cap before the spill.
**Refactor** — Order the two checks once, shared with the run path.

### T7 — capacity shedding passes through (AC7)
**RED** — Saturate the in-flight cap; assert `503` and that `Retry-After` survives
the forwarder unchanged.
**GREEN** — Configure url4's admission wrapper; pass headers through.
**Refactor** — none.

### T8 — forwarder retry policy (AC9)
**RED** — Assert exactly one retry on connection refused, and zero retries on
timeout and on `502`.
**GREEN** — Explicit transport-level retry only.
**Refactor** — none.

### T9 — missing `q` explains itself (AC11)
**RED** — Request a known mount without `q`; expect `400` naming `q`.
**GREEN** — Detect "path is a known mount and `q` is absent" before url4's dispatch
falls through.
**Refactor** — none.

### T10 — unknown path 404s at the App (AC12)
**RED** — Request an unmounted path; assert `404` and that no forward occurred.
**GREEN** — Build the forwardable set from the world module.
**Refactor** — none.

### T11 — encoded route ids (AC13) and T12 — non-GET (AC14)
**RED** — Straightforward assertions against the encoded path and a `POST`.
**GREEN** — Should pass once mounts are wired; if not, the encoding is applied on
one side only.
**Refactor** — none.

### T13 — readiness gating and offline start (AC18, AC19)
**RED** — Start with a failing collision guard, assert readiness fails. Start with
aigateway unreachable, assert readiness succeeds and calls return `502`.
**GREEN** — Gate readiness on world build plus guard; keep the build I/O-free.
**Refactor** — none.

### T14 — ensemble regression (AC2)
The existing conformance suite, run against the deployed shape. Not a new test; the
gate for the unit.

### T15 — NetworkPolicy (AC5)
Verified in the deployment smoke check, not in the unit suite: from a pod that is not
the App, assert the node Service refuses the connection.

## 6. Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Cross-caller identity leak via retained state | Medium | **Critical** | T1 here and T1/T2/T3 in unit 1; the ContextVar has no default |
| Impersonation because NetworkPolicy is missing or wrong | Medium | **Critical** | AC5, T15, and a deploy-time smoke check |
| 30 s cuts off legitimate slow models | **High** | Medium | Accepted under `ans:Q5`. The 504 body names the ensemble path. Revisit with real latency data |
| The tier has no `RLIMIT_AS`; one response OOMs a shared pod | Medium | High | D1 removes fan-out, so blast is one model response; plus the 512 KiB cap, the hard cap, and pod memory limits |
| Two error dialects on one origin confuse clients | **High** | Low | OQ-3.1. The cost is documentation, not correctness |
| Loosening `/artifacts/{id}` auth widens an existing route | Medium | High | OQ-3.2; prefer signed URLs if the loosening is unacceptable |
| Gray failure: node slow but passing probes | Medium | Medium | `503` shedding with `Retry-After`, plus the in-flight gauge and the 503 counter. Readiness is drain-only (`04-review-fixes.md` RD2): a saturated pod stays ready, because removing it moves its load onto the others |
| App and node briefly disagree on mounts during a rolling deploy | Medium | Low | `config_digest` on health; unknown mounts 404 at the App rather than forwarding |

## 7. Open questions

**OQ-3.1 — Is two error dialects on one origin acceptable?**
Mount paths return url4's `{"error":{"code","message"}}`; every other engine route
returns RFC 9457 `application/problem+json`. Forwarding verbatim (D6) and url4
client compatibility both argue for keeping url4's envelope. **Decision (owner, follow-up round): keep both dialects.** The split is
accepted as specified; documenting it in the engine README and in the OpenAPI
description is a **deliverable of unit 3**, not a follow-up. `contracts.md` C1
and the README must state, in one place, which paths speak which envelope.

**OQ-3.2 — How does a token-less caller fetch a spilled artifact?**
D9 redirects sync callers to `/artifacts/{id}`, which is token-only today, and the
artifact id is a content hash rather than a capability. Two options:
(a) accept edge-verified identity as an alternative to the token — smaller change,
but loosens an existing route for all callers;
(b) issue a short-lived signed URL with the `303` and leave `/artifacts/{id}`
token-only — more code, tighter isolation.
**Decision (owner, follow-up round): option (b) — short-lived signed URLs.**
`/artifacts/{id}` without a valid signature stays exactly as today
capability-token-only; the spill path issues a signed URL with the `303`, and a
request carrying a valid signature is accepted as an alternative credential on
that route. Consequences now pinned:

- The node tier **signs** (it emits the `303`); the App **verifies**. A shared
  HMAC signing key is therefore a new Secret injected into both tiers
  (`contracts.md` C6).
- The signature binds the artifact id and an expiry only. Proposed default TTL:
  **10 minutes**, configurable, centralized with the ladder numbers (T4's
  refactor note).
- This decision is what lets T5 go green; `contracts.md` C6 is updated to
  match and `test-plan.md` R9 closes.
