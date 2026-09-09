# Analytics ingestion service — OME-1152

Status: proposed contract for docs-PR review. Parent: https://linear.app/openmined/issue/OME-1060 . Service issue: https://linear.app/openmined/issue/OME-1152 . SDK consumer: OME-1124. Review and merge this docs PR before a separate implementation PR. No application code is included.

## Scope and architecture

Add an independently deployable Python/uv/FastAPI service at apps/analytics, following repository app conventions like apps/report-intake. It receives opted-in product events and forwards an explicit allowlist to PostHog. It never imports another app's internals. Core defines ingestion/validation and an EventDelivery port; HTTP/PostHog adapters implement ports and application wiring composes them.

First increment contains event ingestion, PostHog mapping, bounded delivery, health/configuration, operational limits and synthetic tests. No browser cookie or consent endpoints, SDK edits, account linking, website instrumentation, database submission totals, dashboard rollout or new ORM/database. The browser bridge follows as a separate service-only issue. The gateway does not prompt users; SDK consent enforcement follows in OME-1124.

Service-first order: OME-1152 -> SDK local consent/IDs/events -> service Colab bridge -> SDK Colab adapter. Contract tests and synthetic requests allow each layer to ship independently. Service deployment alone enables no SDK telemetry.

## HTTP contract

Proposed routes:

| Route | Behavior |
|---|---|
| GET /healthz | 200 while process runs; no external calls or secrets. |
| GET /readyz | 200 when required settings are valid and service accepts requests; 503 while draining. Not a claim that PostHog is currently reachable. |
| POST /v1/events | application/json envelope with schema_version=1, consent_version="1", consent_granted=true, events array of 1–20 events. Unknown fields forbidden at every level. |

Reject non-JSON 415, malformed JSON 400, schema/consent/event mismatch 422, request >64KiB or event >4KiB 413, local/edge rate limit 429 with bounded Retry-After, disabled/draining/temporary delivery failure 503. Never echo bodies, property values or upstream error text. Invalid batch rejects wholly before forwarding anything. Enforce streamed body cap before parse, including chunked requests; reject compressed bodies in v1 to avoid decompression ambiguity.

Return 202 {"status":"upstream_accepted","count":N} only after an upstream successful ingestion response. This means PostHog's HTTP boundary accepted the batch, not that it is queryable, unique, or permanently retained. Do not acknowledge an in-memory queue as durable success. A permanent PostHog rejection returns 502 {"code":"upstream_rejected"}; operators inspect redacted status counters. No client retries of 4xx/502; transient 429/503 may be retried with identical events. An upstream partial/ambiguous result is not whole-batch success; return 503 and preserve duplicate keys on replay. Document any provider-specific partial-response interpretation in adapter tests before deployment.

No durable service queue/database in this increment: validate and attempt forwarding within a single asynchronous request with a total 1.5-second wall-clock budget. At most two total upstream attempts, including 100ms jittered backoff, only on transport ambiguity, 429 or 5xx while budget remains. Honor Retry-After only within remaining budget; otherwise return 503. No redirects and no automatic retries outside this budget. This keeps the proposed SDK's two-second request deadline compatible. If the caller disconnects, stop unsent attempts; an already transmitted request cannot be recalled.

## Event schema v1

Envelope carries consent version/affirmation; events cannot override it. Client affirmation is a contract, not proof of human consent or authentication. Request bodies may be forged; these are observed product-usage metrics, not trusted billing or audit records.

Required common fields: event_id, operation_id, session_id (canonical random UUIDv4 strings); event (enum below); timestamp (UTC RFC3339 ending Z, millisecond precision, at most 24 hours old or five minutes future); id_scope (installation/browser/session); sdk_version (bounded version string, max 64 chars, constrained version grammar); surface (python_sdk/cli); interface (sync/async); origin (colab/local/unknown); host_environment (colab/local_jupyter/remote_jupyter/python/cli/unknown); execution_mode (local/hosted/unknown); workflow (recipe/raw_url4/submission). Optional persistent_id is UUIDv4, required for browser/installation and forbidden for session scope. All values are bounded enums except constrained version/time/UUID fields. No arbitrary properties bag or names beginning '$'.

| Event | Required event-specific fields | Forbidden combinations |
|---|---|---|
| evaluation_started | workflow recipe/raw_url4 | outcome, duration_bucket, report_ok absent |
| evaluation_finished | workflow recipe/raw_url4; outcome returned/failed/cancelled; duration_bucket | report_ok boolean required only when returned |
| submission_started | workflow submission | outcome, duration_bucket, report_ok absent |
| submission_finished | workflow submission; outcome returned/failed/cancelled; duration_bucket | report_ok always absent |

Duration buckets: under_1s, 1_10s, 10_60s, 1_10m, 10_60m, over_60m. No numeric cost, score or run duration. Other public operations remain inventoried in the broader SDK draft; discovery/review events require an additive contract review before a producer emits them. Initial funnel is evaluation -> submission response. Returning a non-ok report is not silently labelled an error-free evaluation. Session/active qualification remains a reporting choice for the SDK review, not something the service infers.

Reject prompts, outputs, errors/stack traces, raw URLs/URL4, model/benchmark/provider names, cost/cache fields pending explicit review, run/trace/report/score IDs, authors, email, auth credentials, machine names and IP/location properties. Never forward request headers or enrich from request IP/User-Agent. Do not reuse report-intake payload models or storage.

### Synthetic request example

```json
{
  "schema_version": 1,
  "consent_version": "1",
  "consent_granted": true,
  "events": [{
    "event_id": "11111111-1111-4111-8111-111111111111",
    "operation_id": "22222222-2222-4222-8222-222222222222",
    "session_id": "33333333-3333-4333-8333-333333333333",
    "persistent_id": "44444444-4444-4444-8444-444444444444",
    "id_scope": "installation",
    "event": "evaluation_finished",
    "timestamp": "2026-09-09T10:00:00.000Z",
    "sdk_version": "0.1.0",
    "surface": "python_sdk",
    "interface": "sync",
    "origin": "local",
    "host_environment": "python",
    "execution_mode": "hosted",
    "workflow": "recipe",
    "outcome": "returned",
    "duration_bucket": "1_10m",
    "report_ok": true
  }]
}
```

Example timestamp uses an injected clock in tests; no production event is sent by docs or CI. Sync/async execution uses the same schema and the explicit interface enum.

## PostHog mapping and duplicates

Use PostHog's public capture/batch API through a small HTTP adapter so retry/deadline behavior is under service control. Pin/test request shape against official public API, not internal Django ingestion helpers. Server configuration supplies the project token and HTTPS host; clients cannot choose either. Map event_id to top-level uuid, event to event, timestamp verbatim to timestamp, and distinct_id to sf:<id_scope>:<persistent_id or session_id>. Include only validated common/event fields plus service-owned schema/consent version and $process_person_profile=false, $geoip_disable=true. No identify/alias, $set/$set_once, page URLs, IP forwarding, session replay or autocapture. Keep custom session_id separate from PostHog's automatic session machinery.

Within a batch, identical event IDs with identical canonical content collapse; conflicting content for the same event ID returns 422. Across requests/restarts, retries preserve uuid, event name, timestamp and distinct_id exactly. PostHog deduplication is eventual, not a transactional exactly-once guarantee; transient duplicates can appear and downstream actions can repeat. First service has no global dedup database and promises no immediate uniqueness. Dashboards/acceptance checks must deduplicate by the complete stable key or wait for merges. Do not mutate timestamp or add sent_at during retry. Events with the same UUID and changed content are client-contract violations; across independent requests this stateless service cannot prove immutability. Restrict these events to analytics, not side-effecting automations.

Source: [PostHog event deduplication documentation](https://github.com/PostHog/posthog.com/blob/master/contents/docs/data/events.mdx). [Public capture API](https://posthog.com/docs/api/capture) is the adapter contract to verify when implementing. [Anonymous capture configuration](https://github.com/PostHog/posthog.com/blob/master/contents/docs/libraries/node/index.mdx) documents personless and GeoIP controls. This section supersedes broader draft language implying immediate gateway deduplication.

## Configuration, limits and deployment

Proposed settings: ANALYTICS_ENABLED (off by default), ANALYTICS_POSTHOG_HOST, ANALYTICS_POSTHOG_PROJECT_TOKEN, ANALYTICS_ENV (test/production), ANALYTICS_MAX_INFLIGHT (default 16), ANALYTICS_REQUESTS_PER_MINUTE (default 120 per process, global rather than per-person), bind host/port and redacted log level. Configuration validation fails startup if forwarding is enabled without explicit destination/token. Host must be HTTPS and deployment-allowlisted; no client-selected destination. Test can inject loopback transport without relaxing production validation. Secret values supplied by deployment secret references, never source, charts defaults or logs.

Bound body bytes, event count, task concurrency, HTTP pool and total request time. Per-process limits scale with replicas and are not cluster-wide guarantees; ingress also needs deployment-owned global abuse protection before public launch. No embedded shared SDK secret, CAPTCHA or login is added to this anonymous endpoint. Do not infer consent from browser headers or CORS. Deny browser CORS by default in this server-client increment; future bridge support is a separate design. Trusted proxy configuration must be explicit if ingress limits use network addresses; those must not become analytics properties.

Operational metrics contain only bounded labels (status/event type/retry bucket), no identifiers or bodies. Access logs omit request body, cookies, Authorization, query strings and client IP where possible; deployment must verify actual ingress/CDN logs and retention before public use. Service stores no durable event payloads or backups; in-flight memory expires with the request. PostHog raw-event retention target is 84 days and must be enforceable for the selected project/plan before production. Opt-out prevents future sends in the later SDK; already accepted events require the separate historical-deletion procedure. This ingestion-only service cannot revoke previously issued Colab capabilities because it issues none.

Registration in implementation PR: app src/tests/pyproject/uv lock, Dockerfile, Helm/deployment route, CI lane and gate-card entry, release-please or explicitly chosen release lane, CODEOWNERS owner, dependabot and app guardrails. No runtime config registrations in the docs PR. Select deployment hostname/port/owner during review; do not invent a live endpoint. Use report-intake as structure reference, not as a source of unrelated auth, database or reporting features.

Owner prerequisite: create analytics under the existing app label group in Linear and register/apply it. Current repo/design-session label is intentionally temporary for this docs phase.

## Acceptance matrix

Synthetic tests: valid four event forms and all outcome variants; unknown/deep properties, consent false/missing, malformed versions/UUIDs/time, forbidden fields and invalid scope combinations; chunked oversized request; no upstream call on reject; duplicate/conflicting batch IDs; timeout/429/5xx/permanent rejection/ambiguous acceptance; fixed retry identity/timestamps; caller disconnect; health/drain/readiness; concurrency/rate caps; secrets and request content absent in captured logs.

A separately authorized test-project smoke check verifies exact PostHog payload, stable event identity, personless capture, no enrichment and eventual dedup. CI uses a mock upstream, never production credentials. No service acceptance claims SDK consent, cookie persistence or frontend behavior. Review and merge docs first, then implement in a separate PR against this issue; do not close the issue on docs merge.
