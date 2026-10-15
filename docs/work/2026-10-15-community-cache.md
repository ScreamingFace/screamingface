---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: aigateway
status: planned   # planned | in_progress | done | blocked
started: 2026-10-15
finished:
---

# community-cache — page the community cache to signed-in callers, load it into local SQLite (epic OME-1311, PR 1/3)

## Intent

A signed-in local engine can pull the hosted community request cache into its local SQLite
gateway, so a call the community has already made is a free local cache hit (epic `OME-1311`).
This unit is the AIGateway half: an authenticated, non-admin route that returns the shareable
cache rows one page at a time in write order (`updated_at`, `key_hash`), optionally filtered
by model, and the
SQLite loader the local runtime calls per page. The Engine proxy (PR 2) and
`sf.cache.pull_from_remote()` (PR 3) follow. Spec:
`docs/spec/2026-10-15-community-cache.md`; plan:
`docs/plan/2026-10-15-community-cache.md`.

## Planned changes

- `apps/aigateway/src/aigateway/core/request_cache/community_pages.py` (new) — the page query,
  the byte cut, the cursor, the filtered count.
- `apps/aigateway/src/aigateway/routes/cache_entries.py` (new) — `GET /v1/cache/entries`.
- `apps/aigateway/src/aigateway/core/request_cache/sqlite_loader.py` (new) — revision check
  and per-page load into SQLite.
- `apps/aigateway/src/aigateway/main.py` — include the router.
- `apps/aigateway/DEPLOYMENT.md` — a section on the route.
- `apps/aigateway/src/aigateway/core/request_cache/models/request_cache_entry.py` + migration
  `apps/aigateway/src/aigateway/migrations/0015_cache_entry_write_order.py` — index
  `(updated_at, key_hash)` (S1: the migration ships with the model change).
- No settings.

## Test plan

- Migration: applies on SQLite and Postgres and creates the `(updated_at, key_hash)` index.
- Cursor: round-trips `(updated_at, key_hash)` with microseconds intact; a malformed token is
  refused.
- Page query: rows in `(updated_at, key_hash)` order after the cursor, ties on `updated_at`
  split by `key_hash` with none skipped or repeated; `limit` honoured; rows produced in batches
  of 100; `next` is the last row's cursor, and null on the last page; a row written mid-walk
  appears later in the same walk; Tavily and expired rows never appear; with models only
  those models, without all; `id`, `hit_count`, `last_hit_at` absent; `response_json` verbatim.
- Count: rows after the cursor (all without one); matches the filter; excludes Tavily and
  expired rows.
- Route: 401 anonymous; a non-admin account allowed; the body is NDJSON — a header line
  (`schema`, `revisions`, and `remaining` only with `count=true`, with or without `after`),
  one line per row, a trailer line with `next`; `limit` defaults to 5,000; repeated `model`
  values all reach the query; 422 for a bad `after`, `limit` 0 or 5,001, an empty or 256-char
  `model`; `Cache-Control: private, no-store`; gzip when requested.
- Hit invariant: a cache hit leaves `updated_at` unchanged.
- Walk: paging from no cursor to `next: null` returns every eligible row exactly once.
- Loader: a page round-trips into a Tortoise-created SQLite table and reads back through the
  ORM (timestamps, NULLs, JSON text intact) with a new id and zero hits; a local row is kept on
  conflict; reloading a page adds nothing; a malformed row writes nothing for its page; a
  revision mismatch is refused.

## Acceptance

- A signed-in caller can page every shareable cache row, or only those for the models named,
  from `GET /v1/cache/entries`, with a count of the remaining rows on request and a cursor to
  resume from;
  nothing outside `request_cache_entries` (minus Tavily and expired rows, and without ids or
  hit statistics) is in it.
- Pages load into a local SQLite gateway and their rows are served as ordinary hits.
- `run_gates.py aigateway` green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
- **Commits:**
- **Gates:**
- **Deviations:**
