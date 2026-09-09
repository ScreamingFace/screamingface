# Phase-one session analytics — OME-1124

Status: draft for review, 9 September 2026. Updated for service-first delivery; OME-1152 is the first implementation unit. Scope and consent-only bridge exception confirmed by owner; proposed defaults below are not implementation approval. Parent: https://linear.app/openmined/issue/OME-1060 . Child: https://linear.app/openmined/issue/OME-1124 . Code inspected at `0dc1b845`.

## Delivery sequence update

Owner confirmed one layer per implementation unit: ingestion/PostHog service first (OME-1152), SDK local foundation/events second, service Colab bridge third, SDK Colab adapter fourth. The [OME-1152 contract](2026-09-09-OME-1152-analytics-service-spec.md) is authoritative for initial wire fields and delivery semantics. Discovery/review events below are a later additive contract proposal, not in the initial four-event schema. Scoreboard database aggregates are deferred; client submission-success events cover the first observed funnel. No immediate gateway exactly-once guarantee: stable keys support eventual PostHog deduplication.

## 1. Outcome and boundaries

Measure opted-in evaluation activity and repeat usage without requiring identity association. WAS means distinct active session IDs in the trailing seven days. Weekly active browsers and installations count distinct persistent IDs with qualifying activity, separately by scope. Neither counts verified people; never sum surfaces as unique users. No account/email association, identity-linking prompt, PostHog identify/alias calls or automatic website-to-Colab join in phase one. Website instrumentation remains OME-1128. Desktop/remote notebook integration beyond current SDK usage is future work, not implicitly delivered here.

Confirmed exception: the Colab bridge may contact our server solely to retrieve remembered consent before analytics is enabled. It must create no analytics identifier and send no analytics event until consent. This supersedes the unqualified no-request wording only for this consent control path. Disable controls override even the bridge load. Consent requests must not feed PostHog, access-log analytics or consent-rate dashboards.

## 2. Evidence and actual integration seams

Paths below are repository-relative, verified at the inspected revision.

| Source | Finding / implication |
|---|---|
| `packages/screamingface/src/screamingface/client.py` | Separate Client and AsyncClient; evaluate dispatches Recipe and raw URL4 paths. Instrument public workflow boundaries once, not HTTP requests or individual Engine calls. Login/logout remain unrelated to analytics. |
| `packages/screamingface/src/screamingface/_default_client.py` | Lazy process-wide Client; configure replaces it. Reconfiguration must not create a new analytics session. Automatic local-service discovery already exists. |
| `packages/screamingface/src/screamingface/_evaluation/runner.py` and `_evaluation/url4.py` | Both paths decode and reconcile the report before returning. Worker fan-out and progress callbacks must not create extra evaluation events. |
| `packages/screamingface/src/screamingface/report.py` | Report.ok requires no failures and scored candidates. A returned Report can be non-ok. Export/serialization contains sensitive research data; never serialize it into telemetry. |
| `packages/screamingface/src/screamingface/_engine/catalog.py` | Public model get is also called during evaluation preflight; suppress nested discovery telemetry. |
| `packages/screamingface/src/screamingface/_scoreboard/leaderboards.py` | Sync/async submit uses CandidateResult.run_id as submission Idempotency-Key. Analytics must use its own random operation ID, never this execution ID. |
| `packages/screamingface/src/screamingface/_runtime/config.py` | Runtime data defaults to ~/.screamingface or SCREAMINGFACE_DATA_DIR. It holds service state/databases; no analytics consent store exists. |
| `packages/screamingface/src/screamingface/_runtime/cli.py` | CLI commands manage runtime up/down/restart/status/logs/doctor/prepare. There is no evaluate command to instrument. Runtime startup is not an active evaluation session. |
| `packages/screamingface/src/screamingface/_environment.py` | Detects notebook capability, not Colab specifically. Generic notebook detection must not imply Colab origin. |
| `packages/screamingface/scripts/build_notebooks.py` | Generated notebooks must stay deterministic and output-free; never embed consent, IDs or captured experiment output. |
| `apps/scoreboard/src/scoreboard/scores/models/score.py` | Persisted Score rows and submitted_at support authoritative accepted-submission aggregates. Keep those separate from observed SDK submission attempts. |

No existing apps/analytics deployment or PostHog instrumentation was found in the inspected SDK. A deployable analytics gateway is a new landing, not an SDK-internal server.

Experiment evidence: HTTPBin server-set partitioned cookies passed full restart and independent notebook/fresh runtime recovery in Chrome151 and Safari26.5.2. Earlier direct-output storage and Safari localStorage/JavaScript-set attempts failed relevant continuity checks. One-day expiry only; consent tests used a separate localStorage harness. The production paths, cookies and consent protocol below must be retested. Evidence: [notebook A](https://colab.research.google.com/drive/1YAX15Y1jMRHDq_i1dp0hxJwMUfJCMjoE), [notebook B](https://colab.research.google.com/drive/1o0mD4PV9diiJYLhetgfspmYyOT2qM4vV).

## 3. Identifier and session contract — proposed defaults

- Persistent ID: random UUID, scoped as browser or installation; never derived from email, hardware, IP, hostname, credentials or execution data. Browser profiles/devices are separate. It is an analytics label, never authorization.
- Session: process/kernel-wide coordinator shared by Client/AsyncClient and module wrappers. Create lazily on the first consented tracked operation. Rotate after 30 minutes of inactivity with no active operation; a running evaluation pins its session through completion. Kernel/process restart starts a new session. Separate processes have separate sessions but may share an installation ID. Configure/close of one Client does not rotate a still-used process session. Forked children reset in-memory sessions and worker queues.
- Concurrent evaluations share the session but have separate analytics operation IDs. Session-only fallback uses a distinct scope and no persistent identifier, only when consent is already known accepted. Unknown/unavailable consent means no events, not session-only tracking.
- WAS qualification proposal: a Report returned after reconciliation counts as a completed user-facing evaluation, matching the parent's current completion definition. Emit report_ok separately; an ok-only health metric counts the stricter Report.ok subset. A returned non-ok report must never be presented as error-free. Owner must approve this distinction before implementation.
- Active window uses completion-event time in UTC, trailing seven days. Long evaluations remain on their starting session even across midnight; they qualify on completion. Missing terminal events are unknown, not inferred failures. Session starts do not themselves qualify for WAS.
- origin remains colab/local/unknown; add host_environment=colab/local_jupyter/remote_jupyter/python/cli/unknown where explicitly known. execution_mode=local/hosted/unknown is independent and per operation. Use explicit integration metadata or verified local-service discovery; no raw endpoint URL leaves the process. Unknown custom endpoints stay unknown.

## 4. Consent and persistence

State machine: unknown -> accepted or declined; accepted -> declined on opt-out; stale policy -> unknown. Unavailable storage is a capability failure, not an acceptance. No events buffered before consent and no retroactive replay of pre-consent activity. If consent arrives mid-evaluation, start tracking subsequent operations only.

Local proposal: ~/.screamingface/analytics.json, independently overridable by an explicit SCREAMINGFACE_ANALYTICS_CONFIG path. Do not inherit arbitrary shared runtime --data-dir locations. Versioned document contains choice, consent version, expiry and optional installation UUID. Atomic writes, process lock, owner-only permissions; read before each operation/dispatch. No machine-wide file or notebook/project file. Local Jupyter and CLI share this only under the same OS user/config path. Unwritable state yields explicit session-only acceptance or analytics off; do not claim persistence. Never automatically generate an ID just by importing the package.

Proposed controls: sf.analytics.status(), enable(), disable(), reset_identifier(); CLI screamingface analytics status/enable/disable/reset-id. These are new APIs, not current ones. Disable clears queued events and the local ID and persists declined; reset rotates only with accepted consent and makes no identity merge. Historical deletion remains a separate disclosed request flow. Retain old-ID deletion capability only if the user deliberately requests deletion before reset; do not promise recoverability after identifiers are lost.

Prompt placement: one nonmodal analytics choice at explicit connection/setup or first interactive use, not in a constructor/import, repr or evaluation critical path. Dismissing leaves off and suppresses repeated prompts in that process. Noninteractive/headless defaults off, with explicit configuration required. A notebook run proceeds without waiting for a choice. Precise copy and accessible visual design need the brand skill during implementation; this document does not prescribe finished UI copy.

Proposed retention for review: 90-day fixed ID lifetime; 180-day consent-choice lifetime, refreshed only by a new user choice. Renew an expired identifier only while valid consent remains; no linking old/new IDs. Clearing cookies can lose a decline as well as acceptance. These durations are untested proposals, distinct from 84-day raw-event retention.

DO_NOT_TRACK truthy values and explicit process disable win over saved acceptance and suppress all analytics/control-plane requests. Corrupt or unrecognised settings fail off. App authentication has no effect on analytics consent or identifier in this phase.

## 5. Colab bridge and service contract

Deploy a dedicated ScreamingFace-controlled HTTPS origin, name to be chosen at deployment. Never ship the HTTPBin fixture. Separate consent and identifier request paths so loading consent does not automatically transmit a previously stored analytics cookie:

| Endpoint (proposed) | Contract |
|---|---|
| GET /bridge/consent | Minimal iframe HTML; no PostHog, third-party scripts, analytics ID cookie or unique request token persisted. |
| GET /bridge/consent/state | Return unknown/accepted/declined and consent version/expiry; read consent cookie only. |
| POST /bridge/consent | Persist explicit choice and version; no analytics identifier minted here. |
| POST /bridge/id | Only after accepted state: read or server-set ID cookie; return opaque ID in JSON. Server validates accepted consent cookie before issuing ID. |
| POST /bridge/id/revoke | After explicit opt-out: expire ID cookie, invalidate outstanding bridge analytics capability; consent has already been set declined. No analytics event. |
| POST /v1/events | Allowlisted ingestion; browser/installation/session scope and consent version. Bounded batches. No product auth token. |

Cookie proposal: Secure; SameSite=None; Partitioned; HttpOnly, host-only (no Domain). Consent cookie Path=/bridge, with no random per-user value; identifier cookie Path=/bridge/id. Fixed expiry as above. Path limits which requests carry cookies; it is not a security boundary. HttpOnly means the service returns the ID as JSON instead of JavaScript reading document.cookie; this differs from the tested fixture and requires fresh browser verification. No identifier in URLs, notebook output, HTML or access logs. Control endpoints use Cache-Control: no-store, no redirects and no referrer.

Parent validates iframe source, exact bridge origin, version, request nonce and response schema. Child accepts messages only from its parent and the observed Colab output-origin pattern, with narrowly scoped command allowlist; rejects null origin and arbitrary destinations. Reply only to validated exact origin, never '*'. Deployment CSP frame-ancestors must cover the actual full Colab ancestor chain; validate from browser tests rather than assuming the output host is the top-level site. API CORS must not be broadly credentialed. No browser extension/Storage Access permission or extra login required by design.

Retain a consent observer while the notebook is active, check accepted state before dispatch, and propagate revocation between active bridge instances via a tested notification/polling mechanism. Local processes reread shared consent. Clear in-flight capability/queues on decline. Cross-notebook instantaneous revocation and stale-runtime sends require an expiring service-issued capability plus server revocation check; design that control capability separately from any product credential. If this coordination cannot be validated, do not claim global immediate opt-out. Requests already accepted before opt-out may complete; historical deletion is distinct. The ingest service cannot cryptographically prove human consent from arbitrary local SDK clients; validation and rate limits are not user authentication.

Failure contract: no network or Colab eval_js wait inside evaluate's critical path. Bridge initialization occurs in a separate adapter task; two-second outer deadline, ignore late results with a generation token and cancel/retire the task. Bound active tasks and retries; maximum one initialization per process at a time. If consent/ID isn't ready at operation start, skip that operation or use session-only only for known accepted consent. No delayed ID creation after disable. Colab thread/kernel integration and cancellation are unproven: a required spike must establish that the real evaluation proceeds while initialization hangs. Otherwise ship local analytics first and keep Colab disabled until resolved.

## 6. Public operation inventory

Apply each row equally to sync/async and module wrappers. A context-local outer operation guard suppresses nested calls and must propagate through worker boundaries.

| Surface | Classification / event |
|---|---|
| models.list/get, benchmarks.list/get | Direct discovery_completed on successful explicit calls, with catalog/action enums only. Internal preflight calls and display-triggered loads suppressed. |
| Model, Fusion, Pipeline, CorrectiveLoop, SelfCorrective, Recipe.then, Url4/to_python | Untracked pure composition/serialization. Represent composition via coarse workflow=recipe/raw_url4 on evaluate; no constructors or expression contents sent. |
| Client/AsyncClient.evaluate (Recipe or raw URL4), sf.evaluate | evaluation_started + evaluation_finished, one pair per public invocation. finished outcome=returned/failed/cancelled; returned includes report_ok boolean. Suppress nested retries/fan-out. Validation exceptions count failed attempt, never active success. Re-raise original exceptions/cancellation unchanged. |
| Report repr/HTML, properties, cases, to_dict/to_json/export; recipe/client/catalog repr | Untracked: automatic render is not user intent and serialization contains research data. Review engagement is not fully measurable in phase one. |
| leaderboards.list/get/get_score | discovery_completed or review_completed for explicit successful calls; no IDs, benchmark names or score values. |
| leaderboards.submit | submission_started/finished for one explicit invocation, outcome=returned/failed/cancelled. A replayed accepted response is an observed attempt, not a new persisted score. No authors, submitted_by, score_id or run_id. |
| connect/disconnect; connections list/get/connect/start_oauth and OAuth polling | Untracked in first increment: configuration polling/auth may reveal sensitive context; later coarse workflow event requires explicit scope review. No OAuth URLs or tokens. |
| login/logout, configure/close/context-manager entry/exit | Untracked infrastructure/auth; no identity linking. |
| CLI up/down/restart/status/logs/doctor/prepare and internal service commands | Untracked runtime administration. CLI analytics controls change local preference, not evaluation counts. |
| Event/on_event and Engine retry/run/token APIs | Untracked internal facts; never forward raw events or attach another analytics handler that changes callback behavior. |

## 7. Payload, delivery and reporting

SDK core owns small AnalyticsSink/ConsentStore/ContinuityProvider ports; adapters provide local file, Colab bridge and HTTP delivery, composed at Client wiring. Core never imports adapters, browser runtime or PostHog. Share one coordinator; do not copy sync/async business rules.

Allowlist: schema_version, event_id (random analytics dedup key), operation_id (random, not execution trace), session_id, optional persistent_id, id_scope=browser/installation/session, consent_version, sdk_version, surface, origin, host_environment, execution_mode, workflow, action/catalog enums as applicable, outcome, report_ok on returned evaluation only, duration_bucket, UTC timestamp. Proposed buckets: under_1s, 1_10s, 10_60s, 1_10m, 10_60m, over_60m. Reject unknown fields, invalid combinations and oversized/high-cardinality strings. No raw URLs, exceptions, prompts, outputs, metrics/score values, model names, credentials, email, authors, run/trace IDs, hostnames, dependency inventory or fingerprints.

Irina's request for benchmark/provider/cost/cache-hit context remains open. Proposal: exclude these from the first allowlist pending separate approval of bounded public enums/buckets and measurement definitions; do not silently treat this draft as rejecting the request.

Delivery proposal: memory-only queue up to 100 events; batches up to 20, event size <=4KiB. Background HTTP with two-second request deadline, bounded exponential retries (at most two) for transient failures; same event_id on retries. Drop on overflow/exit/disable; no durable client spool, shutdown wait <=250ms. Gateway validates at most 64KiB per request, applies body limits before decoding and rate limits; identical batch duplicates collapse and cross-request duplicates use eventual PostHog deduplication; count accepted and dropped batches operationally without identifier logs. Invalid payloads are rejected, never forwarded. Initial service returns success only after upstream HTTP acceptance, not queryability or guaranteed uniqueness. OME-1152 specifies bounded synchronous forwarding within an asynchronous request, without durable storage.

Gateway maps distinct_id to namespaced browser/installation ID, or session:<session_id> fallback. Set anonymous/personless processing and disable GeoIP; never forward caller IP/User-Agent or auth headers. No identify/alias, session replay, autocapture or person properties. Use one project destination shared with OME-1128 but explicit event surface. Pin SDK and verify dedup/event-time/personless behavior against a test project before production. Do not assume PostHog built-in browser sessions equal our WAS; query explicit session_id.

Raw events: proposed 84-day maximum; enforce in PostHog and any later durable stores/backups with verified deletion policy. Initial service has no durable event/dedup store. Identifier cookie lifetime is a separate setting. A deployment with no enforceable retention cannot pass acceptance. Restrict dashboard/admin access; isolate development and automated events in a separate test destination.

Dashboards: WAS; weekly active browsers/installations by scope; persistent-ID coverage among observed consented sessions; first-observed-to-repeat cohorts (not first-ever users); started/returned/failed/cancelled/unknown evaluation health; report_ok subset; observed evaluation-to-submission sequence per scope/session. No causal per-evaluation attribution without an approved in-memory association, and no report-ID join. Scoreboard database aggregates are deferred beyond the first slice; no fake person ID for aggregate events. Declined/off users are absent: no global opt-in rate or total-user claim.

## 8. Review decisions and release gates

Confirmed: phase-one anonymous scope; consent-only bridge request exception. Proposed for owner review: 30-minute sessions, returned-report qualification versus report_ok, ID/consent/event retention, excluding optional properties initially, and service ownership/deployment.

Release requires: zero event/ID creation before consent; bounded nonblocking real evaluation under bridge failure; opt-out including stale runtimes; local concurrent persistence; sync/async/URL4/retry parity; actual hosted Chrome/Safari reload/restart/fresh notebook, blocked storage and private-mode matrix; expiry/deletion; payload and PostHog mapping validation; local Jupyter/CLI configuration sharing; disclosure and historical deletion procedure. Cookie availability is not login or trust. Neither proposal nor experiment is release approval.

## Sources

- [MDN Set-Cookie](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Set-Cookie): Path, HttpOnly and partitioned-cookie attributes; used for the proposed split-path protocol.
- [PostHog Node documentation source](https://github.com/PostHog/posthog.com/blob/master/contents/docs/libraries/node/index.mdx): anonymous capture/person-profile control and GeoIP configuration. Implementation must pin and test the chosen SDK/API.
- Linear OME-1060 and OME-1124 descriptions/comments; source files at the revision above; linked live experiment notebooks. Earlier statements of universal impossibility are superseded by the bounded positive server-set results.
