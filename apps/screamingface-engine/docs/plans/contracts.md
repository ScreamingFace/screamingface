# Interface contracts

One section per hop. New or changed hops are marked **NEW** or **CHANGED**.
Unchanged hops are listed because they are regression surface.

## Timeout ladder

Timeouts must decrease inward, so the innermost component fails first and the
caller gets a meaningful error instead of a severed connection. [proposed]

| Layer | Budget | Why |
|---|---|---|
| Cloudflare edge | ~100 s (not ours) | Outermost. Must never be the thing that fires. |
| App → node forward | 35 s | Slightly above the node's own budget so the node's 504 wins the race. |
| Node request wrapper | **30 s** | `ans:Q5`. Emits 504. |
| Node → aigateway | 28 s | Fails inside the wrapper, so the caller gets a 502 naming the cause rather than a bare 504. Overrides `url4.toml`'s 600 s default on this tier. |

The 600 s default in `url4.toml` is correct for the ensemble path and wrong for the
sync tier. The node tier must override it rather than inherit it. [proposed]

---

## C1 — Client → App, sync mount call **NEW**

| Field | Value |
|---|---|
| Endpoint | `GET /<mount path>?q=(context)!intent` |
| Protocol | HTTP/1.1, GET only |
| Auth | Edge-verified `X-User-Email`, injected by Cloudflare Access / Envoy. Never trusted from the client. (`ans:Q4`) |
| Request headers | `X-Profile` (optional), `Cache-Control` (optional, RFC 9111 request directives), `X-Answer-Seed` (optional int), `traceparent` (optional, strict W3C) |
| Success | `200`, `text/plain; charset=utf-8`, body is the handler's return value |
| Large result | `303 See Other`, `Location: /artifacts/{id}` **plus a short-lived signature** when the body exceeds 512 KiB (D9, OQ-3.2 decision) |
| Timeout | 30 s, then `504` |
| Idempotency | GET is idempotent in HTTP terms. The underlying model call is **not** deterministic and **is** billable. No de-duplication is performed. A client wanting a repeatable answer sends `X-Answer-Seed`. [proposed] |
| Retry guidance | Safe to retry on `502`, `503` and `504`. Honour `Retry-After` when present. |

### Error shape — a deliberate divergence

This surface returns **url4's** error envelope, not the engine's RFC 9457
`application/problem+json`:

```json
{"error": {"code": "endpoint_not_found", "message": "..."}}
```

Rationale: under D6 the App forwards verbatim, and this surface *is* a url4 node
surface. A url4 client should be able to point at the engine and at a bare
`url4 serve` node and get the same contract. Translating to RFC 9457 would make the
engine incompatible with url4's own clients for no gain.

The cost is honest and should be stated: **one origin now speaks two error
dialects** — problem+json on `/`, `/token`, `/v1/*`, and url4's envelope on mount
paths. This needs owner sign-off before unit 3 merges. Tracked in
`prd/03` §7. [proposed]

Status mapping is url4's own (`peer/_http.py:30-93`):

| Status | Codes |
|---|---|
| 400 | `malformed_source`, `unbound_reference` |
| 403 | `identity_access_denied`, `consent_required`, `consent_withheld` |
| 404 | `endpoint_not_found`, `unknown_identity`, `identity_unavailable` |
| 405 | non-GET method |
| 413 | body over the hard cap **[proposed, engine addition]** |
| 502 | transient downstream failure |
| 503 | over capacity, with `Retry-After` |
| 504 | request exceeded 30 s **[engine addition via the serve wrapper]** |

Two failure shapes deserve named handling because url4's defaults read badly here:

- **Mount exists, `q` is missing.** url4 dispatch only consults endpoints when `q`
  is present, so `GET /anthropic/claude-haiku-4-5` with no query falls through to
  data routes and returns `404 endpoint_not_found`. A caller who simply forgot the
  query gets told the endpoint does not exist. The engine should return `400` with
  a message naming the missing `q`. [proposed]
- **Timeout.** The 504 body must name the ensemble path as the remedy, because
  under `ans:Q5` a 30 s budget will legitimately cut off slow reasoning models.
  [proposed]

### Known constraint — URL length

`q` travels in the query string. Envoy and Cloudflare cap request URLs at roughly
8–16 KiB. A large context therefore cannot be sent on this surface. url4 is GET-only
by doctrine (`peer/_http.py:71`), so there is no POST variant to fall back on.
Document the limit; large-context work belongs on the ensemble path. [implied]

---

## C2 — App → node tier, verbatim forward **NEW**

| Field | Value |
|---|---|
| Endpoint | `GET http://<node-service>/<mount path>?<query verbatim>` |
| Protocol | HTTP/1.1 over the cluster network. Shared `httpx.AsyncClient` with keep-alive. |
| Forwarded | The path and query unchanged; `X-User-Email`, `X-Profile`, `Cache-Control`, `X-Answer-Seed`, `traceparent` |
| Not forwarded | Cookies, `Authorization`, `URL4-Capability`, any client-supplied `X-User-Email` (stripped and re-set from the verified value) |
| Timeout | 35 s |
| Retry | **Once, on connection error only.** Never on timeout, never on a 5xx response. A timeout may mean the node is mid-call and billing; retrying doubles the cost. [proposed] |
| Response handling | Status, body and `Retry-After` passed through unchanged. `303` `Location` is rewritten only if the node's artifact path differs from the App's. |
| Failure — node down | `503` with `Retry-After: 1` |
| Failure — node over capacity | url4's own `503` + `Retry-After`, passed through unmodified |

### Route agreement

Under D6 the App must know which paths to forward. Two options, and the second is
recommended:

1. Forward anything not matching an engine literal route. Simple, but the App then
   proxies typos to the node and inherits its 404s.
2. **Build the mount path set from the same `world` module the node uses, at App
   startup, and forward only known mounts.** Requires no network call — F1 makes the
   declaration importable by both halves. Unknown paths 404 at the App. [proposed]

Option 2 is what makes D6's "verbatim" safe: both tiers derive their route set from
one declaration, so drift is impossible within a release. Across a rolling deploy
the two tiers may briefly differ; the `config_digest` on the health endpoint
(`erd.md` §2) makes that visible.

---

## C3 — Node → aigateway **CHANGED**

Unchanged in shape; changed in who calls it and with what state.

| Field | Value |
|---|---|
| Endpoint | `POST {aigateway_base_url}/v1/chat/completions` |
| Headers | `X-User-Email` from `REQUEST_SCOPE`, `X-Profile` if set, `traceparent`. **No `Authorization`** — aigateway runs `cloudflare_headers` mode and reads identity, not a bearer token. |
| Body | `{"model": <decoded id>, "messages": [...], ...}` plus cache directives |
| Timeout | 28 s on this tier (see ladder) |
| Retry | Existing connector policy: 1 retry, exponential backoff with jitter. **Must be bounded by the remaining request budget** — a retry that cannot finish inside 30 s should not be attempted. [proposed] |
| Idempotency | None. Each attempt is a separate billable completion. |
| Failure | Transport error → `ResolutionError` transient → `502` upstream |

**The change that matters:** every value in the header set now comes from a
ContextVar rather than from fields on a long-lived handler object (F2). This hop is
where a ContextVar leak would become a security incident — caller A's request
carrying caller B's identity. It is the single highest-risk line in the change and
is tested first (`test-plan.md` §3, T1).

---

## C4 — Node → Tavily, web tools

Unchanged. Bounded by `web_tool_max_iterations`, calls per turn, and result bytes.
On the sync tier the 30 s budget bounds it far more tightly than those caps do, so a
web-tool-enabled mount will usually exhaust the budget rather than the iteration
count. Operators should prefer `web_search = false` on mounts intended for the sync
surface. [proposed]

---

## C5 — Node → artifact store, spill write **NEW**

| Field | Value |
|---|---|
| Operation | `PUT {bucket}/{sha256}` via SigV4, or an atomic write-then-rename on a filesystem store |
| Trigger | Response body exceeds 512 KiB (D9) |
| Hard cap | Bodies above `result_hard_cap_bytes` fail with `413` rather than spilling |
| Idempotency | Content-addressed, so a repeated write of identical bytes is a no-op |
| Failure | Write failure → `502`. The response is **not** returned inline as a fallback: falling back would defeat the memory protection the cap exists for. [proposed] |
| Credentials | S3 access and secret keys, injected as a Kubernetes Secret. New requirement for this tier. |

---

## C6 — Client → App, artifact fetch **CHANGED**

| Field | Value |
|---|---|
| Endpoint | `GET /artifacts/{id}` |
| Today | Requires a `URL4-Capability` token (`rest/artifacts.py:47`) |
| Problem | A sync caller never holds a token (D4), so under D9 the engine would redirect them to an endpoint they cannot call |
| Proposed change | **Decided (owner, follow-up round): short-lived signed URLs.** The spill path issues `Location: /artifacts/{id}?exp=<ts>&sig=<hmac>`; the App verifies `sig` as an alternative credential. Bare `/artifacts/{id}` — no token, no signature — behaves exactly as today. |
| Signing | HMAC over the artifact id and expiry, shared key in a Kubernetes Secret injected into **both** tiers (the node signs, the App verifies). Proposed TTL: **10 minutes**, configurable, centralized with the ladder numbers. The signature binds id + expiry only. |
| Why not rely on the id | The id is a SHA-256 of the content, not a random capability. It is guessable whenever the content is guessable, so it must not be the only thing protecting the fetch. |

This is the one place where D9 forces a change to an existing, already-shipped
endpoint, and the decision is recorded above: the signed URL keeps the existing
route token-only for bare requests while giving the sync caller a scoped,
short-lived credential. The id remains a content hash, not a capability — which
is exactly why the signature, not secrecy of the id, is what authorizes the
fetch. Decision recorded in `prd/03` §7 (OQ-3.2).

---

## C7 — Process → `url4.toml`, config load **CHANGED**

| Field | Value |
|---|---|
| Source | `URL4_RUNNER_CONFIG`, default `/etc/url4/url4.toml`, baked into the image |
| Read by | The child (today), plus the node tier and the App (new) |
| Sections | `[aigateway]` as today; `[data]`, `[holdings]`, `[identities]` become real (D2) |
| Rejected | `[commands]` entirely; command-backed providers inside `[data]` |
| Failure | `WorldConfigError` at startup. The process must not start. A half-configured node serving a partial mount set is worse than a node that refuses to boot. [proposed] |
| Startup logging | The declared shelves are logged, because under D8 they are readable by every caller |

---

## C8 — Local mode, in-process ASGI mount **NEW**

No network hop. `serve --local` mounts `node.asgi()` into the FastAPI app, registered
**after** all literal routes so precedence resolves collisions (D3).

| Field | Value |
|---|---|
| Ordering invariant | Every engine literal route is registered before the mount. Pinned by a test that asserts `/v1/models` reaches the engine and bare `/v1?q=` reaches the node. |
| Shared world | The in-process run path uses the same node as its `IOLayer`, wrapped per run for fair-share I/O. F2 makes this safe. |
| Divergence from deployed | Local has no forwarder and no NetworkPolicy. It is a development shape and must not be presented as a deployment option. |

---

## C9 — Ensemble path, unchanged

Listed as regression surface. `POST /token` → WS `/ws?ticket=` → `ai.url4.attach`
→ `GET /?q=` → NATS queue → worker claim → fork child → frames back over the socket.

The one thing unit 1 touches here is *where the world code lives*, not what it does.
Any observable change on this path is a defect, and the existing suite is the oracle.

---

## 10. Trust boundaries

| Boundary | Untrusted input | Control |
|---|---|---|
| Client → App | `q`, all headers, the path | Identity is taken only from the edge-verified header. Client-supplied `X-User-Email` is stripped. |
| App → node | — | NetworkPolicy: only the App may reach the node tier. Without it, anyone in-cluster could set `X-User-Email` freely. **Required, not optional.** |
| Node → aigateway | — | Identity forwarded, no bearer token |
| `q` → model | Prompt content | Prompt injection is inherent to the product and is not a regression. Unchanged from the ensemble path. |
| `q` → URL fetch | Absolute URLs in context | **Not reachable on the sync surface.** A direct mount hit does not run the DAG, so a URL-valued context stays opaque text (D1). `allow_outbound` should still be `false` on this tier as defence in depth. [proposed] |
