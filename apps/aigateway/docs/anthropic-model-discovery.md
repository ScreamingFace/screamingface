# Private Anthropic Model Discovery (OME-1026)

An account that has stored an Anthropic API key can ask what **its own key** may call explicitly:

```
GET /v1/auth/anthropic/profiles/{name}/models
```

The same private catalog is composed implicitly into `GET /v1/models`: hosted mode resolves the
Profile named `default`; local mode resolves the sole active Connection, regardless of label.

The answer is discovered using that effective credential's already-stored key, so the owner never
re-enters it. A private row may appear only in that authenticated caller's response; it never enters
the deployment-global catalog or another account's response. Missing, unsupported, ambiguous, or
failed discovery retains the compiled Anthropic seeds.

## Two discovery scopes

| Scope | Who sees it | Credential | Providers |
|---|---|---|---|
| `PUBLIC_GLOBAL` | every account, via `GET /v1/models` | none | OpenRouter |
| `PROFILE_CREDENTIAL` | one credential's owner, via the explicit endpoint or their `/v1/models` | that Profile/Connection's stored key | Anthropic |

A provider declares its scope, and the two paths are separate code: a `PUBLIC_GLOBAL` provider
implements `discover_live_models`, a `PROFILE_CREDENTIAL` provider implements
`discover_profile_models`. Anthropic deliberately does **not** implement the public hook, and the
shared catalog refuses the private scope before it consults a source. `/v1/models` composes its
caller's private result separately, without publishing it into that shared catalog.

Designed for, but not implemented by, this unit: public Hugging Face discovery (`PUBLIC_GLOBAL`,
OME-1035) and profile-scoped direct OpenAI/Gemini discovery (`PROFILE_CREDENTIAL`).

## There is no deployment discovery credential

`AIGW_ANTHROPIC_DISCOVERY_API_KEY` **does not exist.** An earlier draft of this feature used one
deployment-owned key whose entitlements defined what every account saw listed; that design was
rejected, and the setting was removed rather than deprecated. Setting the variable has no effect.

Anthropic credentials remain per-account Profile or Connection credentials in `credential_blobs`
(AES-256-GCM), and private discovery reads them through the same credential strategy chat uses.
Only the header projection differs (`x-api-key` for the REST catalog).

## Off-switches

| Switch | Effect |
|---|---|
| `AIGW_ANTHROPIC_LIVE_MODELS=false` | Anthropic declares no discovery scope: the endpoint answers `status=fallback`, `reason=discovery_disabled` with the compiled catalog, and dials nothing |
| `AIGW_DISCOVERY_ENABLED=false` | Global discovery kill switch; silences this with all other discovery traffic, same answer shape |

Each means the **exact** compiled seed listing and **zero** Anthropic catalog egress. Nothing needs
turning *on*: the caller's effective API-key credential is the opt-in.

## What the endpoint returns

```json
{
  "object": "list",
  "provider": "anthropic",
  "profile": "work",
  "status": "fresh",
  "reason": null,
  "data": [ { "id": "anthropic/claude-opus-5", "object": "model", "owned_by": "anthropic", ... } ]
}
```

Rows are shaped exactly like `GET /v1/models` rows (same `model_row` builder), so a consumer can
use either endpoint with one row parser.

`status` is the trust label:

| `status` | Meaning | `data` |
|---|---|---|
| `fresh` | live snapshot inside its TTL | discovered rows |
| `stale` | last-good snapshot past TTL; a refresh is running behind this response | discovered rows |
| `refreshing` | no snapshot yet; one is being fetched and outlasted the wait budget | compiled seeds |
| `fallback` | no live listing — see `reason` | compiled seeds |

`reason` is a sanitized code, never upstream text. The complete emitted vocabulary:

| Group | Codes |
|---|---|
| Refusals (no dial) | `discovery_disabled`, `not_profile_scoped`, `profile_not_authenticated`, `unsupported_auth_type`, `missing_credential` |
| Refresh coordination | `refresh_deferred`, `refresh_superseded`, `no_snapshot`, `internal_error` |
| Transport / fetch | `timeout`, `unreachable`, `bad_status`, `bad_content_type`, `oversized`, `unsupported_encoding`, `insecure_scheme`, `origin_not_allowed` |
| Payload | `malformed_json`, `too_deep`, `too_many_nodes` |
| Catalog shape (provider refused its own walk) | `model_catalog_empty`, `model_catalog_truncated`, `model_catalog_too_large` |
| Cache capacity (this worker refused to retain it) | `cache_row_budget_exceeded` |
| Last resort | `unavailable` — a degraded answer whose cause was not recorded |

On `stale` **and** on `fallback`, `reason` is present only when a failure or refusal produced that
answer. The ordinary stale-while-revalidate path — a snapshot past its TTL with a refresh running
behind the response and nothing wrong — carries `status=stale` with **`reason: null`**. A non-null
reason on `stale` therefore means "the list is not advancing, and here is why"; a null one means
"the list is simply being revalidated".

**`fresh` is decided by age, never by the fact that rows were retained.** A snapshot inside its TTL
is `fresh`; past the TTL it is `stale` while it is still inside the stale window, and `fallback`
after that — including when the answer follows a refusal such as `cache_row_budget_exceeded`. A
retained entry whose refresh was refused therefore cannot be relabelled `fresh` by that refusal, and
the age comparison is made against the same clock the store was written with.

**Never an outage.** A rejected key, a slow catalog, and an unsupported auth type all answer `200`
with the compiled catalog plus a reason. The endpoint describes the listing; a `5xx` would make a
polling UI look broken and would hide the catalog the owner can still use.

## Timing: a bounded wait, unbounded work

- A **cold** profile waits at most **3 seconds**. If the refresh has not landed by then the answer
  is `refreshing` — and the refresh **keeps running**, so the next request sees `fresh`. The wait is
  bounded; the work is not cancelled.
- That 3 s is a **hard maximum, not a default.** `AIGW_DISCOVERY_TIMEOUT_SECONDS` is the provider
  *dial* deadline: raising it above 3 s (for a slowly paginating catalog) cannot lengthen any
  caller's wait, and a value below 3 s is honoured as-is. `GET /v1/models` obeys the same ceiling.
  The provider's own aggregate pagination deadline is unaffected, and a request whose budget expires
  never cancels the shared refresh it was waiting on.
- A **stale** profile answers immediately with the last-good listing and revalidates behind the
  response.
- Storing or replacing an api key starts discovery **post-commit without waiting**, so the list is
  usually warm before the owner looks at it — and publishing a credential never inherits the
  upstream catalog's latency or its failures.
- Concurrent requests for one profile share **one** upstream attempt.

## Auth types

Only **api-key** profiles do private discovery. A Claude-subscription **OAuth** profile answers
`status=fallback`, `reason=unsupported_auth_type` and spends **zero** credentialed requests: the
refusal is made from the profile's declared auth type, before any credential is decrypted.
Anthropic's `/v1/models` is verified for API keys only, and using a subscription token there has
not been probed.

## Isolation and lifecycle

- The cache identity is `(account_id, provider, profile_name, credential_revision)`. Two accounts
  with a profile of the same name hold two unrelated listings.
- Connection-backed identities use a fresh row UUID plus an API-key ownership generation. API-key
  replacement advances it; generic OAuth activation and refresh do not claim an ownership change.
- More than one active local Connection is ambiguous. A Connection labelled `default` never
  breaks that tie for an implicit request.
- `credential_revision` is a **non-secret** generation token derived from the profile's auth type
  and its **durable ownership generation** — the strictly-advancing counter the profile index bumps
  inside the atomic CAS that publishes a credential. Never from the key, and never from a
  wall-clock stamp: two replacements inside one clock tick used to produce equal identities, so the
  first key's snapshot could be served under the second. A snapshot gathered under a previous
  credential generation is unreadable under the new one, so a rotated key cannot serve the old
  catalog even if no invalidation ran at all.
- Storing, replacing, re-authenticating, or deleting a profile drops its snapshots and **cancels**
  any in-flight refresh, so a request started by the previous credential cannot publish over the new
  owner's listing.
- A **credential-generation change** is an ownership change: replacing the key, re-authenticating,
  switching auth type, changing owner, and delete/recreate all bump the generation. A routine
  same-owner token refresh does **not** — it renews the stored token under the same owner, so it
  keeps the profile's warm listing instead of retiring it.
- **Automatic token refresh does not reach this cache.** A chat request whose OAuth token is near
  expiry renews it through the shared cached strategy for that credential, outside any publication
  transaction. That path cannot affect a discovery snapshot, because discovery is **API-key only**:
  an OAuth profile is refused with `unsupported_auth_type` before its credential is ever read, so no
  OAuth profile has a listing to corrupt. The generation fence that guards this cache is driven by
  the profile-index CAS on the API-key and lifecycle paths above. Ownership-fencing the automatic
  OAuth refresh publication itself is tracked as separate work and is not part of this unit.
- **Refresh conflict.** A refresh captures the owning generation *before* it calls the provider and
  publishes under both checks at once: the profile row must still be present at that generation and
  auth type, and the stored credential bytes must still be the ones the refresh read. If a
  replacement committed while the refresh was in flight, publication is refused with
  `409 {"code": "credential_owner_changed"}` and **nothing** is written — not the token, not the
  profile metadata, not the auth type, not the generation — and the new owner's listing is left
  warm. Retry against the new credential if the refresh is still wanted.
- Another account asking for the same profile name gets `404` — the lookup is scoped to the caller's
  account, so there is no query that could reach someone else's row.

## Bounds and cost

- Snapshots and in-flight refresh tasks are each bounded by
  `AIGW_DISCOVERY_CACHE_MAX_ENTRIES` (default 512), evicting least-recently-used. At capacity a new
  profile degrades to `fallback`/`refresh_deferred` rather than growing the map.
- Retained model **rows** are bounded independently by `AIGW_DISCOVERY_PROFILE_CACHE_MAX_ROWS`
  (default 16384), because an identity count bounds nothing about size: 512 identities × a 2000-model
  walk would admit over a million retained rows per worker. This is a **row count, not a byte
  budget** — no per-row byte size is claimed, because none has been measured.
- The row maximum is **hard: there is no carve-out.** A single snapshot larger than the whole budget
  is refused rather than cached, with `reason=cache_row_budget_exceeded`; the refusal is damped by
  the same provider failure TTL as any other failure, so it does not re-dial per page load. The
  profile keeps its previous snapshot when it has one (`status=stale`) and answers with the compiled
  seeds otherwise. Raise the row budget to admit such a catalog. Distinct from
  `model_catalog_too_large`, which means the *provider* refused its own walk.
- Freshness policy (provider-declared): fresh 5 min, stale window 1 h, failed refreshes damped to
  one attempt per 30 s — so a revoked key costs at most one upstream 401 per 30 s per replica, not
  one per page load.
- Per-replica, process-local caches: N replicas ⇒ up to N refreshes per TTL **per active profile**.
  The cost driver is the number of *profiles whose owners are looking*, not the number of accounts.
- Walk bounds are unchanged: page size 1000 (the catalogue is one page in practice), at most 8
  pages, 2000 models, 256-character ids, 10 s aggregate deadline. Cursors are validated against the
  publishable-id charset before being embedded in the next request.
- **Fail-closed, all-or-nothing.** One malformed row, envelope, or cursor fails the whole refresh;
  nothing partial is ever cached as fresh, so upstream schema drift degrades to the last good
  snapshot and then to seeds.

## Consumer notes

- **Order.** With `AIGW_ANTHROPIC_MODELS` unset, a discovered listing is in raw upstream order
  rather than curated seed order. A consumer that treats the first row as its default gets a default
  chosen by upstream.
- **`supported_parameters` is not uniform across rows.** Sampling evidence
  (`temperature`/`top_p`/`top_k`) comes from a small hand-**reviewed** allowlist of exact model ids;
  every id outside it is fail-closed and its row omits those parameters. Discovered ids are by
  definition not yet reviewed, so a newly appearing model — and every date-stamped snapshot, even
  one whose alias is reviewed — publishes a row without sampling parameters until someone reviews it
  and adds it. This is the pre-existing OME-583 policy; discovery only makes it visible on more rows.
- **Aliases and date-stamped snapshots are both published, unfolded** — e.g. both
  `anthropic/claude-opus-5` and `anthropic/claude-opus-5-20260801` when upstream returns both, in
  upstream order, first occurrence winning on duplicates. The gateway does not infer which alias
  points at which snapshot, because Anthropic publishes no authoritative relation for that.
- **Listing is not dispatch readiness.** Appearing here means the profile's credential can *see* the
  model. It adds nothing to the router and removes nothing: admission and dispatch are unchanged,
  and a model absent from this listing may still be dispatchable.
- **Parameter evidence stays static, but private IDs resolve.** Every row carries a
  `parameter_contract_url`. Follow it with the same gateway authorization and `X-Profile` header:
  a discovered-only ID resolves for the account/profile that discovered it, while another account
  or sibling profile receives `model_not_found`. The Anthropic evidence remains
  `anthropic:static`; live model discovery does not invent parameter support.
