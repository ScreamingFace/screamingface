---
title: Debugging & traceability review — inventory, gaps, phased roadmap
ticket: OME-936
status: approved
date: 2026-08-22
updated: 2026-08-24
---

# Debugging & traceability review

Three questions drove this review: what debugging/traceability tooling the solution has
today and whether it is integrated correctly; which of it works against the live k8s
deployment versus local development only; and what exists for humans reporting errors —
and how such a report can be connected to logs and traces. The whole monorepo was audited:
`apps/aigateway`, `apps/aigateway-ui`, `apps/scoreboard`, `apps/screamingface-engine`,
`packages/url4`, `packages/screamingface`, all Helm charts, CI, and `docs/`.

The one-paragraph verdict: the engine/url4 layer already produces real observability
signals — one W3C `trace_id` per run tree, OTel-GenAI-shaped span/cost/log frames, a
Prometheus endpoint — but **nothing consumes them**: no scraper, no exporter, no durable
store. The other three apps produce almost no signal at all. The single most severe
finding is that a run's entire diagnostic record is destroyed ~60 seconds after the run
ends, which by itself defeats any human-reporting channel: a report arrives hours after
the evidence is gone.

Sections 1–3 were written from a static reading of the code. **Section 4 records an
empirical audit run on 2026-08-24** that drove the real code paths and captured real
output; it confirms most of the reading, corrects it in several places, and supersedes it
wherever the two disagree. Read §4 before acting on §1.

## 1. What exists, per component

### aigateway

Stdlib logging only, plain text, no timestamps or request IDs (`src/aigateway/logs.py:27`);
`AIGW_LOG_LEVEL` is the one knob and it works (drives uvicorn and the app tree, surfaced
in the chart). Secret redaction is properly engineered: `RedactProvisioningTokenFilter`
installs process-wide via `logging.setLogRecordFactory` (`core/auth/log_filter.py:71-85`).
The only correlation handle is **`gateway_call_id`** (`call_<uuid>`), built for cost
accounting: it appears in the `_aigw` response envelope and in exactly **one** log line
(`plugins/taxonomy/session.py:135`); a test pins that the two are the same value. Every
other log line of the same request — dispatch, cache, retry, concurrency — carries no id.
The `AccountingAsyncHTTPHandler` (`core/usage_accounting/hooks.py:243`) observes every
provider send with httpx event hooks (latency-to-body, status, redirect folding, bounded
raw evidence), bound per-request through a ContextVar — a hand-rolled span context and the
sanctioned seam for any future tracing. Admin and provisioning surfaces have real audit
trails implemented as custom `APIRoute` classes that record 4xx/5xx as diligently as
successes (`routes/admin.py:54-91`, `routes/accounts.py:22-56`).

Absent: OpenTelemetry (zero packages, not even transitive), metrics, any error-tracking
SDK, a catch-all exception handler (an unhandled non-chat exception is an uncaught ASGI
500), inbound correlation headers, a DEBUG mode, credential-store read/write audit, and
login success/failure audit. Two deliberate postures shape any fix: tracebacks are
suppressed by design — error paths log `type(exc).__name__` only, so provider text and
prompts stay out of logs (`routes/chat_dispatch.py:280`) — and LiteLLM's telemetry control
plane is treated as an attack surface: `strip_dispatch_controls()` removes every callback,
langfuse/datadog key, and debug field from every request (`core/request_hardening.py:28-157`),
and the OpenRouter plugin classifies process-global LiteLLM callbacks as unsafe. Telemetry
must never ride LiteLLM callbacks here. Two traps: streaming (SSE) has no accounting, no
`_aigw`, no `gateway_call_id` at all; and `AIGW_TAXONOMY_ENABLED=false` silently removes
the only correlation mechanism in the app.

### scoreboard

Three stdlib loggers and no configuration module: `scoreboard.*` records fall through to
`logging.lastResort` — message-only on stderr, everything below WARNING discarded. This is
the exact bug the engine fixed for itself in `screamingface_engine/logs.py`, whose
docstring documents it; the scoreboard never received the equivalent.
`SCOREBOARD_LOG_LEVEL` is half-dead: plumbed chart → configmap → `uvicorn.run`, it governs
only uvicorn's loggers and never the app's. Jobs log via `print()` (visible in
`kubectl logs`, not filterable). What the scoreboard does well is diagnosis style: the
seed job's auth-proxy diagnostic (commit `20d88690`) names the likeliest cause in the
error ("a public hostname behind an authentication proxy answers 200 with a sign-in page:
engineUrl must name the in-cluster Engine address"), states consequence in the fallback's
own WARNING, records the trap at the config site in `values.yaml`, and pins it with a
behavior-named test over a real recorded fixture. Startup config guards fail loudly with
bypass-naming messages instead of silently 403ing (`main.py:110-176`). That style is the
house standard the rest of the roadmap should generalize.

Run traceability: the scoreboard records only successful published scores. The Engine's
`run_id` arrives as the `Idempotency-Key` header and as `metadata.run_id` — unindexed,
exposed on `GET /v1/scores/{id}` only, absent from leaderboard and history responses.
**A failed run leaves zero record anywhere** — the client raises before submission and
there is no failure table. The stored `url4_expression` is a re-run capability, not a
trace. Absent: OTel (the repo's traceparent chain terminates before this app; its one
outbound engine call sends no trace headers), metrics, error tracking, exception handlers,
client-side error capture, any "report a problem" affordance, and browser e2e tests.
`/healthz` is static and serves as both probes, so a DB-dead pod stays Ready.

### screamingface-engine

The best-instrumented component. W3C trace context is implemented end to end within its
own bubble: inbound `traceparent` validated at the edge (`rest/routes.py:479`), carried
into the Runner Job env re-validated (`adapters/k8s.py:268`), adopted or restarted per
W3C in `url4/streaming/lifecycle.py:199` — one `trace_id` per execution tree, every frame
carrying its own `traceparent` plus `tracestate: url4.parent=<span>`, pinned by
`test_traceparent.py`. Frames use OTel GenAI semantic conventions as their wire format
(`gen_ai.*` aliases in `url4/streaming/protocol/signals.py`); `url4/observe.py` is a
deliberately dependency-free observation port waiting for a downstream adapter.
`/metrics` exists with a genuine cardinality-DoS guard (route templates, never raw paths —
`metrics.py:70-108`), plus catalog and reaper collectors. WS close codes are preserved
and logged with duration/frames/heartbeats (`ws/bridge.py:201`). `serve --local` swaps
exactly two adapters (in-process runner, memory stream); everything above them is
production code.

The run-evidence problem: the NATS frame stream — the run's entire diagnostic record —
is **deleted 60 s after the run ends**, deliberately, in a `finally`
(`runner/main.py:100-140`); the Runner Job pod is GC'd at 120 s
(`ttlSecondsAfterFinished`); artifact spills >1 MiB have a 48 h TTL but are **inert when
deployed** — the chart mounts no shared volume (self-flagged at `job_env.py:236-238`,
`OME-892`), so `GET /artifacts/{id}` 404s. A failed deployed run is not reconstructable
after roughly two minutes. Compounding it: the run identifier (`topic`) is the JWT `sub`
and is treated throughout the engine as a bearer capability, so the design intent is that
it never be pasted into a ticket (**but see `OME-966` — it is already published for every
submitted score, and §4 establishes that topic knowledge alone in fact authorizes
nothing**); `trace_id` is never logged or returned over HTTP, so the
topic↔trace_id↔Job-name correspondence is recorded nowhere; and
`TerminatedData.error{code,message,permanent}` is discarded on the HTTP GET path — a
synchronous caller gets a bare `502 "the run failed"` (`rest/routes.py:282-298`).

Dead config: `URL4_CLOUD_LOG_LEVEL` is charted nowhere (no way to get DEBUG in a deployed
pod); `/livez` and `/readyz` are static literals unused by the chart (probes hit
`/healthz`); the `pods/log` RBAC grant is read by no code; `InProcessJobRunner.active_count`
is documented as a metric and registered nowhere. `/metrics` sits unauthenticated behind
the catch-all HTTPRoute. No traceparent is emitted on any of the three aigateway client
paths (`runner/connector.py:660`, `catalog/aigateway.py:202`, `connections/aigateway.py:199`)
— **the trace dies at the engine→aigateway boundary**. `logs.configure()` is bound to
`cli.main`, not `create_app`, so any other ASGI entry loses app logging.

### aigateway-ui

The BFF error taxonomy is well built: `AdminErrorKind` (8 kinds), 503 disambiguation via
`detail.code`, transport failures typed, secret scrubbing before render. But three modules
rethrow errors specifically "to reach the error boundary" and **no error boundary exists**
— no `error.tsx`/`global-error.tsx`, so production renders Next's generic digest page.
There is **zero server-side logging**: a 500 in the BFF logs nothing. No correlation
headers flow to aigateway (only `x-user-email` ties a UI action to a gateway log line).
The chart renders a `LOG_LEVEL` env that nothing reads.

### Infra, CI, docs

Azure ACR (+GHCR) via OIDC; k3s as the smoke target; Envoy Gateway + Cloudflare Access as
the auth proxy. No observability backend anywhere; SigNoz is named once as contemplated
follow-up (`apps/aigateway/DEPLOYMENT.md:304`). No ServiceMonitor/PodMonitor — nothing
scrapes the engine's `/metrics`. CI reports JUnit + coverage per lane but uploads no
failure logs or rendered manifests as artifacts; the aigateway and scoreboard images are
never built in CI. The url4-engine doctrine's F2 durable trace store and F3
`Link: /traces/{id}` remain design-only. `docs/spec/2026-08-13-websocket-disconnected-drops.md`
is the repo's de-facto incident report — three real causes invisible precisely because of
the muted root logger this roadmap fixes.

## 2. Live-k8s vs local-only

Usable against the live deployment today: `kubectl logs` (uvicorn access lines plus the
sparse app lines above), `helm test` pods, the engine `/metrics` via port-forward, the
`_aigw` envelope + `gateway_call_id` on non-streaming chat, the `AIGW_LIVE=1` suite
against `AIGW_LIVE_BASE_URL`, the WS frame stream while attached (and ~60 s after),
Plausible traffic analytics, Cloudflare Access logs, and a temporarily enabled nats-box.

Local-only: `serve --local`, the fake-OAuth harness (`AIGATEWAY_FAKE_*`), the client
`runtime.log` + `screamingface logs`/`status`, the mock runner, the `CredentialBlobProbe`
fixture, SQLite file reset, `--reload`.

Available in neither: log aggregation/search, trace visualization, dashboards/alerting,
error aggregation, post-hoc run reconstruction, and a DEBUG log level in any deployed pod
— all three level knobs are broken or uncharted.

## 3. Human report → evidence: the three missing legs

There is no reporting channel: no issue templates, no support address, no in-product
report affordance. The README says "open an issue" without linking one, and PyPI metadata
points at `ScreamingFace/screamingface/issues` while the portal and docs link
`OpenMined/screamingface` — the org repoint (`b28df175`) was only partially applied, so
the two halves of the product currently direct reporters to different places.

Connecting a report to evidence requires three legs, all absent today:

1. **An id the human can see at the failure moment.** Portal error states show none; CLI
   errors print none; the UI error page shows only Next's digest. The one exception:
   aigateway API callers do receive `gateway_call_id` in `_aigw`.
2. **That id on every log/trace record.** Today `gateway_call_id` is on one line and
   `trace_id` on zero.
3. **Evidence that survives until the report arrives.** Run evidence lives ~2 minutes; a
   human report lands hours later. Durable evidence is the prerequisite — without it every
   reporting channel dead-ends.

## 4. Empirical verification (2026-08-24)

Four probes drove the real code paths — aigateway through its own test fixtures, the
engine through `create_app` + `InProcessJobRunner` + `InMemoryEventStream`, url4's
streaming lifecycle directly, the scoreboard through a live app and DB — and captured
real output rather than reading source. The question was narrow: **are traces and logs
actually associated?**

**The answer is no.** The engine's trace machinery is genuinely correct *inside one
process*, and the trace never leaves that process.

### What holds

- **Adoption is strictly correct.** An inbound `traceparent` is adopted verbatim:
  `00-4bf92f…4736-00f067aa0ba902b7-01` produced
  `TraceContext(trace_id='4bf92f3577b34da6a3ce929d0e0e4736', root_span_id='0cbb06598aa3f6c6')`.
  The W3C restart rule is *stricter* than expected — a valid trace id inside a
  syntactically invalid header is discarded rather than salvaged, and all-zero trace,
  all-zero span, version `01`, and uppercase hex are all rejected. 9/9 malformed cases
  minted exactly one fresh valid id.
- **One trace per tree, with real parent edges.** A 10-frame nested run yielded
  `distinct trace ids: 1`, `distinct span ids: 7`, siblings sharing
  `tracestate=url4.parent=34e9878e59cb4905`.
- **No crosstalk under genuine interleaving**, not merely the serialized case.
- **`url4.observe` is already an OTel-shaped stream** — `RunStarted` carrying
  `(trace_id, root_span_id)`, matched `NodeStarted`/`NodeFinished` with explicit
  `parent_span_id`, `RunFinished`, and injected identity adopted verbatim. The Phase 2
  exporter is a small adapter, not a rewrite. Gap: node events carry no timestamps, only
  `engine_seq`.

### What is broken, with the observation that proves it

- **Engine → aigateway carries no trace context.** During a run whose frames all carried
  `4bf92f…4736`, the complete header set received by a capture server was
  `Host, Accept, Accept-Encoding, Connection, User-Agent, X-User-Email, X-Profile,
  Content-Length, Content-Type` — `traceparent present? False`. Same for the catalog and
  connections paths; `/v1/providers` omits `X-Profile` too.
- **aigateway never *reads* the header.** Instrumenting `Headers.get/__getitem__/
  __contains__` showed the entire chat path looks up exactly two request headers:
  `Authorization` and `X-Profile`. There is no half-built ingestion to finish.
- **The client originates nothing.** Captured start-request header keys were
  `['accept','accept-encoding','connection','content-length','host','user-agent']`;
  `traceparent present? False` on both the HTTP start and the WS upgrade. → `OME-967`.
- **url4's own outbound hops drop it too.** A real `HttpIOLayer` fetch under an explicit
  trace sent `['accept','accept-encoding','connection','host','user-agent']` —
  `ANY downstream request carried a traceparent? False`.
- **No log record anywhere carries a trace id**, in any of the three services.
- **The scoreboard emits no application log lines at all.** With
  `SCOREBOARD_LOG_LEVEL=debug` and root forced to DEBUG, an unfiltered handler captured 25
  records around a 201 — `records from a 'scoreboard.*' logger: 0`.
- **`run_id` is not queryable.** `Score.filter(run_id=…)` → `FieldError: Unknown filter
  param 'run_id'`; no column, no index on `metadata`. Its only indexed home is
  `idempotency_keys.key` (PK, 24 h TTL, no route).
- **The terminal HTTP path flattens the cause.** A real aigateway 402 through the whole
  spine produced `HTTP 502 {"detail":"the run failed"}` with no `traceparent` header,
  while the WS `terminated` frame held
  `{"code":"aigateway_http_402","message":"aigateway request failed with status 402"}` —
  and the gateway's own `"upstream provider is out of credit"` had already been dropped a
  hop earlier. Diagnosis narrows twice.

### What a code reading got wrong, optimistically

These are the findings that justify running the audit rather than reading the source:

- **A 500 can be completely silent.** A mapped litellm `APIConnectionError` returns
  `provider_unavailable` and logs **zero** WARNING/ERROR records — an operator alerting on
  WARNING+ sees nothing. `routes/chat.py` has an `except` block that logs, so the reading
  says "logged"; the mapped branch never reaches it. → `OME-968`.
- **A successful stream is entirely anonymous** — 0 records, no id in logs, SSE body, or
  headers. A failed stream logs only the plugin class name, with HTTP status still 200.
- **`AIGW_TAXONOMY_ENABLED` is an observability kill-switch, not a feature flag** —
  flipping it false removes `call_` from logs, body, and headers simultaneously.
- **`metadata` is unbounded on the public write path** — a 64 KB blob returned 201
  (`stored metadata bytes=65570`), 10-level nesting returned 201; the bounding validator is
  attached only to the operator baseline paths. → `OME-969`.
- **Content-hash dedup asserts a false identity** — `RUN-SECOND`'s caller received `200`
  with `run_id: "RUN-FIRST"`. `Idempotency-Key` and `metadata.run_id` are never
  cross-checked; the scoreboard source contains zero occurrences of `run_id`. → `OME-970`.
- **A load-bearing docstring is wrong.** `url4/streaming/protocol/envelope.py:25` says
  `subject: """The run == <trace_id>."""`; the observed `subject` is the *topic*, and the
  SDK maps `Event.run_id` from it — which is how the capability became public. → `OME-966`.
- **The topic-in-logs "leak" is not a leak.** Every topic-referencing route reads the
  topic out of a *verified* token, so topic knowledge alone authorizes nothing. Provable
  only by trying to use it as a credential — which a code reading would not do.
- **The client already holds the traceparent and nothing can use it.** It reaches
  `sf.Event.traceparent` on every event; there are 5 occurrences in client source and
  **zero read sites**; `ExecutionError` exposes only
  `['code','details','hint','message','permanent','status']`.
- **The sampled flag is silently forced** — an inbound `-00` is re-stamped `-01`, because
  `format_traceparent` hardcodes `_SAMPLED = "01"`.
- **Inbound span ids are discarded** — the trace id is adopted but a fresh root span is
  minted, so a caller's parent span cannot be joined.

### The limits of this audit

Everything ran in-process on one laptop; there is no cluster context configured on this
machine. Therefore **this audit speaks to code wiring only and cannot speak to deployment
reality**. Specifically unobserved: the `K8sJobRunner` env hop
(`URL4_CLOUD_TRACEPARENT`) — inferred correct from a repo unit test, not run; whether
Cloudflare Access strips, rewrites, or *injects* `traceparent`/`cf-ray`; NATS/JetStream
sequencing, retention, redelivery and gap behavior (all frames went through the in-memory
stream); multi-replica topic routing (the engine itself logs that the reaper "assumes a
single replica"); the production log formatter and level; **whether
`AIGW_TAXONOMY_ENABLED` is actually true in deployed values**, which decides whether any
request id exists at all; egress propagation to providers; per-plugin logging for the
seven non-Anthropic providers; Postgres-side indexes (findings came from live SQLite DDL);
cost attribution (`Usage`/`ModelResponse`/`scope="self"` events were never produced by the
static IO layers); and the UI → aigateway hop, which no probe touched.

One instrumentation blind spot is recorded rather than hidden: aigateway's header capture
covers lookup by key, not iteration (`headers.items()`).

## 5. Locked decisions (owner, 2026-08-22)

- **Backend: SigNoz, self-hosted.** One OTLP-native system for traces+logs+metrics; a
  single chart fits the `charts.yml` gating model; it is the backend `DEPLOYMENT.md`
  already contemplated. The ClickHouse resource floor on the k3s nodes must be validated
  at the Phase 2 spec stage before committing.
- **Traceback posture: split.** Full tracebacks become allowed on non-dispatch paths
  (auth, admin, DB, config); the dispatch path stays class-name-only because exception
  text there can embed provider/prompt content. **This amends the aigateway security
  posture stated at `routes/chat_dispatch.py:280`** — recorded here as the authoritative
  amendment.
- **Retention: 30 days, full bodies.** Exported run evidence includes prompt-bearing
  frame bodies — a deliberate divergence from the aigateway class-name-only log posture,
  chosen for complete run reconstruction. It is acceptable only because the sink stays
  Cloudflare-Access-gated; the divergence is confined to the SigNoz store and must never
  leak back into pod logs. Failed-run hot retention stopgap: 24 h.
- **Error tracker: none for now.** A Sentry event scrubbed to this posture degenerates to
  the structured log line the backend will already hold; backend alerting covers paging.
  Revisit ~90 days after Phase 3; if wanted then, self-hosted GlitchTip — provider text to
  a third-party SaaS is a hard no.

## 6. Roadmap

Four phases, each an epic; every sub-issue is one SDLC unit and one PR. Phase 0 is filed
(epic `OME-935`); Phases 1–3 are filed as separate epics when their turn comes.

**Keystone, ahead of every phase: `OME-967` — the client originates the traceparent.**
Because the trace id is currently minted inside the Runner Job and never returned, every
failure occurring *before the first frame* (capability mint, run start, WS handshake) has
no id of any kind and is unjoinable forever — and that class is a large share of what
users actually hit. The engine already adopts an inbound traceparent, so this is a
client-side change with no server work, and it is the precondition that makes both the
correlation chain and any evidence bundle joinable by construction rather than by luck.

**Phase 0 — existing signals become consumable** (no new infra, no cross-app contracts,
all items independent): this spec (`OME-936`); scoreboard `logs.py` copying the engine
pattern (`OME-937`); `gateway_call_id` on every aigateway log line via a contextvar
injector that wraps — never replaces — the redaction record factory (`OME-938`); an
aigateway catch-all handler, class-name-only + call id (`OME-939`); engine run-identity +
terminal-evidence lines on the control plane — trace_id, topic *digest*, job name at
schedule; outcome, `TerminatedData.error`, close code, drop counts at termination
(`OME-940`); surfacing `TerminatedData.error` + trace_id on the HTTP GET path (`OME-941`);
the engine dead-config sweep (`OME-942`); aigateway-ui `LOG_LEVEL` wire-or-delete +
minimal BFF error logging (`OME-943`); scoreboard DB-aware readiness (`OME-944`); the
org-repoint hygiene fix, shipped first (`OME-945`); and the retention stopgap — Job TTL to
1 h, failed-run streams kept 24 h via per-stream MaxAge instead of the explicit delete
(`OME-946`).

**Correction to `OME-946`:** a TTL change alone is insufficient. `_sweep_orphans`
(`adapters/jetstream.py:166-179,194-230`) deletes terminal streams older than 60 s
whenever the store is full, so 24 h retention silently degrades to 60 s exactly when the
cluster is busy — which is when failures cluster. The sweep predicate must change too.
Note also that `max_bytes` is a reservation charged at stream creation (~200 streams
against the current store), so retention trades directly against run concurrency.

**Phase 1 — one trace, end to end** (requires `OME-938`): engine emits `traceparent` on
its three aigateway client paths; aigateway accepts it as untrusted input, joins it to the
log contextvar and echoes `_aigw.trace_id`; SSE responses carry the ids as headers;
aigateway-ui gains `error.tsx` and emits traceparent from the BFF; the scoreboard adopts a
documented `metadata.trace_id` convention, promotes `run_id` to an indexed column, and
sends trace headers on its engine call. Payoff: one trace_id greppable across every pod's
`kubectl logs` with zero new infrastructure.

**Phase 2 — a place for signals to live**: deploy SigNoz behind Cloudflare Access; build
the frame→OTLP exporter adapter at the engine control-plane relay — the frames are
already OTel-shaped, the OTel dependency stays confined to the engine serve-mode adapter
(never url4 core, never the runner, never the other apps), and emit-time export makes the
backend the durable evidence store, superseding the design-only F2; wire scraping for
engine `/metrics` and simultaneously remove it from public routing; add `/metrics` to
aigateway (fed from the accounting handler's existing latency measurement) and
scoreboard; alerting rules in the backend; then shorten the hot NATS retention back down.

**Phase 3 — humans can report, reports join to evidence** (parallel with Phase 2; needs
only 0–1): issue templates with trace_id/gateway_call_id fields; the client CLI printing
trace_id + a prefilled report URL on failure (never the topic); portal error states
showing a request id with a report link; the UI error page likewise; and a runbook —
"report trace_id → evidence" — with the `kubectl logs` grep crib pre-backend and the
SigNoz query post-backend.

### Phase 3 direction: the reported unit is client-assembled

The goal is a report that arrives as a single unit with its telemetry attached. Design
research settled three things about how to get there.

**Assemble client-side, not server-side.** The client is the only component present in
every audience's failure. Server-side assembly (replaying frames for a given run) would
require retention changes, a trace→topic index that exists nowhere, a second longer-lived
read token, and the `OME-892` volume fix — and it walks into a real hazard: subscribing to
a reclaimed topic recreates an empty stream holding a full byte reservation and then hangs,
reachable merely by asking about a missing run. Phase 2's SigNoz export supersedes that
path entirely and covers successful runs too.

**Two content classes, and the class gates the destination.** Class S (shareable, default)
carries envelope facts only — trace_id, versions, benchmark and spec ids, failure class and
error code, timings, close code, and the event stream folded to *structure* (kinds,
sequence, span names, `gen_ai.*` attributes, token counts, finish reasons) plus a
structurally redacted url4 expression. Safe for a public issue. Class C adds prompt
strings, log bodies, and error details, is opt-in per invocation, and may only reach the
Access-gated sink — never a public issue tracker.

Two hazards make this non-negotiable rather than fussy. The url4 expression carries prompt
text *structurally* and travels as a GET query string, and uvicorn access logging is on in
the local runtime, so **`runtime.log` already contains user prompts today**. And
`~/.screamingface` holds live credentials — Claude Code OAuth access *and refresh* tokens
in `aigateway.sqlite3`, a live `owner_token` in `runtime.json`. Collection must therefore
be **allow-list, never a directory sweep**, and must never capture frame locals around
`connect()` (the API key is a keyword argument) or touch the `Cf-Access-Token`.

**Delivery is blocked on a rule amendment.** CLAUDE.md rule 9 — "API tokens / raw GraphQL
are forbidden" — has no subject and on its literal wording catches product code calling
Linear's API, not only agent tooling. Ranked options: an agent files via MCP during triage
(zero credential, unambiguously compliant, but no ticket id back to the reporter); a GitHub
App creates an issue that Linear's GitHub sync mirrors (real-time, short-lived
installation token, needs `.github/ISSUE_TEMPLATE` and `OME-945` first); or product code
calls `issueCreate` directly, which requires amending rule 9 in writing the way the
traceback-posture amendment was recorded here. A public intake endpoint also introduces the
repo's first unauthenticated write that reaches humans, in a codebase with no rate limiting
anywhere — so rate limiting and a bot gate are part of that option, not a follow-up.

## 7. Verification

Phase 0: per-app `run_gates.py` green; behavior-named tests in house style ("a log record
carries the gateway_call_id of the request that produced it"; "a terminated run leaves a
control-plane evidence line"; "readyz fails when the DB is down"); chart edits pass
`verify_chart_wiring.py`; `kubectl logs` on a dev deploy shows id-carrying lines;
`AIGW_LIVE=1` stays green. Phase 1: a cross-hop test pins trace_id equality from the
engine-emitted header through the aigateway log line to `_aigw.trace_id`; one trace_id
greps across two pods. Phase 2: a dev benchmark run's full span tree is findable in
SigNoz by trace_id after its stream deletion; `/metrics` is unreachable from the public
hostname. Phase 3: a test report filed through the template with a real failed run's
trace_id leads, via the runbook, to the evidence.

File:line references were verified against the working tree at the time of the audit
(2026-08-22, main ≈ `7e74662c`); they are evidence anchors, not live links.
