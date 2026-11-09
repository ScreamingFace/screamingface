# Analytics ingestion service

Receives opted-in SDK evaluation/submission events at `POST /v1/events` and forwards
validated events to PostHog. Implements the [OME-1152 contract](../../docs/spec/2026-09-09-OME-1152-analytics-service-spec.md).
No SDK instrumentation, prompts, identity linking or database is included.
An optional Colab bridge adds consent and identifier cookies as described below.

## Run and configure

From this directory: `uv sync --frozen` then `uv run sf-analytics`.
Default bind is loopback port 9110; the container binds 0.0.0.0:9110.
This port is an internal default, not a reserved public endpoint.

| Variable | Default / purpose |
|---|---|
| ANALYTICS_ENABLED | false; disabled ingestion returns 503; readiness also accounts for the optional bridge |
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
invalid destination. `/healthz` is process liveness; `/readyz` means ingestion or the
bridge is enabled, and the service is not draining. This keeps consent and opt-out
reachable through Kubernetes while event delivery is disabled. It does not indicate
current PostHog reachability. No access logs or browser CORS are enabled.

## Delivery and operations

202 means whole-batch upstream HTTP acceptance, not queryability or durable/exactly-once
storage. Permanent upstream rejection returns 502; transient/ambiguous delivery returns 503.
Clients retry only 429/503 with the original events. Never retry 4xx or 502. Request cap is
64 KiB (streamed), event cap 4 KiB (compact UTF-8 JSON), batch cap 20. Compressed bodies are
rejected. Schema/consent rejection is 422; malformed JSON 400; size 413; media type 415.

Body intake, validation and forwarding share one total 1.5-second request budget, with at
most two upstream attempts and jittered 100ms backoff. Retry-After is honored only within
the remaining request budget. Corrupt upstream encodings are retryable ambiguity. Deadline
expiry or disconnect cancels pending delivery. There is no durable spool. PostHog duplicates
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
eventual duplicates), accurate disclosure of PostHog-managed retention without a fixed deletion deadline,
operator ownership, ingress protections, and a historical-deletion procedure. This service
stores no event payloads/backups and cannot enforce PostHog's retention remotely. Longer-lived
aggregates must omit browser/installation/session IDs. SDK opt-out arrives in its later slice.

## Verification

`uv run .claude/scripts/run_gates.py analytics` from repository root runs lock, lint,
format, types, tests with 95% branch coverage, and distribution build. CI also builds and
starts the container and renders both disabled/enabled Helm configurations. Tests never send
live events. Code ownership follows the repository's shared service maintainers pending a
specific deployment owner.


## Optional Colab bridge

The service-side bridge is implemented here; the Colab SDK adapter is a separate
change. It is disabled by default. Node 24 is required to run the iframe protocol
tests included in the Python test suite; CI installs it explicitly.

| Variable | Purpose |
|---|---|
| `ANALYTICS_BRIDGE_ENABLED` | `false`; register bridge routes only when enabled |
| `ANALYTICS_BRIDGE_COLAB_ENABLED` | `false`; opt into the verified Colab output-host profile |
| `ANALYTICS_BRIDGE_ORIGIN` | Exact public HTTPS analytics origin |
| `ANALYTICS_BRIDGE_PARENT_ORIGINS` | Comma-separated exact permitted Colab output origins |
| `ANALYTICS_BRIDGE_ANCESTOR_ORIGINS` | Comma-separated exact additional ancestors for CSP |
| `ANALYTICS_BRIDGE_COOKIE_MAX_AGE` | 15552000 seconds (180 days), configurable from 1 to 365 days |

Custom origins contain no path, wildcard, credentials, query or fragment. For
Colab, enable the optional profile instead of manually registering each output
host. Its observed grammar is bounded to one DNS label of the form
`<alphanumeric>-<16 lowercase hex digits>-<numeric index>-colab.googleusercontent.com`
over canonical HTTPS without explicit ports. It is a tested integration rule,
not a Google guarantee; future host changes fail closed until reviewed.

Helm exposes these under `analytics.bridge.{enabled,colabEnabled,origin,parentOrigins,
ancestorOrigins,cookieMaxAge}`. Enabling the bridge adds `/bridge` Prefix ingress
beside `/v1/events` Exact; health routes remain internal. Allow unauthenticated access
to bridge routes, strip no Set-Cookie/CSP headers, disable caching and raw request
logging, and apply edge rate/body limits. No new PostHog key or database is required.

### HTTP and iframe protocol

- `GET /bridge/consent`: minimal iframe page; no cookies minted or events sent.
- `GET /bridge/consent/state`: choice/version only; no identifier creation.
- `POST /bridge/consent`: exact JSON `{"choice":"accepted","consent_version":"1"}`
  or `declined`. Choice has no unique value. Decline expires ID in the same response;
  fresh consent also expires any orphan/stale ID. Repeated acceptance preserves ID.
- `POST /bridge/id`: empty JSON object; accepted cookie required. Returns
  `choice`, `consent_version`, `id_scope:browser`, `persistent_id`. Renews consent.
  Returns a valid existing ID without rewriting its cookie; creates an ID only
  if missing or invalid. ID lifetime runs from creation, not the latest read.
- `POST /bridge/id/revoke`: empty JSON object; declined cookie required; idempotent
  ID expiry. Normal decline already expires ID, so no second request is necessary.
- `POST /bridge/id/events`: the existing four-event envelope. Requires accepted
  consent and ID cookies; each event must be `origin:colab`, `surface:python_sdk`,
  `id_scope:browser` with the matching `persistent_id`. Uses the same strict event
  schema, dedup keys, admission and upstream acknowledgement as `/v1/events`.

Mutations require the configured same-origin Origin header and, when present,
`Sec-Fetch-Site: same-origin`. No CORS is enabled. Consent-control bodies are capped
at 1 KiB with a 1.5-second deadline. They have a separate admission budget using the
same configured limits so event delivery being disabled does not prevent opt-out.
All successful/handled-error bridge responses have no-store/no-referrer/nosniff.
The consent and opt-out cookies are scoped to `/bridge`; the ID to `/bridge/id`. All are Secure,
HttpOnly, SameSite=None, Partitioned and host-only. Cookie retention is independent
of PostHog-managed event retention; browser eviction may end continuity earlier.
The non-identifying `__Secure-sf_bridge_optout=1` flag takes precedence over the
legacy consent cookie. Explicit decline sets it with the same configured lifetime;
only explicit accept clears it. Enrollment and identity refresh never write it.
Enrollment never writes or deletes the ID cookie. A delayed enrollment or an
existing-ID read cannot delete or restore an ID after explicit reaccept.

The parent waits for iframe load and sends `postMessage` to the exact service origin:
`{version:1,nonce:<16–128 ASCII letters/digits/_/->,command:<command>}`. Commands are
`state`, `accept`, `decline`, `id`, `events`; only `events` adds a `batch` field.
The iframe checks exact allowed parent origin and source, rejects unknown fields,
and responds to that origin with version/nonce/command plus `result` or a sanitized
`error`. The parent must independently check source/origin/schema/nonce and discard
late generations. There is no unsolicited ready message or wildcard target.

Only one request is active per iframe. Additional calls return `busy`; decline
aborts that frame's active request and suppresses late results. Requests time out
after two seconds; no durable queue or automatic browser retry. The future SDK
adapter must serialize/batch sends, preserve event IDs on bounded retry, recheck
state on failure, and never block evaluation on iframe or kernel initialization.

### Revocation and validation limits

Other active notebooks send the browser's current shared partition cookies on each
batch. After a decline response updates the cookie jar, subsequent requests are
rejected by any upgraded replica, even if an older enrollment or identity-refresh
response arrives afterward. The separate opt-out flag prevents those responses
from restoring permission. Requests already sent may complete; concurrent explicit
accept/decline responses are applied in browser order. This is not globally instantaneous
revocation. No capability or product credential is copied into a Python runtime.
The anonymous `/v1/events` endpoint still trusts explicit client consent affirmation;
this system cannot prove human consent from a modified client.
Concurrent first-time ID requests can still mint different fresh IDs whose
cookies apply in response order, including across reaccept. This can invalidate
another frame's cached ID; it is not the old-ID restoration fixed by making
existing-ID reads leave the ID cookie untouched. Explicit-action races also
retain browser response ordering.

Automated tests cover synthetic cookie jars, two independent replicas, stale-ID
rejection, request validation and the actual shipped script's message boundary.
They do not emulate browser partitioning. Before public activation, verify the
real Colab ancestor chain, nonblocking SDK integration, blocked cookies, Chrome and
Safari notebook/runtime/browser restarts, and two-notebook opt-out against dev
PostHog. This implementation has not yet been deployed or passed that browser run.


### Dev Colab profile (deployment owner applies)

```yaml
analytics:
  bridge:
    enabled: true
    colabEnabled: true
    origin: https://analytics.dev.screamingface.ai
    parentOrigins: ""
    ancestorOrigins: ""
```

Retain existing PostHog configuration. These are deployment values, not a change to
the general disabled defaults. Ensure the updated chart or private ingress exposes
`/bridge`; changing only the image is insufficient.

The Colab adapter must construct the iframe URL in the notebook output frame:

```javascript
const bridge = new URL('/bridge/consent', 'https://analytics.dev.screamingface.ai');
bridge.searchParams.set('parent_origin', location.origin);
iframe.src = bridge.href;
```

The page endpoint validates that origin against the profile and generates an exact
`frame-ancestors https://colab.research.google.com <validated-output-origin>` policy.
It does not use `*.googleusercontent.com`. Duplicate/extra query parameters or
invalid parents return 400. With no parent query and no custom origins, the page
has `frame-ancestors 'none'`. The script independently enforces the bounded Colab
origin grammar and parent-window source, and always replies to the exact origin.
The query contains an output-frame origin, never an analytics ID; keep query logging
redacted. The actual SDK integration and deployed browser tests remain separate.

Live origin probe on 25 September verified a changing output host across a page
reload and the Colab top-level ancestor. See the origin-policy spec/work ledger
for evidence and remaining Chrome/Safari end-to-end acceptance.

## Default-on SDK enrollment (OME-1768)

The SDK enables analytics by default while making a best-effort disclosure attempt,
including in headless environments. Every explicit opt-out is preserved. The additive
`enroll` browser command posts `{"consent_version":"1"}` to
`/bridge/consent/enroll`. It accepts only when both consent and opt-out cookies are absent.
Existing accepted/declined or unrecognized cookies are preserved; no identity
is minted by enrollment. The SDK requests an ID separately after confirmed acceptance.
Explicit `accept` remains the only command that can reverse a stored decline.

Upgrade every service replica before the new SDK. Old replicas do not enforce the
opt-out flag, so mixed deployments cannot guarantee the response-order protection.
Older SDKs retain their explicit opt-in flow;
new SDKs against older services stay off if enrollment is unavailable. The version-1
wire shape is unchanged: accepted/consent_granted now permits explicit enable or a
default-on policy. Existing opt-outs are not migrated to acceptance.
This amends the opt-in-only policy described in the original implementation notes.
The existing limitation for browser requests already in flight still applies.
Source changes are not rollout approval; see
`docs/spec/2026-10-30-analytics-default.md`.
