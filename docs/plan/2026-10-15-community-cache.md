# Community cache for local engines — plan (epic OME-1311)

Spec: `docs/spec/2026-10-15-community-cache.md`. Four PRs, one leaf each under
OME-1311, each stacked on the one before and merged in order.

## PR 1 — `aigateway`: the page route and the SQLite loader

0. Model + migration `0015_cache_entry_write_order.py` — index `(updated_at, key_hash)` on
   `request_cache_entries` (spec decision 1).
1. `core/request_cache/community_pages.py` (new) — the cursor (encode/decode
   `(updated_at, key_hash)`); `read_page(after, limit, models)`: the ORM query (no Tavily, not
   expired, optional `model__in`, after the cursor, ordered by `(updated_at, key_hash)`),
   yielding rows in batches of 100 and the next cursor at the end; `count_rows(after, models)`
   for `remaining`.
2. `routes/cache_entries.py` (new) — `GET /v1/cache/entries` under `CurrentAccount`;
   validation (422; `limit` 1..5,000, default 5,000), an NDJSON body streamed batch by batch
   (header line with `schema`, `revisions` from `active_cache_revisions()` and, with
   `count=true`, `remaining`; one line per row; trailer line with `next`),
   `Cache-Control: private, no-store`, gzip when accepted.
3. `main.py` — include the router.
4. `core/request_cache/sqlite_loader.py` (new) — `check_revisions(header, local)` and
   `load_page(rows, database)`: one transaction per call (the SDK calls it per batch), skip
   keys already present, new ids, zero hits; skip and count a row a local lookup could not
   serve. `check_database(database)` before any request.
5. A test pinning that a cache hit leaves `updated_at` unchanged (spec, Risks).
6. `DEPLOYMENT.md` — the route, who can call it, what crosses, the cost of a pull.

No settings; one index migration. Ledger:
`docs/work/2026-10-15-community-cache.md`.

## PR 2 — `screamingface-engine`: the proxy

- A `CommunityCache` port and its AIGateway adapter (pattern: `rest/connections.py`).
- `GET /v1/cache/entries` forwards the caller's identity and the query parameters, and
  passes 401/422 through.
- It streams the gateway's body through as it arrives, still compressed, with its
  `Content-Type` and `Content-Encoding`. Unlike the existing adapters, which read whole
  responses, it never decodes or buffers a page, which can be ~235 MB of rows (spec
  decision 6).
- Merging this PR is what makes the pull reachable in prod.

## PR 3 — `client-sf`: `sf.cache.pull_from_remote` and `use_cache=`

- `screamingface/cache.py` (public namespace) over a private `_cache` package:
  - the hosted page client: its own `Client`-style httpx session against `url` (default
    `DEFAULT_ENGINE_URL`) with the Access auth, `stream("GET", "/v1/cache/entries", …)` with the
    replay-safe extension, gzip accepted, problem+json mapped to SDK errors;
  - the page reader: NDJSON header / rows / trailer, line by line; a page without its trailer
    is discarded and retried;
  - the pull loop: `count=true` on the first request of a call, revisions checked on every
    header against the local revisions (plugins loaded first), page N loaded while page N+1
    downloads, transient failures retried with backoff, the cursor kept in memory per
    `(url, models)` for a repeat call in the same process;
  - the loader call: `aigateway…sqlite_loader.load_page` into `<data_dir>/aigateway.sqlite3`,
    imported lazily behind `require_runtime_extra()`; `not_a_gateway_database` and
    `outdated_gateway_database` turned into "run `screamingface up`" messages;
  - progress: a notebook card through an IPython display handle, a terminal line on stderr,
    the `evaluate` tri-state.
- `use_cache: bool = True` on `Client.evaluate`, `AsyncClient.evaluate`, `sf.evaluate`, carried
  down the same path as `capture` to the run request's `Cache-Control: no-cache`.
- `_runtime/bootstrap.py`: `AIGW_REQUEST_CACHE_ENABLED=true` in `LOCAL_GATEWAY_DEFAULTS`.
- `_runtime/cli.py`: `screamingface cache pull`, a thin wrapper over the same function.
- `__init__.py` / public-surface snapshot, `README.md`, `CHANGELOG.md`.

## PR 4 — `public-docs`: the caching page and the API reference

- `public-docs/src/pages/learn/CachingPage.vue`: the community cache now reaches a local
  engine — `pull_from_remote`, the model filter, sign-in, what crosses, the local cache on by
  default, `use_cache=False`.
- `public-docs/src/pages/sf-client/api/ModulesPage.vue`: an `sf.cache` section and `use_cache=`
  on `evaluate`.

## Follow-ups (separate tickets)

- `version=` filter — blocked by OME-1307.
