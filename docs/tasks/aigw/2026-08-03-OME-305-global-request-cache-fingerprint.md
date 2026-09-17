---
id: OME-305
linear_url: https://linear.app/openmined/issue/OME-305/implement-caching-model-and-decide-on-fingerprinting
status: in_progress
type: Feature
priority: High
labels: [aigateway, agentic, autonomous]
created: 2026-08-03
closed:
---

# OME-305 — Global caching model and full-call fingerprinting

Absorbs OME-702 (Canceled — fingerprint scope moved here). Blocks OME-303 (per-call usage/cost
accounting), OME-304, OME-311, OME-692. Related: OME-617, OME-344, OME-704 (the five OpenRouter
routing/privacy controls this task promotes from `cache_behavior="bypass"` to `keyed`).

Plan of record: `.agent-team-AIGW/caching-model-and-fingerprinting/implementation_plan.md`
Work ledger: `docs/work/aigw/2026-08-03-OME-305-global-request-cache-fingerprint.md`

## Scope

One global exact-request response cache for eligible non-streaming `/v1/chat/completions` calls in
`apps/aigateway`, keyed on the complete effective output-affecting model call plus a pure
provider-owned projection.

```text
same effective output-affecting call -> same key across all users
different keyed input               -> miss
unknown or unsafe input            -> bypass
```

- Account, profile, user, auth mode, credential and BYOK identity do not partition the key.
  Hosted identity headers (`X-User-Email`, `X-User-Id`, `X-Service-Id`, `X-Tenant`) are excluded.
- `CurrentAccount` still authenticates every caller before route logic; a global cache does not
  make the endpoint anonymous.
- Before lookup, the route reads only profile defaults and merges them body-wins so the key describes
  the effective request. Profile/account identity, auth mode and provider credentials remain absent
  from the key. A hit performs no provider dispatch and resolves no provider credential.
- Per-call default-on: absent `cache` control means global read+write; `use-cache=false` is a full
  bypass; `ttl`/`s-maxage`/`no-cache`/`no-store`/unknown/malformed controls bypass as unsupported.
- Value is the complete provider response dict stored as plaintext compact JSON in the existing
  `RequestCacheEntry.response_ciphertext` column and returned unchanged on a hit including `usage`.
- Persistence reuses `RequestCacheEntry` with `key_version="aigw-global-chat-cache-v2"`,
  `account_id`/`profile_name` fixed to `"global"`, and `expires_at` nullable and always NULL for
  v2. Migration `0009_global_request_cache.py`. V1 rows stay unchanged and unreachable by v2.
- Writes are create-only: first successful insert wins (`stored` | `race_lost`); no single-flight.
- The cache is never an availability dependency: database/configuration/read/write failures bypass
  to the normal provider path and do not fail startup, readiness or liveness.
- Provenance headers: `X-AIGW-Cache: hit|miss|bypass`, `X-AIGW-Cache-Reason`, and
  `X-AIGW-Cache-Write: stored|race_lost|not_stored` on miss paths.

## Out of scope

OME-303 usage/latency/cost/currency accounting and any monetary field in the cache value; Engine
run rollups (OME-304, OME-306); hosted-to-local transfer (OME-311); Evaluation-scoped shared-work
scheduling (OME-617); Client cache inspection (OME-692); URL4 propagation of the cache control
(URL4 is outside OME-305 implementation scope as of 2026-08-03); sample `variant` lanes;
configurable v2 TTL, capacity limits, eviction, expired-row refill; response encryption, key
management, rotation and plaintext-row migration.

## Accepted trade-offs

Exact-response reuse is intentionally global across hosted users, and the first caller's provider
execution determines the globally replayed response. Hidden provider-account defaults are not key
dimensions. Rows live indefinitely with unbounded storage growth (monitored, not capped).
Concurrent cold misses may duplicate provider spend. A hit skips the auth-specific parameter
validation a miss would run. Response JSON is plaintext in the MVP database; encryption is deferred
until the feature proves useful.

## Done when

Plan §8 acceptance tests 1–19 pass, no plan §10 stop condition is triggered, and gates are green
including the PostgreSQL-marked subset for create-only conflicts, the nullable-expiry migration and
atomic hit increments.
