---
title: Debugging & traceability review — inventory, gaps, phased roadmap
ticket: OME-936
status: approved
date: 2026-08-22
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
after roughly two minutes. Compounding it: the run identifier (`topic`) is a bearer
capability — the JWT `sub` — so it cannot be pasted into a ticket without leaking the
right to stop/redeem the run; `trace_id` is never logged or returned over HTTP, so the
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

## 4. Locked decisions (owner, 2026-08-22)

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

## 5. Roadmap

Four phases, each an epic; every sub-issue is one SDLC unit and one PR. Phase 0 is filed
(epic `OME-935`); Phases 1–3 are filed as separate epics when their turn comes.

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

## 6. Verification

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
