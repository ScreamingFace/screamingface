---
title: Cache Tavily retrieval results in aigateway
ticket: OME-1043
status: approved
date: 2026-08-31
---

# Cache Tavily retrieval results in aigateway

## Problem

Tavily-backed retrieval executes inside the Runner Job (`runner/web_tools.py`) and never
traverses aigateway, so it has no cache at all. An identical request pays Tavily on every run.

The larger half of the cost is second-order. aigateway's global cache hashes `messages`
**verbatim** (`global_eligibility.PROMPT_FIELDS`), and a tool result is appended to `messages`
and re-sent on every later iteration. Non-deterministic Tavily output therefore permanently
poisons the continuation chat call's key. For an identical user request today:

```
turn 1 chat call ......... CACHE HIT  (works already)
Tavily /search ........... fresh results, DIFFERENT bytes every time
continuation chat call ... CACHE MISS, permanently, by construction
```

The continuation is the expensive call — it carries up to `web_tool_max_result_bytes`
(32 KB ≈ 8K tokens) of injected content, re-sent per iteration, with
`web_tool_max_iterations = 12` in `url4.toml`. Caching retrieval saves Tavily credits **and**
restores byte-identical tool results, which is what unlocks the existing chat cache for the
whole loop.

Rough envelope for a DRACO-style run (8 candidates × 50 cases, ~2 iterations, ~2 tool
calls/turn): ~1,600 Tavily calls ≈ $13, plus ~$19 of extra model input from re-sent tool
results — ~$30/run, effectively 100% re-paid on every identical re-run. Storage is ~13 MB/run
before dedup. **Regime: one Postgres table, point lookups by hash. No Redis, no sharding.**

## Decision

**Strategy B′ — Tavily execution stays in the Runner; aigateway stores the results only.**

Alternatives considered and rejected:

- *Tavily as an aigateway provider plugin* (aigateway calls Tavily). Architecturally cleanest
  and would move the credential to where credentials belong, but the owner ruled Tavily may
  not live in aigateway.
- *A generic client-keyed cache API*. Rejected: it inverts the invariant that ONE pure
  server-side function owns the key, so two Runner versions with different normalization would
  silently split or share rows. OME-777/D2 deleted an env-var-shaped request modifier for
  exactly this reason.
- *Runner-local in-process memo only*. Solves intra-run duplication but nothing survives the
  Job, so the stated cross-run cost remains. Recorded as a follow-up.

### Locked decisions (owner, 2026-08-31)

| Decision | Value |
|---|---|
| Where Tavily runs | The Runner. aigateway holds no Tavily credential and makes no Tavily call. |
| Who derives the key | aigateway, server-side, from a structured description of the request. |
| Storage | Reuse `request_cache_entries` — `provider='tavily'`, `model=<tool>`, `prompt_hash=key_hash`. Zero migration. |
| TTL | None. `expires_at = NULL`, 1:1 with the chat lane. Manual pruning is the correction path. |
| Naming | The table is shared, so every other layer is Tavily-explicit: module, store, key builder, route path. |
| Configuration | **None.** The lane is unconditional — no env var, no chart value, no availability gate. |
| v1 scope | Cache only. No in-run single-flight memo. |

Accepted consequence of the TTL decision: a stale web result can be served indefinitely. The
correction path is the per-provider reset already documented in `DEPLOYMENT.md`,
`DELETE FROM request_cache_entries WHERE provider = 'tavily'`, which works unchanged because
rows carry their provider.

## Invariants inherited from OME-305 / OME-777

1. The key is built by one pure, server-side function and is identity-free — no account,
   profile, auth mode or credential term exists on its signature.
2. Insert-only fill, first fill wins; a race is confirmed before being reported, never
   resolved by overwriting.
3. A cache failure is **always** a bypass, never an error into the request path. The cache may
   not become an availability dependency of a run.
4. A closed bypass vocabulary, published in `Cache-Status` (RFC 9211) and the `X-AIGW-Cache*`
   triple, so the Runner's existing total parser `runner/cache_readback.read_cache_outcome`
   is reused unchanged.
5. `excluded_domains` participates in the key. **This is security-critical:** without it a row
   filled by an unrestricted caller could be served to a run whose retrieval policy excludes
   arxiv/semanticscholar, and the cache would silently defeat DRACO's leakage control. A cached
   hit returns an already-formatted string that cannot be re-filtered, so the key is the only
   place this property can live.

## Interface

Two POST endpoints. `POST` rather than `GET` because the query is user content and must not sit
in a URL, and because this is our cache rather than an HTTP intermediary cache.

**A miss is a `200` answer, not a `404`** — following the house precedent of
`POST /v1/models/admit`: "a refusal is a 200 ANSWER carrying a diagnostic code, never an HTTP
error". The Runner's next move needs the body either way.

```
POST /v1/retrieval/tavily/cache/lookup
{"provider":"tavily","tool":"web_search","query":"…",
 "search_depth":"advanced","max_results":5,"excluded_domains":["arxiv.org"]}

200  Cache-Status: aigateway; hit; key=a1b2c3d4
     Age: 3600
     {"status":"hit","result":"Title: …\nURL: …\nContent: …"}

200  Cache-Status: aigateway; fwd=miss
     {"status":"miss","result":null}

200  Cache-Status: aigateway; fwd=bypass; detail=disabled
     {"status":"bypass","reason":"disabled","result":null}
```

```
POST /v1/retrieval/tavily/cache/entries
{…identical description…, "result":"…"}

200  {"outcome":"stored"}        # or "race_lost" | "not_stored"
```

`200` with an outcome code rather than `201 Location`: the Runner already holds the value,
nothing dereferences a location, and a failed fill must never look like a request failure.

`422` with this app's existing `{"code":…,"message":…}` detail shape — the codebase does **not**
use RFC 9457, so the codebase wins — for: unknown `provider`/`tool`, empty `query`/`url`,
`max_results` out of range, malformed `excluded_domains`, or `result` over 256 KB.

Authentication is `CurrentAccount`, like every other route. Identity gates **who may ask** and
never enters the key.

## Key material

```python
@dataclass(frozen=True, slots=True)
class TavilyRetrievalCacheKey:
    provider: str                        # "tavily"
    tool: str                            # "web_search" | "web_fetch"
    target: str                          # normalized query, or normalized URL
    search_depth: str | None             # web_search only
    max_results: int | None              # web_search only
    excluded_domains: tuple[str, ...]    # sorted, normalized — LOAD-BEARING
    retrieval_contract_revision: str     # "aigw-tavily-retrieval-2026-08a"
```

`key_hash` comes from the **existing** canonicalizer in `global_keys.py`. A hand-rolled one is
how the DRACO backfill tool silently keyed wrong on U+2028 — do not write a second one.

**Mechanism (owner decision, 2026-08-31): one new public wrapper, nothing moved.** The generic
helpers (`_canonical_json`, `_sha256`, `_require_json_safe`) stay private where they are.
`global_keys.py` gains one additive public function:

```python
def canonical_digest(mapping: Mapping[str, Any]) -> str:
    _require_json_safe(mapping, depth=0)
    return _sha256(_canonical_json(mapping))
```

Rejected alternatives: extracting the three helpers into a shared `canonical.py` (relocates
code inside a security-critical proven file, and exposes three primitives where a caller could
use the formatter while skipping the guard); duplicating the four `json.dumps` options in the
retrieval module (two copies of a byte-exact contract with nothing forcing them equal).

Why the wrapper is sufficient AND safer:

- No second copy of the rules exists — it is composed of the same privates, so editing
  `_canonical_json` changes both lanes at once.
- The json-safety guard becomes **non-optional**: canonical bytes are unreachable without it,
  so no caller can lose the non-string-object-key refusal that would let two different
  requests collide on one entry.
- It returns the **digest only**, preserving the existing rule that the canonical string —
  which holds caller text verbatim — never leaves that module.

The lane supplies its own mapping, and `schema` + `operation` live INSIDE the hashed mapping
exactly as `_canonical_mapping` does for chat. `operation = "retrieval.tavily"` versus
`"chat.completions"` makes the two lanes' key spaces provably disjoint, and lets Tavily rows be
abandoned by bumping only `TAVILY_RETRIEVAL_CONTRACT_REVISION`.

`CanonicalizationError` propagates unchanged, so the route maps it to the same
`canonicalization_failure` bypass reason the chat lane already publishes.

Accepted minor coupling: `tavily_retrieval.py` imports `global_keys.py` (one-way, no cycle). If
that ever becomes awkward the wrapper moves to its own module with no call-site change.

Normalization is a reviewed decision, not a convenience:

- **`web_fetch` URL** — lowercase scheme and host, drop a default port and the fragment; keep
  path case, the query string, and `utm_*`. Over-normalizing silently serves the wrong page,
  so v1 fails conservative: two URLs that differ are two rows.
- **`web_search` query** — `strip()` + NFC, case preserved verbatim, mirroring "prompt material
  is hashed verbatim".

### Deliberately absent from the key

- `tavily_timeout_s` — transport only, mirroring `EXCLUDED_TRANSPORT_FIELDS`.
- `web_tool_max_result_bytes` — truncation stays on the read side (`append_tool_results`), so
  re-tuning the cap does not abandon the corpus.
- `tavily_base_url` — one Tavily endpoint per deployment and the table is per-deployment, so it
  is constant within a cache's scope. **Documented limitation:** one gateway fronting two
  different Tavily endpoints would need a key field.

## Storage

Reuse `request_cache_entries` through a Tavily-named store: `provider='tavily'`,
`model=<tool>`, `prompt_hash=key_hash` (the chat lane already sets `prompt_hash == key_hash`),
`expires_at=NULL`.

Mirror `TortoiseRequestCacheStore`'s exception discipline exactly: insert-only;
`IntegrityError` → confirm the winner exists before reporting `race_lost`; infrastructure
errors → `not_stored` with a warning; and the `except IntegrityError` clause stays **above**
the infrastructure clause (the MRO trap is documented at that call site).

## Configuration

**None — the lane is unconditional (owner decision, 2026-08-31).** There is no env var, no
chart value and no availability gate. Retrieval results are always cached.

An operator switch was drafted (`AIGW_TAVILY_RETRIEVAL_CACHE_ENABLED`, app-off/chart-on,
mirroring the response cache) and then **removed** on the owner's instruction: "we don't need
another layer of configuration." Consequences accepted with it:

- Every deployment shares retrieval results across accounts, with no way to opt a deployment
  out. Combined with the no-expiry decision, the only correction is the documented
  per-provider reset.
- The `disabled` bypass reason therefore never appears on this lane. `cache_unavailable` — a
  runtime store failure, which is degradation rather than configuration — is the only reason it
  publishes, so `PUBLISHED_CACHE_REASONS` needs no new member.
- `TavilyRetrievalCacheStore` takes no constructor argument, and a test asserts that, so a
  configuration layer cannot quietly reappear.

## Out of scope

- Any aigateway → Tavily call, or a Tavily credential in aigateway.
- A migration or a new table.
- A TTL, a sweeper, or a caller-facing opt-out beyond the operator switch (the Runner's
  existing `CachePolicy` covers per-run intent for chat and is not extended here).
- In-run single-flight (follow-up), retrieval outcomes in run accounting (follow-up).

## Risks

| Risk | Mitigation |
|---|---|
| A cached row defeats a benchmark's domain exclusions | `excluded_domains` is in the key; dedicated test. |
| Stale web content served forever | Accepted by decision; per-provider reset documented. |
| A malicious in-cluster peer pre-fills popular queries | Not a new trust boundary — the same NetworkPolicy peers can already forge `X-User-Email`. Keys are server-derived, so an attacker can only fill a key they could have legitimately requested, and insert-only means no overwrite. |
| Cold-key stampede across concurrent Jobs | Bounded by run concurrency; the in-run memo follow-up narrows it. |
| The shared table mixes lanes | Rows carry `provider`, so listing, reset and admin surfaces already discriminate. |
