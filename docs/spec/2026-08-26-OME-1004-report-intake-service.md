---
title: Report-intake service
ticket: OME-1004
status: draft
date: 2026-08-26
---

# Report-intake service

`apps/report-intake` accepts an error report from a ScreamingFace client, persists it, and
files it into the **private** Linear workspace. Its reason to exist is that a reporter
should need no account of their own — the service holds the credential, so a researcher in
a notebook can send a diagnosable bug report without a GitHub login, a Linear seat, or an
email we can verify.

Epic: `OME-1002`. The decisions behind it are recorded in
`docs/spec/2026-08-22-observability-traceability-review.md` §6 Phase 3 and in the
pre-decision `OME-973`.

## 1. Non-goals

These are settled and should not be re-litigated during implementation.

- **No bundle or blob store.** Prompt-bearing content is rejected, not stored. This removes
  content-addressing, TTL sweeps, a retention policy, and an Access-gated read surface from
  the service entirely.
- **No `GET /v1/reports/{ref}`.** It was inherited from a browser-form design that no
  longer exists; with a kernel-side POST nothing consumes it. Support questions are
  answered from our own storage.
- **No query or search API, no triage logic, no human sessions, no UI.** Triage happens in
  Linear.
- **It is its own app.** It cannot be added to scoreboard (the submitter check is a plain
  call rather than a `Depends`; production is Traefik-fronted rather than Access-meshed, so
  `X-User-Email` is forgeable there; and flipping `authMode` CrashLoops on current chart
  defaults) or to aigateway-ui (whose chart fails the render on `ingress.enabled=true` —
  unreachability *is* its authentication boundary).

## 2. API

```
POST /v1/reports              the only write
GET  /healthz                 liveness, static
GET  /readyz                  readiness, checks storage
```

`/healthz` must never touch storage. A liveness probe that depends on the database turns
one bad database into a restart loop; `/readyz` is the one that may fail closed.

### 2.1 Request

`Content-Type: application/json` only. **No form encoding, from any client.** In the
notebook that decision is load-bearing: an HTML `<form>` would serialize the report body
and any credential into the saved `.ipynb`, and JupyterLab's sanitizer strips `action` and
`name` from untrusted output anyway, so the notebook client posts kernel-side. Browser
clients — the portal and aigateway-ui — post the same JSON with `fetch`; they are
first-class callers, not an exception.

Because browser callers are first-class, the service is CORS-relevant: JSON bodies are not
simple requests, so every browser submission is preceded by a preflight. Allow the origins
the clients actually run on, allow `Content-Type` and `Idempotency-Key`, and **do not**
allow credentials — the mesh supplies identity, so no cookie ever needs to cross. An origin
allowlist is not an authorization control and is not counted as one.

| Header | Meaning |
|---|---|
| `Idempotency-Key` | client-minted; recommended. Absent means the service cannot dedupe a retry. |
| `X-User-Email` | **honoured only when injected by the mesh.** Any client-supplied copy is stripped at the edge. |
| `Cf-Turnstile-Response` | present only if anonymous submission is admitted — see §7. |

```jsonc
{
  "schema": "screamingface.error-report/v1",   // required
  "occurred_at": "2026-08-26T14:03:11.204Z",   // required, RFC 3339

  "client": {                                   // required
    "name": "screamingface-python",             // the SDK or app, NOT the language
    "version": "0.1.1.post5",
    "host": "notebook",                         // notebook | cli | studio | web
    "platform": "darwin",                       // darwin | linux | windows | browser
    "runtime": {                                // the language runtime
      "name": "cpython",                        // cpython | node | browser | …
      "version": "3.13.1"
    },
    "frontend": {                               // nullable; browser-side, via widget comm
      "name": "jupyterlab",
      "version": "4.5.3"
    },
    "user_agent": "..."                         // nullable; browser-side, opaque
  },

  "error": {                                    // required
    "type": "ExecutionError",
    "code": "websocket_disconnected",
    "message": "...",                           // carried VERBATIM — see note below
    "status": null,
    "permanent": false,
    "retryable": true,
    "hint": "...",
    "notes": ["..."],
    "details": { },                             // nullable; unbounded server JSON — see caps
    "cause": { "type": "...", "rcvd": { "code": 1011, "reason": "..." } },
    "traceback": "..."                          // nullable
  },

  "correlation": {                              // all nullable
    "trace_id": null,
    "run_id": null,
    "gateway_call_id": null
  },

  "context": {                                  // nullable throughout
    "engine_host": "engine.screamingface.ai",   // HOST only, never a full URL or query
    "benchmark": { "id": "...", "revision": "..." },
    "candidate": { "name": "...", "kind": "fusion", "models": ["..."] }
  },

  "note": "...",                                // nullable, user free text
  "reply_to": "someone@example.org"             // nullable, self-asserted, never identity
}
```

**`client` is language-neutral by construction.** Three of the four client surfaces are not
Python — Studio (Electron), aigateway-ui (Next.js), and the portal (browser JS) — so no
field may name a language. `name` identifies the SDK or app; `runtime` identifies whatever
executes it. The same `{name, version}` pair is reused for `client`, `runtime`, and
`frontend` so that "which versions are failing?" is a group-by rather than a string parse.

| Surface | `name` | `host` | `platform` | `runtime.name` |
|---|---|---|---|---|
| Python SDK | `screamingface-python` | `notebook` / `cli` | `darwin` / `linux` / `windows` | `cpython` |
| Studio (Electron) | `screamingface-studio` | `studio` | `darwin` / `linux` / `windows` | `node` |
| aigateway-ui | `aigateway-ui` | `web` | `browser` | `browser` |
| Portal | `scoreboard-portal` | `web` | `browser` | `browser` |

Studio reports as `node`, not `browser`: Electron's renderer cannot make the external call
(CORS), so the submission runs in the main process. Studio is a click-through prototype
today, so its row is the contract it will satisfy, not behaviour that exists.

**The vocabularies are documented, not enforced.** `host`, `platform`, and `runtime.name`
carry the values listed above, but an unrecognised value is **stored, not rejected** — it is
triage metadata and routes nothing in v1. A client shipping before the service learns its
name must still be able to report a bug. Each is a bounded string (§2.4) and is escaped at
ticket-render time; nothing is ever branched on. Only *structural* violations reject.

**Unknown keys: forbidden at the top level, preserved inside `client` and `context`.** The
top level is a small stable set, so an unknown key there is a typo worth a `422`. `client`
and `context` are the extension points, and clients in four languages will not ship in
lockstep — a `node` client adding `electron_version` must not be rejected by a service that
predates it. Unknown keys inside those two objects are stored verbatim, counted against the
depth and key-count caps, and never interpreted.

**`error.message` is carried verbatim and must not be "cleaned up" into structured
fields.** In the current client the WebSocket close code and elapsed seconds exist *only*
inside that string — `ExecutionError` adds no attributes over its base. A future client may
add structured fields; until then, discarding the message loses the two facts that most
often explain a disconnect.

**`context` is caller-supplied.** A generic `except` around an evaluation gets none of it,
because the runner re-raises untouched and the transport attaches no candidate. The service
must treat every `context` field as optional and must never infer it.

### 2.2 Success

One shape, for both new reports and replays.

```jsonc
{
  "ref": "r_8f21c0",
  "classification": "envelope",                 // the SERVER's verdict, not the client's
  "delivery": {
    "state": "delivered",                       // delivered | pending | failed
    "ticket": { "id": "OME-1042", "url": "https://linear.app/..." }   // null unless delivered
  }
}
```

- `202 Accepted` — a new report was persisted.
- `200 OK` — idempotent replay; the original record is returned unchanged.

`202` rather than `201` is deliberate: it encodes that the report is durable while the
ticket may not exist yet. Delivery is attempted inline with a **3 s** timeout, so `state`
is usually `delivered` and the ticket id returns on the first call; a slow or failing sink
degrades to `pending` instead of failing the reporter's request.

### 2.3 Errors

RFC 9457 `application/problem+json`, matching the engine's existing convention in
`auth/problem.py`.

```jsonc
{ "type": "about:blank", "title": "Payload Too Large", "status": 413,
  "detail": "report body is 91 kB; the limit is 64 kB" }
```

| Status | Cause |
|---|---|
| `400` | malformed JSON; unknown `schema` **major** |
| `413` | body over cap — `detail` **names the cap** |
| `422` | schema violation (field pointers), or content rejected (§4) |
| `429` | rate limited |
| `503` | storage unavailable |

A `503` is meaningful to the client: it means *nothing was stored*, so the client must fall
back to writing the report to disk rather than assuming delivery.

### 2.4 Caps

Concrete, because "bounded" is how `OME-969` happened.

| Limit | Value | On breach |
|---|---|---|
| total body | 64 KiB | `413` |
| `note` | 4 KiB | truncate, mark |
| `error.message` | 8 KiB | truncate, mark |
| `error.traceback` | 32 KiB | truncate **head and tail kept**, mark |
| `error.details` | 8 KiB | truncate, mark |
| `notes[]` | 16 items | drop excess, mark |
| any `client` / `context` string | 256 B | truncate, mark |
| `user_agent` | 1 KiB | truncate, mark |
| JSON depth | 6 | `422` |
| object keys per node | 64 | `422` |

Oversized *individual strings* are truncated with an explicit marker rather than rejected —
a truncated report is worth more than no report. Only the total body cap and structural
violations reject. Truncation keeps the head **and** tail of a traceback, because the
innermost frame is usually the informative one — and runtimes disagree about which end that
is. CPython renders it last, V8's `Error.stack` renders it first. Keeping both ends means
the truncator does not need to know which runtime produced the string.

Control characters other than tab and newline are stripped from every free-text field.

## 3. Pipeline

```
bound  ->  classify  ->  persist  ->  dedupe  ->  deliver  ->  respond
```

Bound before trusting. Classify without believing the client. **Persist before
delivering.** Dedupe on the idempotency key. Deliver through a port.

## 4. Classification

The service decides the class. It does **not** trust `client`-declared intent.

- Scan the payload for content-bearing material: prompt text, model responses, cell source,
  log bodies, url4 expressions.
- Content present → **reject with `422`**, with a `detail` explaining that prompt-bearing
  content is not accepted by this service.
- Fail safe: undeclared content is still content. Never fail open.
- Echo the verdict as `classification` so a client can tell what was understood.

**Why reject rather than store.** v1 has no bundle store, so there is nowhere safe to put
it: Linear is third-party SaaS and the review spec permits prompt-bearing bodies only in
the Cloudflare-Access-gated SigNoz sink. A responder who needs prompt text asks the
reporter — which is why `reply_to` exists — or, once Phase 2 lands, pulls it from SigNoz by
`trace_id`.

**Do not attempt redact-and-accept.** Partial redaction of free text is unreliable and
creates false confidence. Reject cleanly and say why.

## 5. Storage and idempotency

One table. The service has state, but it is a retry queue, not a document store.

| Column | Notes |
|---|---|
| `ref` | primary key, minted server-side, never derived from client input |
| `idempotency_key` | unique, nullable |
| `payload` | the validated, truncated report |
| `classification` | server verdict |
| `caller_email` | from the mesh only; nullable |
| `reply_to` | self-asserted; nullable |
| `delivery_state` | `pending` / `delivered` / `failed` |
| `attempts` | integer |
| `ticket_id`, `ticket_url` | nullable until delivered |
| `created_at`, `updated_at` | |

**Persist before deliver.** The record is committed before the sink is called. A sink
outage is then a retry rather than a lost bug report. Calling the sink first and storing on
success is the single most common way services like this drop reports, and it is
prohibited here.

**Idempotency window: 24 h**, matching the scoreboard's existing `idempotency_keys` TTL.
Within it, a replayed key returns `200` with the original record — one report, one ticket,
regardless of double-clicks or client retries. After it, the same key is treated as new.

**Row retention: 90 days**, then purged. The ticket is the durable artifact; the row exists
for idempotency, retry, and operational forensics.

## 6. Delivery

`TicketSink` is a port. Core defines it; core never imports an adapter; wiring happens in a
registry.

- **`LinearSink`** — creates the issue directly. Requires the `OME-976` amendment.
- **`QueueSink`** — the fallback: mark the record ready and let an agent file it via MCP
  during triage. Still private Linear, but asynchronous and with no ticket id returned.

**Ticket content:** the envelope, `trace_id`, `ref`, the reporter's note, `reply_to` when
present, and the caller email when the mesh supplied one. **Never** prompt-bearing content
— see §4.

**Retry:** exponential backoff, 6 attempts over roughly 24 h, then terminal `failed`.
`failed` must be visible to us through a metric or log line; a report we permanently failed
to file is an operational event, not a shrug. Retries must not stampede the sink's rate
limits.

## 7. Identity and auth

Settled regardless of the open fork:

- `X-User-Email` is trusted **only** when Envoy injects it after re-verifying the
  Cloudflare Access assertion, exactly as aigateway does. Client-supplied copies are
  stripped at the edge.
- `reply_to` is self-asserted and is never identity. It matters more here than it looks:
  the Python client parses only `exp` from its Access token, so it has **no email of its
  own** — without `reply_to`, an SDK report cannot be answered.
- Content is rejected for every caller, authenticated or not.
- **Nothing is ever authorized by `trace_id` or `run_id`.** An id in a report is a claim,
  not a credential (`OME-966`).

The rest depends on the `OME-973` fork — see §9.

## 8. Failure modes

| Condition | Service | Client |
|---|---|---|
| sink slow (>3 s) | persist, `delivery.state=pending`, retry | shows `ref`, no ticket id |
| sink down | as above | as above |
| sink permanently failing | `failed` after 6 attempts, alarm | already returned |
| storage down | `503`, nothing stored | write report to disk, print path |
| over body cap | `413` naming the cap | truncate and retry once, else disk |
| content present | `422` | drop content, resend envelope |
| rate limited | `429` | back off, offer disk fallback |

The client rule behind this table: **a report is never lost.** Every terminal failure path
ends with the report on the user's disk and a path printed.

## 9. Open decisions

Both block implementation, not this spec.

**`OME-976` — rule 9.** As written, CLAUDE.md rule 9 forbids product code from calling
Linear's API. Amending it selects `LinearSink`; declining selects `QueueSink` and the
reporter stops getting a ticket id. The amendment must also state where the credential
lives and who rotates it — a long-lived Linear API key in a deployed service is a new
secret class for this repo.

**`OME-973` — anonymous or authenticated.** This decides whether the abuse surface exists
at all.

| | Authenticated | Anonymous |
|---|---|---|
| gate | none | Turnstile + edge rate limit |
| `X-User-Email` | mesh-injected | absent |
| `reply_to` | ignored | accepted, unverified |
| content | rejected | rejected |

Admitting anonymous callers makes this the repo's first unauthenticated write that reaches
human eyes, in a codebase with no rate limiting anywhere. The stakes rose when reports were
routed to private Linear: spam lands in the workspace the team works in, rather than a
public tracker that could be moderated at arm's length.

## 10. Verification

- Behavior-named tests per cap: an over-cap body is rejected *and names the cap*; a
  deep-nested payload is rejected; an ordinary report is untouched; an oversized traceback
  is truncated head-and-tail with a marker.
- A report containing an undeclared prompt string is rejected; an envelope-only report
  passes; the rejection says why.
- A report survives a sink failure: the record exists, `state=pending`, and the response is
  still `202`.
- The same `Idempotency-Key` twice produces one row and one ticket.
- Storage down returns `503` and creates nothing.
- A forged `X-User-Email` from outside the mesh is not honoured.
- `helm template` renders for default and prod values; `verify_chart_wiring.py` asserts
  something real about this chart; liveness and readiness point at **different** endpoints.
