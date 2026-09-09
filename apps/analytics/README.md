# Analytics ingestion service

Receives opted-in SDK evaluation/submission events at `POST /v1/events` and forwards
validated events to PostHog. Implements the [OME-1152 contract](../../docs/spec/2026-09-09-OME-1152-analytics-service-spec.md).
No SDK instrumentation, prompts, cookies, identity linking or database is included.

## Run and configure

From this directory: `uv sync --frozen` then `uv run sf-analytics`.
Default bind is loopback port 9110; the container binds 0.0.0.0:9110.
This port is an internal default, not a reserved public endpoint.

| Variable | Default / purpose |
|---|---|
| ANALYTICS_ENABLED | false; disabled ingestion and readiness return 503 |
| ANALYTICS_ENV | test; deployment classification, test/production |
| ANALYTICS_POSTHOG_HOST | Explicit HTTPS capture origin, no path/query/userinfo |
| ANALYTICS_POSTHOG_ALLOWED_HOSTS | Comma-separated deployment allowlist of destination hostnames |
| ANALYTICS_POSTHOG_PROJECT_TOKEN | Secret; required when enabled |
| ANALYTICS_MAX_INFLIGHT | 16 per process, including bounded body reads |
| ANALYTICS_REQUESTS_PER_MINUTE | 120 per process; fixed 60-second window |
| ANALYTICS_HOST / ANALYTICS_PORT | 127.0.0.1 / 9110 |

Choose a separate test project's host/token for development and smoke tests. The environment
label does not prove which project a token belongs to; deployment must verify that mapping.
No real destination or credentials are shipped. Startup rejects enabled forwarding with an
invalid destination. `/healthz` is process liveness; `/readyz` means enabled and not draining,
not current PostHog reachability. No access logs or browser CORS are enabled.

## Delivery and operations

202 means whole-batch upstream HTTP acceptance, not queryability or durable/exactly-once
storage. Permanent upstream rejection returns 502; transient/ambiguous delivery returns 503.
Clients retry only 429/503 with the original events. Never retry 4xx or 502. Request cap is
64 KiB (streamed), event cap 4 KiB (compact UTF-8 JSON), batch cap 20. Compressed bodies are
rejected. Schema/consent rejection is 422; malformed JSON 400; size 413; media type 415.

Forwarding has a total 1.5-second budget, at most two upstream attempts and jittered 100ms
backoff. Retry-After is honored only within the budget. Body reads have a separate 2-second
limit. Disconnect cancels pending delivery. There is no durable spool. PostHog duplicates
are eventual: stable uuid/event/timestamp/distinct_id keys are preserved. Never use these
events to trigger side-effecting automations. Anonymous capture disables person profiles and
GeoIP. The adapter accepts exactly the public batch acknowledgement `{"status":1}`; malformed,
extra/partial response shapes fail closed until verified against the chosen deployment.
Source: [PostHog public capture API](https://posthog.com/docs/api/capture).

In-process `app.state.ingestion.counters` contains only bounded HTTP status counts; no event
bodies or identifiers. They reset on restart. Deploy behind external aggregate status/latency
monitoring. Limits scale with replicas and can burst across a fixed-window boundary; cluster
abuse protection belongs at ingress. Request bodies, cookies, credentials, query strings and
client IPs must be excluded from proxy/CDN logs. Review actual logging before public rollout.

## Deployment and release status

**Not released yet.** This first implementation registers the app and a build/start CI lane;
image publishing and production rollout require a reviewed release lane and destination.
Build a review image from repository root:
`docker build -f apps/analytics/Dockerfile -t analytics:review .`.
The chart requires an explicit tested image tag; ingestion and public ingress default off.
Tokens come only from an existing Kubernetes Secret. Public ingress exposes only `/v1/events`
and requires explicit hostname/controller/TLS. Configure controller-specific abuse protection
and log redaction before enabling it. No live hostname or cloud infrastructure is created.

Production gates remaining: dedicated test-project smoke (payload/personless/no enrichment and
eventual duplicates), verified **90-day raw-event retention** in the selected PostHog project,
operator ownership, ingress protections, and a historical-deletion procedure. This service
stores no event payloads/backups and cannot enforce PostHog's retention remotely. Longer-lived
aggregates must omit browser/installation/session IDs. SDK opt-out arrives in its later slice.

## Verification

`uv run .claude/scripts/run_gates.py analytics` from repository root runs lock, lint,
format, types, tests with 95% branch coverage, and distribution build. CI also builds and
starts the container and renders both disabled/enabled Helm configurations. Tests never send
live events. Code ownership follows the repository's shared service maintainers pending a
specific deployment owner.
