# Community cache for local engines — spec (epic OME-1311)

Status: draft for review (2026-10-15).

## Problem

The community request cache (OME-305) lives in the hosted gateway's Postgres table
`request_cache_entries`. A local engine (`screamingface up`) runs the same AIGateway code on
SQLite and never sees that table, so a local run pays again for calls the community has already
made. Goal of the epic: a signed-in local engine can pull the hosted cache and serve the pulled
rows as ordinary local cache hits.

## What the hosted cache looks like (prod, measured 2026-10-15, read-only)

| | |
|---|---|
| Rows | 595,907, created 2026-08-10 → 2026-10-15 |
| Table on disk | 1.6 GB (821 MB heap, 776 MB indexes and TOAST) |
| Response + metadata text | ~1.85 GB (~400–500 MB gzip'd; samples compressed 3.6–4.7×) |
| Response size p50 / p95 / p99 / max | 470 B / 6.4 KB / 47 KB / 998 KB |
| Providers / models | `openrouter` only / 32 models |
| Tavily rows / expired rows | 0 / 0 (no row has an `expires_at`) |
| Rows hit at least once / total hits | 523,121 / 3,429,374 |

Skewed by model: `gemini-3.1-pro-preview` is 525k rows (88%) of short responses (469 MB); a few
models hold few rows with large responses (e.g. `deepseek-v4-pro-0813`: 4.6k rows, 203 MB,
46 KB per row on average). Growth comes in bursts with benchmark waves: one week (2026-09-28)
added 118k rows and 961 MB.

`updated_at` records when a row's content was last written to this database: a live write
sets it on insert (live writes never overwrite an existing key, `set_if_absent`), and an admin
snapshot *merge* restore sets it to the restore time, both for rows it inserts and for rows it
overwrites. A *replace* restore is the exception: it empties the table and keeps each archived
row's own `updated_at` (decision 13). A cache hit never touches it (0 rows have `updated_at` equal to `last_hit_at`).
`created_at` is not an addition date: restored rows keep their source's value (206,745 rows
share `2026-08-26 00:00`), and three restores on 2026-10-07/08 rewrote ~470k rows.

A cached response is at most 1 MB (`AIGW_REQUEST_CACHE_MAX_RESPONSE_BYTES`). Gateway and Engine
API pods each have a 512 MiB memory limit (using ~270 MiB and ~176 MiB) and a 1-CPU limit;
prod runs one gateway pod.

### Cost of a full pull (measured per page on prod, totals estimated)

| Per page | 1,000 rows | 5,000 rows |
|---|---|---|
| Fetch, ordered by `updated_at` without an index | 268–416 ms (avg 352) | — |
| Fetch, index-ordered (measured on the `key_hash` index as a stand-in) | avg 33 ms | avg 139 ms |
| Gateway JSON encoding + gzip | 13 + 57 ms | ~65 + ~285 ms |
| Size, unfiltered / heaviest model | 2.9–5.3 MB / ~47 MB | ~17 MB / ~235 MB |

Full pull, pages fetched in sequence, assuming ~150 ms per-request overhead through Cloudflare
and the Engine (not measured), a 100 Mbps link and ~50 ms per 1,000 rows of local load:

| | Requests | Gateway + DB | Request overhead | Transfer + load | Total |
|---|---|---|---|---|---|
| No index, 1,000/page | 596 | 251 s | 90 s | ~65 s | ~6.8 min |
| Index, 1,000/page | 596 | 61 s | 90 s | ~65 s | ~3.6 min |
| Index, 5,000/page | 120 | 59 s | 18 s | ~65 s | ~2.4 min |

Without the index every page re-scans and re-sorts the table, so a pull's cost grows with the
square of the table's size. Page size changes only the per-request overhead; per-row work is
the same.

## Decisions

1. **The client pulls pages in write order.** The client asks for the rows after a cursor and
   gets one page plus the next cursor, repeating until the cursor is null. Pages are ordered by
   `(updated_at, key_hash)`: `key_hash` breaks ties (a restore stamps many rows with one
   time), and the cursor is the last row's pair, sent as an opaque token. Ordering by write
   time means a row written during a pull normally lands after the cursor and is picked up by
   the same pull (decision 13 has the exceptions), and it leaves incremental pulls open for
   later. `updated_at` rather than `created_at`, because a merge restore inserts rows with old
   `created_at` values and overwrites rows without changing it; `updated_at` moves in both
   cases and a hit never moves it. A new index,
   `(updated_at, key_hash)`, added by this unit's migration, makes each page an index range
   read.
2. **Through the ORM, in short queries.** The gateway reads a page through the ORM in batches
   of 100 rows, each batch its own keyset query that borrows a pool connection for
   milliseconds. No transaction is held between batches or pages, and nothing is
   Postgres-specific, so the route works on any database the gateway runs on.
3. **Everything by default, or only the models asked for.** `?model=…` (repeatable) restricts
   the pages to those models. The filter is exact: the cache key includes the resolved model, so
   a run can only hit rows for the models its candidates and judge use, and a model-filtered
   pull loses no hits. Values match the `model` column exactly as stored (e.g.
   `openrouter/anthropic/claude-opus-5.5`); an unknown model yields an empty first page.
4. **Signed-in only, not admin.** The route takes any authenticated account (`CurrentAccount`)
   and answers 401 to an anonymous caller (under `AIGW_AUTH_MODE=disabled`, which is
   loopback-only, every caller is the anonymous account and may read). The gateway has no public ingress, so callers reach it
   through the Engine (`fusion.dev.screamingface.ai`, behind Cloudflare Access), which forwards
   the caller's identity as it does for its other gateway calls.
5. **No feature flag, no limits of its own.** It is an ordinary authenticated route, always
   mounted; it becomes reachable in prod when the Engine proxies it (PR 2). Its requests are
   short indexed reads like any other read route's, so it needs no concurrency cap, lock or
   timeout of its own.
6. **Pages of up to 5,000 rows, streamed.** `limit` defaults to and is capped at 5,000. Above
   that the saving is under 10 seconds per full pull (request overhead ~18 s at 5,000, ~9 s at
   10,000), while each request grows longer and an interrupted page costs more to repeat. A
   heavy page is large (~235 MB of rows for the heaviest model), so no hop may hold a whole
   page:
   - the gateway writes each batch to the response as it is read. A batch is at most 100 rows
     and at most 8 MB of responses (one row, if a single response is larger), chosen by a cheap
     size-only query on the stored `response_size_bytes` before the rows are read; the second
     query reads exactly those rows (same key, `updated_at` and size), so a row rewritten in
     between comes later in the walk instead of crossing at its new size, and `next` follows the
     keys scanned, not the rows sent (PR 1 review round 2). A response can
     be up to 1 MB, so a row count alone would let one batch reach ~100 MB, several times that
     while it is encoded; bounded by bytes, a request holds ~24 MB at most whatever the page size
     or filter (revised after the PR 1 review, 2026-10-20);
   - the Engine passes the gateway's bytes through as they arrive, still compressed, never
     reading the whole page (PR 2);
   - the client parses the page line by line (decision 12).
7. **Only shareable cache values cross.** Of `request_cache_entries`: no `provider = 'tavily'`
   rows (their keys hash the caller's account id, so they are one account's private entries and
   useless to anyone else) and no expired rows. Each row carries `key_hash`, `prompt_hash`,
   `provider`, `model`, `response_json` (the stored text, verbatim), `response_size_bytes`,
   `created_at`, `updated_at`, `expires_at` and `metadata_json`. `id`, `hit_count` and
   `last_hit_at` are not sent, so platform usage patterns do not leave; the local loader gives
   each row a new id and zero hits. The table holds no prompts, identities or credentials.
8. **Progress, on request.** With `?count=true` the header line carries `remaining`: the
   number of rows matching the filter after the given cursor (all of them without one), from
   one `count(*)`. Without it the header omits `remaining`. The client asks on the first
   request of every session, fresh or resumed, and shows rows loaded against it. Counting on
   every page would scan the remaining rows each time (~120 scans per full pull) to report a
   number that barely moves. The figure is approximate: rows written during the pull are not
   in it, so if loaded rows pass it (a burst of writes mid-pull) the client may ask again.
9. **Resume, within one process.** The cursor (`next`) is the whole state, and the client keeps
   it in memory: a transient page failure (a dropped connection, a 502/503/504, a timeout) is
   retried inside the call with backoff, and calling `pull_from_remote` again in the same
   process with the same `url` and filter continues from the last committed page. Nothing is
   written to disk: a pull whose process ended (a kernel restart, a killed CLI) starts over.
   That is cheap because loading is idempotent (decision 11) — a restart only re-downloads
   pages whose rows are already local, at most a full pull's ~2.4 minutes. An on-disk cursor is
   a follow-up if restarts start to hurt.
10. **Revisions on every page.** Each page carries `revisions` (the gateway's
    `active_cache_revisions()`). The client compares them with its local gateway's and stops on
    any mismatch: rows keyed under another revision would load and then never hit. A change
    mid-pull (the hosted gateway was redeployed) also stops it; the next pull starts over.
11. **Local load: a transaction per batch, as the page streams in** (revised after the PR 1 and
    PR 3 reviews). The client loads a page's rows in batches as they arrive, each batch one
    `load_page` call and one transaction into the local SQLite `request_cache_entries`, skipping
    any row whose `key_hash` the local cache already has. So the download and the load overlap,
    and no page is held whole. A transaction spanning a page would hold SQLite's single write
    lock for the page's whole download, while the running gateway's own writes wait only 5 s for
    it. The database is checked (`check_database`: it exists, has the current schema and the
    unique key on `key_hash`) before any request. Only a row a local lookup can serve is written:
    both hashes SHA-256 hex, text fields within their columns, `response_json` accepted by the
    lookup's own decoder (`store.decode_cached_response`), timestamps in range, not expired;
    `response_size_bytes` is measured from `response_json`, never taken from the page; unreadable metadata is stored as NULL, as a lookup would read it. A row that fails is
    skipped and counted (`PageLoad.skipped`), never written, so it can neither hold its key
    against a later valid row nor stop the pull (owner decision, 2026-10-20). The cursor still
    only advances past a page that ended with its trailer.
12. **Newline-delimited JSON, gzip'd.** A page is NDJSON: a header line (`schema`,
    `revisions`, and `remaining` when asked), one line per row, and a trailer line carrying
    `next`. Each line parses on its own, so neither the gateway nor the client holds a whole
    page; a page without its trailer was cut off and the client discards it. The gateway
    gzip-compresses the body when the client accepts it, and the Engine passes the encoding
    through.
13. **What a pull promises.** Every eligible row written before the pull reaches the end is
    included, apart from a row whose write commits after the cursor has passed its timestamp:
    `updated_at` is set when the write starts, not when it commits. For a live write that window
    is milliseconds; for a merge restore it is as long as the restore's transaction. A replace
    restore keeps the archive's `updated_at` values, so a pull under way when it commits misses
    every restored row behind its cursor. Such rows come with the next pull, which in v1 always
    walks from the start (a finished pull ends with `next: null`). A row a restore overwrites mid-pull arrives again later in the same
    pull, and the loader keeps whichever version is already local (decision 11).
14. **SDK surface: one verb and one per-call switch** (settled 2026-10-16).
    - `sf.cache.pull_from_remote(models=None, *, url=None, progress=None) -> PullResult` pulls
      into the local gateway database (`<data_dir>/aigateway.sqlite3`). `models=None` pulls
      everything. `url=None` is the hosted production Engine (`DEFAULT_ENGINE_URL`); it never
      follows `default_client()` or `SCREAMINGFACE_ENGINE_URL`, which point at the local stack
      or at wherever runs go — the pull's destination, not its source. Sign-in is the existing
      in-memory Cloudflare Access flow (one browser login per process): a pull reuses the
      default client's session when that client is already open on the same Engine, and
      otherwise keeps its own client per Engine for the process. It needs the
      `screamingface[runtime]` extra (the loader lives in `aigateway`) and imports it lazily, so
      `import screamingface` stays light. Before the first page it loads the gateway's provider
      plugins so the local revisions include the adapters' (today `openrouter_adapter`), the ones
      every hosted row is keyed under. `PullResult` reports rows read, rows added, pages,
      whether it resumed and whether it finished; an interrupted pull re-raises its
      `KeyboardInterrupt` with the same counts as `.result`. A resume continues only into the
      database file it was loading (its device and inode), not merely the same path.
    - Progress follows `evaluate`: `progress=None` shows it in a notebook or an interactive
      terminal and stays quiet when piped. A notebook gets one card updated in place through an
      IPython display handle (no `ipywidgets` needed); a terminal gets one line on stderr
      rewritten in place, or a line per ~10% when not interactive and forced on. Both show rows
      against `remaining`, rows added, bytes, elapsed and an ETA.
    - `use_cache: bool = True` on every `evaluate` (`Client`, `AsyncClient`, `sf.evaluate`;
      Recipes and raw URL4). `False` sends `Cache-Control: no-cache` on the run request, which
      the Engine collapses to `use-cache: false` on every model call of that run; the report
      shows them as `bypass` / `opted_out`. `True` sends nothing (the Engine's default is on).
    - The local gateway caches by default: `screamingface up` sets
      `AIGW_REQUEST_CACHE_ENABLED=true` as a local default (an exported value still wins).
      Pulled rows only help when it is on. There is no `enable()` / `disable()` — the operator
      switch is read at boot, so a function that only took effect after a restart would promise
      more than it does — and no `status()` for v1.
    - CLI: `screamingface cache pull [--model M]… [--url U] [--data-dir D]`, always with
      progress; exit 0 finished, 1 refused or failed (one-line reason), 130 interrupted.

## Wire contract

Gateway (the Engine exposes the same path and forwards it):

```
GET /v1/cache/entries[?after=<cursor>][&limit=<1..5000>][&count=true]
                     [&model=<model>&model=<model>…]
Authorization: <any signed-in account>

200  Content-Type: application/x-ndjson   (Content-Encoding: gzip when accepted;
     406 when neither gzip nor identity is)
     Cache-Control: private, no-store

     {"schema": "screamingface.cache-page.v1", "revisions": {"parameter_contract": "…", …},
      "remaining": 595907}                              // only with `count=true`
     {"key_hash": "…", "prompt_hash": "…", "provider": "…", "model": "…",
      "response_json": "…", "response_size_bytes": 1234, "created_at": "…",
      "updated_at": "…", "expires_at": null, "metadata_json": "…"}
     …                                                  // one line per row
     {"next": "<cursor>" | null}                        // opaque; null: no more rows

401  no identity
422  `after` not a valid cursor; `limit` out of range; a `model` empty or over 255 chars
```

(Lines are shown wrapped; on the wire each is one line.)

## Alternatives considered

- **Order pages by `key_hash`** (already indexed, no migration). Rejected: the key is a
  SHA-256, so a row written during a pull is included only by chance, and incremental pulls are
  impossible.
- **Five parallel 1,000-row requests instead of 5,000-row pages.** Rejected: cursor pages are
  sequential, so parallel requests need ranges split up front (a full sort to find balanced
  split points, since writes come in bursts), an upper bound on the route, and five cursors to
  resume. It would not be faster: one gateway pod with one CPU does the same encoding work,
  and the connections share the same bandwidth (~2.2–2.5 min against ~2.4 min). It would also
  put several heavy requests from one user on the pod at once.
- **Download everything, then load it in one transaction.** Rejected: an all-or-nothing load
  protects nothing, since rows are independent; it needs the whole download staged on disk
  (~450 MB compressed, ~1.85 GB raw), a journal of similar size, and holds SQLite's write lock
  for the whole load, so a local run writing to the cache meanwhile fails.
- **One streaming download per pull** (`COPY … TO STDOUT` gzip'd straight to the caller).
  Rejected: a full pull is minutes long, so it needs a dedicated database connection held for
  the duration (the ORM pool has 5 connections per pod, shared with `/v1/chat/completions`) and
  one long transaction; it is Postgres-only; it needs a stall timeout and a concurrency
  safeguard; and it gives neither progress nor resume.
- **An archive exported on demand and kept on the gateway pod for a TTL** (a `latest` route
  returning a stamp and manifest, then a download by stamp). Rejected:
  - the ~500 MB archive exceeds the export size cap (256 MB), which cannot be raised without
    also raising the admin upload cap;
  - it occupies that much pod disk for the whole TTL;
  - with more than one gateway pod each exports its own stamp, so the two-step fetch can reach
    a pod that has never seen the stamp;
  - filters would need one archive per filter combination.
- **A scheduled publish to object storage or a CDN.** Not now: new infrastructure, data up to a
  period stale, and it raises the anonymous-access question. The likely route for anonymous
  distribution later, which needs product sign-off.
- **Pull by benchmark** (tag rows, or precompute a benchmark's keys). Rejected: rows carry no
  benchmark link and one key can serve several benchmarks; keys depend on the candidates
  passed to `sf.evaluate`; multi-pass, fusion and judge prompts contain earlier outputs, so
  those keys cannot be known before the run.
- **Runtime read-through** (the local gateway asks the hosted cache on every miss). Deferred:
  a network round trip per call and a hard dependency on the hosted service during runs; the
  epic's agreed direction is a pull.

## Out of scope (v1)

Incremental pulls (only rows written since the last pull: write order makes this a matter of
keeping the last cursor and re-reading a margin before it, but the margin and its interaction
with restores need their own decision); other filters (`provider`; `version=`, blocked by
OME-1307); anonymous or CDN distribution; an on-disk resume cursor; a runtime toggle of the
local gateway's cache switch; pushing local results to the community cache.

## Risks

- An unfiltered pull is ~120 requests and ~400–500 MB transferred, growing in bursts. Each
  request is cheap for the database; the model filter is the reduction available today.
- Gzip is the largest gateway cost (~57 ms per 1,000 rows on a 1-CPU pod), spent only while a
  pull is running.
- `count=true` costs one `count(*)` over the rows after the cursor, up to a full index scan of
  a table that keeps growing. Clients ask once per session. Cheap today; if it ever is not,
  it can become an estimate.
- The new index is built when the migration runs; on ~600k rows that is seconds, during which
  writes to the table wait.
- `updated_at` must keep meaning "content written": code that saved a row through the ORM on a
  hit would bump it, and pulls would keep re-sending hit rows. A test pins that a hit leaves it
  unchanged.
