# AI Gateway Deployment

This runbook deploys `apps/aigateway` as a containerized FastAPI service on Kubernetes. The app chart is database-agnostic: it reads `AIGATEWAY_DATABASE_URL` from a Secret and runs Tortoise migrations as a Helm pre-install/pre-upgrade Job.

## Artifacts

- Container image: `ghcr.io/screamingface/screamingface-aigateway:<version>`.
- App chart: `oci://ghcr.io/screamingface/screamingface/charts/aigateway`.
- Demo database chart in this repo: `apps/aigateway/charts/db`.

The demo database chart is a single `postgres:16-alpine` Deployment with a PVC. It is useful for k3s smoke tests and demos, but it has no HA, backups, PITR, or managed upgrade policy.

## Local k3s Smoke Image

Build an amd64 image for a single-node Linux k3s server:

```bash
docker buildx build \
  --platform linux/amd64 \
  -f apps/aigateway/Dockerfile \
  -t ghcr.io/screamingface/screamingface-aigateway:sf186-local \
  --load \
  .
```

Import the local image into k3s containerd when you do not want to push a temporary tag:

```bash
export K3S_SSH_TARGET='adminuser@k3s-host.example.com'

docker save ghcr.io/screamingface/screamingface-aigateway:sf186-local \
  | ssh "$K3S_SSH_TARGET" \
      "sudo k3s ctr -n k8s.io images import --platform linux/amd64 -"
```

Verify it is available to pods:

```bash
ssh "$K3S_SSH_TARGET" \
  "sudo k3s ctr -n k8s.io images ls | grep screamingface-aigateway"
```

## Demo Database

Install the generic Postgres chart with the AI Gateway values overlay:

```bash
helm upgrade --install aigw-db apps/aigateway/charts/db \
  --namespace aigw \
  --create-namespace \
  --values apps/aigateway/charts/db-aigateway.values.yaml \
  --wait
```

The chart creates `Secret/aigw-db` with `username`, `password`, `database`, and `database-url`. The app chart consumes only the `database-url` key.

For production, replace this chart with managed Postgres or a Postgres operator. Create a Secret with a `database-url` key and point `database.existingSecret` at it.

## App Install

Use a real HTTPS hostname in production. For a temporary k3s smoke test, set
`AIGW_SMOKE_HOST` locally to a disposable DNS name that resolves to the server. A service such as
`nip.io` can provide that mapping without committing a machine address to this runbook.

```bash
export AIGW_SMOKE_HOST='aigateway.example.com'

helm upgrade --install aigw apps/aigateway/charts/aigateway \
  --namespace aigw \
  --set image.tag=sf186-local \
  --set ingress.className=traefik \
  --set "ingress.hosts[0].host=${AIGW_SMOKE_HOST}" \
  --set "ingress.hosts[0].paths[0].path=/" \
  --set "ingress.hosts[0].paths[0].pathType=Prefix" \
  --set "publicUrl=http://${AIGW_SMOKE_HOST}" \
  --wait
```

Quote indexed `--set` keys in shells such as zsh. If you override a list item, set the full `host` and `paths` structure.

## Production Secrets

By default the app chart creates `Secret/aigw-auth` and preserves generated values across Helm upgrades when it can read the existing Secret. For production, prefer creating the auth Secret yourself and installing with `auth.createSecret=false`.

```bash
kubectl -n aigw create secret generic aigw-auth \
  --from-literal=jwt-secret="$(openssl rand -base64 48)" \
  --from-literal=admin-password="$(openssl rand -base64 24)"

helm upgrade --install aigw oci://ghcr.io/screamingface/screamingface/charts/aigateway \
  --version 0.2.0 \
  --namespace aigw \
  --set auth.createSecret=false \
  --set auth.existingSecret=aigw-auth \
  --set database.existingSecret=aigw-db \
  --set database.existingSecretKey=database-url \
  --set publicUrl=https://aigateway.example.com
```

## Smoke Checks

Run the Helm test and check public health:

```bash
export AIGW_SMOKE_HOST='aigateway.example.com'

helm test aigw --namespace aigw --timeout 3m
curl -fsS "http://${AIGW_SMOKE_HOST}/healthz"
```

Check gateway login without printing the token:

```bash
ADMIN_PASSWORD=$(kubectl -n aigw get secret aigw-auth \
  -o jsonpath='{.data.admin-password}' | base64 --decode)

STATUS=$(curl -fsS -o /tmp/aigw-login.json -w '%{http_code}' \
  -H 'content-type: application/json' \
  --data "{\"username\":\"admin\",\"password\":\"$ADMIN_PASSWORD\"}" \
  "http://${AIGW_SMOKE_HOST}/v1/auth/login")

python3 -c 'import json; print(bool(json.load(open("/tmp/aigw-login.json")).get("token")))'
```

## SF External Mode

Point SF at the deployed gateway instead of the local managed runner:

```bash
SF_AIGW_BASE__MODE=external \
SF_AIGW_BASE__GATEWAY_URL=https://aigateway.example.com \
uv run sf run --no-ssl
```

External HTTP URLs are blocked by default unless they are loopback. For a temporary HTTP-only k3s smoke test, set `SF_AIGW_ALLOW_INSECURE_EXTERNAL=1` only for that process.

The SF status endpoint should move from `login_gateway` to `healthy` after logging into the gateway through `/aigateway/session/login`.

## Migrations

The app chart runs:

```bash
python -m tortoise -c aigateway.db.TORTOISE_CONFIG migrate
```

This runs in a Helm hook Job before app Deployment rollout. Do not run `Tortoise.generate_schemas()` in production and do not run migrations in app startup.

### Rolling back the request-cache schema resets the cache

`0010_simplify_request_cache` removes the unused account/profile-scoped preflight schema. Its upgrade
clears the cache before dropping those columns and renaming the plaintext response field to
`response_json`. Cache rows are disposable, so no mixed encrypted/preflight payload is retained.

Before rolling back past `0010`, disable the cache and quiesce every app replica so no writer can
refill the table during the downgrade. Clear the cache, then downgrade. Migration `0010` also clears
rows automatically at the beginning of its reverse path as a final safety net. The empty table can
then regain the removed non-null columns, and the following `0009` downgrade can restore
`expires_at NOT NULL`:

```sql
DELETE FROM request_cache_entries;
```

That is a deliberate cache reset, not application-data loss. The table contains only the global
request cache; it stores no account/profile identity.

## The Global Response Cache

`config.requestCache.enabled` (env `AIGW_REQUEST_CACHE_ENABLED`) turns on **one global cache shared
by every caller of the gateway**. The Helm chart enables it by default; set the value to `false` to
opt out. The standalone app default remains off. Enabling it is a decision about data sharing, not
a performance setting.

**It is not gateway-wide.** Of the eight registered providers, **anthropic**, **openai**,
**openrouter** and eligible **huggingface** requests can be served from cache in this release —
huggingface only *partly* (see below). Requests to **antigravity**, **codex**, **gemini-cli** and
**ollama** bypass it entirely and always dispatch. Caching a provider requires that provider to
declare what *it* contributes to the upstream call (`global_cache_projection`), and those four
inherit the bypassing default, so there is nothing safe to key on. Expect a 100% miss rate on
those four and do not read it as a fault.

**The four cacheable providers are not gated the same way, and the difference matters because this
table describes the pre-credential cache stage itself — not checks that run only after a miss:**

| Provider | Provider switch checked before cache | Additional cache-participation gate |
| --- | --- | --- |
| `anthropic` | none | none beyond projection and shared request eligibility |
| `openai` | none | requested-model and ambient-state runtime certification |
| `openrouter` | its own enabled flag | none beyond projection and shared request eligibility |
| `huggingface` | none | pinned-backend rule below, router-base certification and ambient-state runtime certification |

OpenRouter does have additional dispatch-time protection against unsafe ambient LiteLLM state, but
that runs only on a miss. A cache hit returns before dispatch, so it is not a cache-participation
gate and is deliberately not represented as one here. Anthropic likewise has no separate
participation override; it inherits the default after its projection accepts the request.

Direct **openai** is the one to read twice: it has **no OpenRouter-style operator switch**, so
`requestCache.enabled` is the only lever that turns its caching off. That is not the same as
caching unconditionally — its runtime guard still declines per request when the model is
ambiently aliased or the process carries LiteLLM state that would reroute the call. Plan for
OpenAI responses to be cached and cross-account replayable whenever the cache is on.

#### Hugging Face: only a pinned provider participates

A Hugging Face model id may end in `:<suffix>`, and the suffix means one of two different things.
Only the first is cacheable:

| Request | Cached? | Why |
| --- | --- | --- |
| `huggingface/<org>/<model>:<provider>` — a **known partner slug** (`:novita`, `:groq`, …) | **yes** | one fixed backend answers, so the stored row describes the next identical call |
| `huggingface/<org>/<model>` — no suffix | no | the router picks a backend **per request** (equivalent to `:fastest`) |
| `:fastest`, `:cheapest`, `:preferred` — routing **policies** | no | a selection rule, not a backend. `:preferred` follows the **requesting account's** preference order, so it is identity-dependent and the global key is identity-free |
| an unrecognised suffix | no | fail closed — unknown means unproven |
| any request from a process with unsafe ambient LiteLLM state, or with `router_api_base` overridden away from the official router | no | the projection would describe a call this process is not making |

Bypassing requests **still dispatch normally** — this narrows caching, never validity. The
allowlist is a reviewed transcription of the Hugging Face partner table, so a newly launched
partner is simply uncached until it is added.

**Operator consequence — cross-account replay of gated repositories.** A cacheable Hugging Face
response is stored globally and replayed to any caller whose request keys identically, **before
any credential is resolved**. Many Hugging Face repositories are *gated*: access requires
per-account licence acceptance. A row filled by an account that accepted the licence can therefore
be served to an account that never did. The cache changes **who may read a stored answer**, never
what goes on the wire — but if your deployment serves multiple tenants and relies on Hugging Face
gating for licence compliance, that is a decision to take deliberately, not a side effect to
discover. Set `config.requestCache.enabled=false` to opt out.

### What it does

- **Cross-user replay of the *effective* request.** The key is built from the call as the gateway
  will actually send it — **after** the caller's own profile defaults have been resolved and merged,
  with explicit body values winning. Two callers share a stored response when their requests are
  identical *once each has had their own defaults applied*. So two callers whose profiles carry
  different system prompts or sampling parameters correctly do **not** share one, and a caller whose
  profile default happens to equal another caller's explicit parameter correctly **does**. Profile
  name and account identity never enter the key, and neither do auth mode, provider credentials, API
  keys or OAuth tokens. On a hit no provider request is made and no provider credential is read.
  There is no per-user or per-account partition; that is the feature, not a leak.
- **Default-on per request, opt-out per request.** With the operator flag on, an eligible request
  participates in the cache by default. A caller who must not be served a stored answer sends
  `{"cache": {"use-cache": false}}` in the request body and gets a normal dispatch.
- **First successful fill wins, permanently.** Rows are created, never overwritten. Whatever the
  first caller's request produced is what everyone receives from then on. A concurrent second fill
  is discarded, not merged.
- **No expiry.** Global rows are written with `expires_at = NULL` and are never collected by the
  TTL purge. "Indefinite" is literal.

### Who can *ask* is a wider set than who can read

The access-control question the cross-user replay raises is not "who may read
`request_cache_entries`" — it is **who may send a request that is answered from it**. Those are
different sets and the second is larger, because reproducing a cached request needs only the request
and the asker's own profile defaults, which may legitimately be empty — never a provider credential.

**The boundary is the edge, not the gateway.** In `cloudflare_headers` mode the gateway *trusts*
`X-User-Email` as already-verified identity; it does not authenticate the caller itself. Cloudflare
Access, plus `allowedNetworks` and the NetworkPolicy that keep the gateway internal-only, are what
decide who may ask. Review those before enabling the cache — there is no gateway-side setting that
narrows who a hit may be served to.

**A caller needs no provider credential — but the profile index must be readable.** A hit reads
no provider API key and no OAuth token, and makes no provider request. It does resolve the
caller's own profile defaults, because the key is built from the effective request, and that
means a hit reads this account's profile index.

Read that precisely: it is the index *read* that has to succeed, not the profile that has to
exist. A caller with no profile configured for this provider has empty defaults and is served
from cache normally — and so is a caller whose profile is still pending authorization or already
errored, because the pre-cache read never inspects profile state
(`routes/chat_profile_defaults.py`). What stands the cache down is a failed read: if the index
cannot be fetched or decrypted, the request bypasses the cache and is dispatched with the
defaults resolved further down, rather than keyed without them.

What survives is the part that matters for access control: **a principal who has never configured a
usable provider credential is still served responses another account paid for.** Treat this as a
**new capability** rather than a widened one — before the global cache such a caller could obtain
nothing at all. It matters most in `cloudflare_headers` mode, where an unrecognised email
**auto-provisions** an account instead of being rejected.

### Response-cache reads do not use the master key

The cached response is plaintext compact JSON in `response_json`. Reading it does not resolve a
secret provider, validate an encryption canary or decrypt the response body.

The caller's profile index is still a credential blob (`aigateway:index`) and remains encrypted under
the credential master key. A hit reads that index to merge profile defaults before key construction,
but it never reads the selected provider API key or OAuth token and never dispatches to the provider.

### A hit replays the first caller's credential *type*, not only their answer

The cache key is the effective output-affecting model call and deliberately carries **no credential
and no auth-mode term** (`core/request_cache/global_keys.py`); `api_key` sits in
`EXCLUDED_TRANSPORT_FIELDS`. But the upstream call is not the same across credential types: an
Anthropic **OAuth** subscription credential gets the Claude-Code attribution system block added and
the caller's system messages hoisted (`plugins/anthropic_provider/chat_handler.py`), while a raw
`sk-ant-` API key deliberately must not carry that block.

Both produce the same cache key, so **whichever credential type filled a row first fixes the shape of
the upstream call for everyone**. An API-key caller can be served text that its own credential type
would not have produced, and vice versa. The block's *content* is folded into the provider's
`provider_adapter_revision`, so changing it abandons rows filled under the old block — but *whether*
it applied is not in the key. A deployment that mixes OAuth and API-key credentials for one provider
and needs that distinction preserved must opt those requests out with `use-cache=false`.

### `enabled: true` is the complete response-cache switch

`AIGW_REQUEST_CACHE_ENABLED=true` makes the response cache available. There is no response-cache
master-key precondition or acknowledgement flag. `AIGATEWAY_SECRET_KEY` and `auth.secretKeyKey` still
control encryption of provider credentials, OAuth tokens and other credential blobs.

**`AIGW_AUTH_MODE=disabled` is not a refusal, and is worth understanding separately:** with auth off,
every peer who can reach the port is the same anonymous principal, so the cached corpus is common to
everyone with network access rather than shared between identified users.

### Growth is unbounded — monitor it

There is no TTL and no eviction policy for global rows. Size grows with the number of distinct
requests the gateway has ever answered, and each row holds a full plaintext provider response.

```sql
SELECT count(*) AS rows,
       pg_size_pretty(pg_total_relation_size('request_cache_entries')) AS size
FROM request_cache_entries;
```

Watch this table's size like any other unbounded table and prune deliberately (for example by
`created_at`, or by `hit_count = 0` for rows nothing has ever reused). Pruning is safe at any time:
a deleted row is a cache miss, and the next caller re-fills it.

**Rows carry the provider that filled them, so a reset does not have to be all-or-nothing.** To
drop only Hugging Face rows — after a partner-allowlist correction, say, or to retire replayable
gated-repository answers — without discarding every other provider's cache:

```sql
DELETE FROM request_cache_entries WHERE provider = 'huggingface';
```

That removes Hugging Face cache rows and nothing else; substitute any other provider name to
narrow the same way. It is a targeted version of the full reset, not a different mechanism, and
carries the same guarantee: the next caller re-fills what was removed. There is no runtime
endpoint for this — it is a deliberate database operation, on purpose.

### Plaintext storage boundary

Global response rows are readable to anyone with database, replica, snapshot or backup access. If a
class of response must not be stored or replayed across users, send `use-cache=false`.

### Accounting boundary

Usage and cost accounting for cache hits is **out of scope here** and tracked separately as OME-303.
This feature writes no accounting or attribution fields, and a hit performs no provider dispatch —
so a hit currently produces no provider-side usage record of its own. Do not read cache-hit volume
out of provider billing.

## Live OpenRouter Model Discovery (OME-972)

`GET /v1/models` lists the models OpenRouter actually serves now, refreshed from its public
catalog (`https://openrouter.ai/api/v1/models`, no credential attached) through a cached
catalog snapshot, held per process (see the replica note below). Default **on**.

- `AIGW_OPENROUTER_LIVE_MODELS=false` restores the static compiled-seed listing with **zero**
  catalog egress. `AIGW_DISCOVERY_ENABLED=false` (the discovery kill switch) silences the
  catalog together with all other discovery traffic.
- **Snapshot-or-fallback:** with a healthy snapshot the listing is the discovered plain
  `vendor/model` ids plus anything explicitly configured in `AIGW_OPENROUTER_DEFAULT_MODELS`
  plus admitted models — compiled defaults absent from the snapshot are not listed, so retired
  models disappear within one TTL. When the catalog is cold or degraded, the listing falls back
  to the compiled/operator seeds, identical to today's static behavior.
- **Degrade ladder:** fresh snapshot (≤5 min) → served from cache; refresh failure → last good
  snapshot serves for up to 1 h (stale window); beyond that → seed fallback. Failed refreshes
  are damped to at most one upstream attempt per 30 s. A failure never evicts the last good
  snapshot, and a partial/malformed/oversized/off-policy catalog read is never cached.
- **Explicit config vs. fallback:** setting `AIGW_OPENROUTER_DEFAULT_MODELS` makes those models
  operator intent — they are listed first and survive every healthy snapshot. Leaving it unset
  means the compiled seeds are only the fallback.
- **Variants are never discovered automatically.** Colon variants (`:free`, `:batch`) and tilde
  aliases (`~`) are excluded from auto-publication; a variant reaches the listing only by
  being configured in `AIGW_OPENROUTER_DEFAULT_MODELS` or by sitting in the compiled seed
  list that the fallback serves (some seeds are `:batch` slugs) — never from the catalog and
  **not** through `POST /v1/models/admit`, which refuses the same shapes. Variants stay
  dispatchable directly whether or not they are listed.
- **`:online` is refused at startup.** Chat dispatch rejects the `:online` suffix
  (`unsupported_model_variant`) because web search is a provider-neutral Gateway parameter, so
  configuring one would publish a model whose every request fails. The settings validator now
  rejects it outright — use the Gateway's own web-search parameter instead.
  **Breaking on upgrade:** a deployment that currently lists a `:online` slug in
  `AIGW_OPENROUTER_DEFAULT_MODELS` fails to start after this change. Scrub the variant from
  the env var before rolling out.
- **Fail-closed catalog parsing.** A catalog page must carry `data`, `links.next` (string or
  null) and a non-negative integer `total_count`, and every row must carry a string `id`; the
  per-page `total_count` must agree across pages and with the number of rows collected. Any
  deviation — one malformed row included — fails the **whole** refresh. Nothing partial or
  salvaged is ever cached as fresh, so an upstream schema drift degrades to the last good
  snapshot (then to seeds) instead of silently publishing a shrunken listing.
- **Refresh latency is paid inline** by whichever request finds the snapshot cold or expired:
  one fetch per catalog page (two pages at the current ~420-model catalog size), hard-bounded
  by a 10 s aggregate deadline across the whole pagination chain. Concurrent callers share that one refresh (single-flight) and all
  receive the same answer; failures are damped to one attempt per 30 s, so an outage costs at
  most one slow request per damping window.
- **Each replica caches independently.** The snapshot is process-local (no shared store), so
  every worker and every replica performs its own refresh and may briefly serve a different
  tier than its peers during an upstream incident. Sizing note: N replicas ⇒ up to N catalog
  fetches per TTL.
- Listing only: discovery never changes what is dispatchable — admission and chat dispatch are
  untouched. Log lines carry counts, reason codes, the upstream HTTP status code, and the
  served tier
  (`tier=fresh|stale|seeds`, logged on change) — never catalog content.
- **A shifting census fails the refresh, by design.** `total_count` must agree across pages,
  and upstream's count does move between page fetches (measured 418 → 419 seconds apart on
  2026-08-25). Such a refresh is rejected as `model_catalog_truncated`, the previous snapshot
  keeps serving, and the next attempt (after 30 s damping) normally succeeds. Fail-safe and
  self-healing, but expect occasional truncation reasons in the logs that are drift, not loss.

## Live Anthropic Model Discovery (OME-1026)

`GET /v1/models` can also list the Claude models this deployment can actually use now, discovered
from the Anthropic Models API. Anthropic's catalog is credentialed-only, so unlike the OpenRouter
catalog above this is **opt-in** and inert by default: set `AIGW_ANTHROPIC_DISCOVERY_API_KEY` to a
deployment-owned Anthropic key to enable it, unset it to roll back. `AIGW_ANTHROPIC_LIVE_MODELS=false`
is the fast off-switch that keeps the key configured, and `AIGW_DISCOVERY_ENABLED=false` silences it
with all other discovery traffic — each off-switch means the exact compiled seed listing and zero
Anthropic catalog egress. It reuses the same snapshot cache, degrade ladder, single-flight refresh,
per-replica behavior, and `tier=` logging described above.

**Before choosing the key:** the Models API answers for the CALLING key, so that one key's
entitlements decide what every account sees LISTED (dispatch stays per-account). Full operator
guidance — publication of aliases vs date-stamped snapshots, fail-closed cursor-walk semantics,
bounds, and the cost profile — is in
[`docs/anthropic-model-discovery.md`](docs/anthropic-model-discovery.md).

## Operations Notes

- The container listens on `0.0.0.0:9105` and exposes `/healthz`.
- `publicUrl` sets `AIGATEWAY_PUBLIC_URL`, which is used for hosted OAuth callback URLs.
- The migration Job uses the same image and database Secret as the app Deployment.
- The demo DB PVC owns the database state; deleting it deletes the database.
- The Helm chart enables the global response cache by default; it stores plaintext responses and
  has no expiry. Set `config.requestCache.enabled=false` to opt out (see The Global Response Cache).
- CNPG, backups, PodMonitor, and SigNoz/Prometheus integration are follow-up infrastructure work.
