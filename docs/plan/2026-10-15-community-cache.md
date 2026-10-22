# Community cache for local engines — plan (epic OME-1311)

Spec: `docs/spec/2026-10-15-community-cache.md`. Three PRs, one leaf each under
OME-1311, merged in order.

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

## PR 3 — `client-sf`: `sf.cache`

- `sf.cache.pull_from_remote(models=None)`: page through the Engine route with the signed-in
  identity; parse each page line by line; check the header's revisions against the local
  gateway's `active_cache_revisions()` on every page; discard a page without its trailer; load
  page N while page N+1 downloads; send `count=true` on the first request of every session,
  fresh or resumed, and show progress against `remaining`; record the cursor after each page
  commits and resume from it.
- `sf.cache.enable()` / `disable()` / `status()`; the local request cache on by default in the
  local runtime.
- CLI `screamingface cache pull [--model …]`.
- Public docs: the caching page.

## Follow-ups (separate tickets)

- `version=` filter — blocked by OME-1307.
