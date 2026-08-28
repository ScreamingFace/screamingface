# Live Anthropic Model Discovery (OME-1026)

`GET /v1/models` can list the Claude models this deployment can actually use **now**, discovered
from the Anthropic Models API, instead of only the compiled seed aliases frozen at release time.
A newly released model then appears without an AI Gateway release, and a retired alias disappears
instead of 404-ing at dispatch.

**Default: off.** Unlike OpenRouter's public catalog, Anthropic's is credentialed-only, so this
feature is strictly opt-in and does nothing at all until you configure a key.

## Turning it on

Set one variable:

```
AIGW_ANTHROPIC_DISCOVERY_API_KEY=<an Anthropic API key>
```

This is **deployment configuration**, in the same class as `AIGATEWAY_SECRET_KEY` — not a
per-account credential. It is never written to `credential_blobs`, never used for chat, never
logged, and never part of the discovery cache identity.

Roll back by unsetting it — or by setting it to an empty value, which counts the same: an empty or
whitespace-only key is read as **no key at all**, so no source is declared and nothing is dialed.
(That matters because a declared-but-empty variable is a normal deployment shape rather than a typo:
`${VAR}` interpolation of an unset host variable, an existing-but-empty Kubernetes Secret key, or a
chart that emits every key so an operator's explicit opt-out stays visible in the manifest.) The next
boot serves compiled seeds again. There is no migration and no data to undo.

## The three off-switches

Each of these means the **exact** compiled seed listing and **zero** Anthropic catalog egress:

| Switch | Effect |
|---|---|
| `AIGW_ANTHROPIC_DISCOVERY_API_KEY` unset (the default), **or empty/whitespace-only** | No credential ⇒ no source is declared ⇒ no dial |
| `AIGW_ANTHROPIC_LIVE_MODELS=false` | Fast off-switch that **keeps the key configured** |
| `AIGW_DISCOVERY_ENABLED=false` | Global discovery kill switch; silences this with all other discovery traffic |

Anthropic has no provider-level disable flag, and this unit did not add one.

## What the listing becomes

- **Healthy snapshot:** models explicitly configured in `AIGW_ANTHROPIC_MODELS` first (operator
  intent — they survive every healthy snapshot), then the discovered ids, deduplicated on the
  canonical `anthropic/<id>` form. Compiled defaults absent from the snapshot are **not** listed,
  which is how a retired alias disappears within one TTL.
- **Cold or degraded:** the compiled/operator seeds, byte-identical to the pre-OME-1026 listing.
- **Row shape is unchanged** — only the ID SET becomes live, so existing consumers do not need a
  row-contract change. Historical context: SF-284's `aigw-claude-backend` derived its Settings
  suggestions from this endpoint, but that consumer was removed before the OME-1026 baseline; there
  is no live dropdown integration to validate. Two consequences still matter to any consumer:
  - **Order.** With `AIGW_ANTHROPIC_MODELS` unset, the published order becomes raw upstream order
    rather than the curated seed order. A consumer that treats the first row as its default sees a
    default chosen by upstream.
  - **`supported_parameters` is not uniform across rows.** Sampling evidence
    (`temperature`/`top_p`/`top_k`) comes from a small hand-REVIEWED allowlist of exact model ids;
    every id outside it is fail-closed and its row simply omits those parameters. Discovered ids are
    by definition not yet reviewed, so a newly appearing model — and every date-stamped snapshot,
    even one whose alias is reviewed — publishes a row without sampling parameters until someone
    reviews it and adds it. This is the pre-existing, deliberate fail-closed policy from OME-583 and
    OME-1026 did not change it; discovery only makes it visible on more rows. A consumer that reads
    `supported_parameters` per row is unaffected; one that assumes uniform capability across
    Anthropic rows is not.
- **Aliases and date-stamped snapshots are both published, unfolded** — e.g. both
  `anthropic/claude-opus-5` and `anthropic/claude-opus-5-20260801` when upstream returns both, in
  upstream order (newest-first), with the first occurrence winning on duplicates. Both dispatch,
  and snapshot ids let a caller pin an exact build. The gateway does not infer which alias points
  at which snapshot, because Anthropic publishes no authoritative relation for that.

## Visibility caveat — read this before choosing the key

The Models API answers **for the calling key**, and account entitlements differ. So the operator
key's entitlements define what **every** account sees listed on this deployment. A restricted key
narrows the listing for everyone.

This affects the LISTING only. Dispatch is still authorized per account with that account's own
credential, and a model absent from the listing remains dispatchable. Prefer a key whose account
sees the full catalogue you intend to offer.

## Failure behavior

The degrade ladder, single-flight refresh, per-replica caching, and `tier=fresh|stale|seeds`
logging are the shared mechanics described under *Live OpenRouter Model Discovery* in
`DEPLOYMENT.md`; the Anthropic source declares the same policy (fresh 5 min, stale window 1 h,
failed refreshes damped to one attempt per 30 s). Anthropic-specific points:

- **Fail-closed, all-or-nothing.** This envelope carries no `total_count`, so completeness cannot
  be reconciled by counting: it means the cursor walk terminated on `has_more=false` with monotone
  cursor progress inside every cap. One malformed row, envelope, or cursor fails the **whole**
  refresh. Nothing partial is ever cached as fresh, so upstream schema drift degrades to the last
  good snapshot (then to seeds) rather than publishing a silently shrunken listing.
- **A revoked or throttled key degrades the LISTING, never chat.** Upstream 401/403/429/5xx are
  logged as a sanitized reason plus the exact status code and drop the listing to
  stale-then-seeds. Chat dispatch is untouched — it never consults this key.
- **Bounded everything:** page size 1000 (the whole catalogue is one page in practice, so a
  healthy refresh costs a single request), at most 8 pages, 2000 models, 256-character ids, and a
  10 s aggregate deadline across the walk. A cursor that repeats — including an `a → b → a`
  cycle — is reported as truncation rather than walked further.
- **Cursors are validated before use.** `last_id` is upstream-controlled material that the
  gateway embeds in the next request, so it must match the same conservative charset as a
  publishable id (`^[A-Za-z0-9][A-Za-z0-9._-]*$`) before being URL-encoded into the query.
- **Parameter discovery is unaffected.** `/v1/model-parameters` evidence for Anthropic stays
  `anthropic:static` and byte-identical. OME-479 §6.3 is superseded for the model LIST only, and
  only with this dedicated operator credential.

## Cost note

A healthy deployment makes one Models API request per 5 minutes per replica (the catalogue fits
one page). During a sustained upstream outage the 30 s damping permits up to ~10 attempts per
5 minutes per replica — bounded, but ten times the healthy rate.
