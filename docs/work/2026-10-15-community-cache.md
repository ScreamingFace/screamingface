---
ticket: OME-1631
stack: aigateway
status: done   # planned | in_progress | done | blocked
started: 2026-10-15
finished: 2026-10-16
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

- **Actual files:** as planned — `core/request_cache/community_pages.py`,
  `core/request_cache/sqlite_loader.py`, `routes/cache_entries.py`, migration
  `0015_cache_entry_write_order.py` with the `Meta.indexes` entry on `RequestCacheEntry`,
  `main.py` (router), `DEPLOYMENT.md` section. Tests: `test_community_cache_pages.py`,
  `test_cache_entries_route.py`, `test_community_cache_loader.py`,
  `test_migration_0015_cache_entry_write_order.py`, and Postgres evidence in
  `tests/integration/test_community_cache_pages_postgres.py`.
- **Commits:** `docs: spec and plan for pulling the community cache into local engines`;
  `feat(aigateway): page the community cache to signed-in callers and load pages into SQLite`.
- **Gates:** format, lint, pyright green; full suite 5,840 passed / 118 skipped with 2 failures
  that are now fixed (the 0011 index tests below); total coverage 93%, new route module 100%.
  New and touched migration tests (0010/0011/0015) 20 passed. Postgres (`AIGW_TEST_PG=1`,
  OrbStack): the 5 new/pinned tests pass; of the full Postgres suite 73 passed, 5 failed only
  because `pg_dump` is not installed locally (snapshot-upload tests; CI has it) and 1 OAuth
  test timed out under parallel load and passed on rerun.
- **Deviations:**
  - Prior tests changed (owner-approved, `.claude/test-change-approvals/OME-1631.json`): the
    0010 SQLite + Postgres and two 0011 index-set tests migrated to *head* and compared the exact
    index set 0010/0011 leave; 0015's new index broke that. Each now migrates to its own
    migration; no assertion changed.
  - `check_revisions` compares the revisions both sides report, and requires
    `parameter_contract` on both. An adapter revision only one side has is not a mismatch: a
    local process may load fewer provider plugins, and rows for a provider it lacks are never
    looked up there.
  - The migration was generated with `tortoise makemigrations` and the autodetector's known
    `OAuthConnection.account` `AlterField` dropped, as in 0012/0014.
  - `main.py` was already over 450 lines (506); this unit adds 2.
  - Installed the mandatory `tortoise-dev` companion skill (user scope) at the user's request.

## Review round 1 (PR #1433 `/code-review`, verified 2026-10-16)

Owner chose: fix the five confirmed findings plus the cheap wording fixes; #2 is a
documentation correction only; #4 (filtered-walk index) and #9 (timestamp text form) are
dropped as not real.

- **Planned, one commit each:**
  1. #6 — `community_pages._eligible` excludes Tavily by `TAVILY_PROVIDER`, not a literal.
  2. #7 — `sqlite_loader` uses `revisions.PARAMETER_CONTRACT_KEY`, not a copy.
  3. #2 + #1 — spec, `community_pages` docstring, DEPLOYMENT.md: a *replace* restore keeps the
     archive's `updated_at` (only *merge* stamps `now()`), so a pull under way misses those
     rows until the next pull; the "same walk reaches it" claim is qualified by decision 13.
  4. #3 — route docstring, spec decision 4, DEPLOYMENT.md: 401 in every authenticating mode;
     `AIGW_AUTH_MODE=disabled` serves the anonymous account, loopback-only.
  5. #8 — `load_page` checks the table's columns and refuses an unmigrated local database
     with a `PageRejected` instead of a raw `sqlite3.OperationalError`. New test.
  6. #5 — the route's per-batch JSON encoding and gzip run in a worker thread, not on the
     event loop. New test.
  7. #10 — `check_revisions` and a revision only the local side reports (approach confirmed
     with the owner before coding).
- **Test plan:** new tests only (append-only); 1, 2 and the docs are covered by the existing
  suite. Gates: `run_gates.py aigateway`.
- **Outcome (2026-10-16):** all seven landed as planned, one commit each:
  `refactor(aigateway): exclude Tavily rows from community pages by TAVILY_PROVIDER`;
  `refactor(aigateway): check the parameter contract by revisions.PARAMETER_CONTRACT_KEY`;
  `docs(aigateway): a replace restore and a late commit can fall behind a pull's cursor`;
  `docs(aigateway): the cache-entries route serves the anonymous account when auth is disabled`;
  `fix(aigateway): refuse a local database missing a cache column as outdated_gateway_database`;
  `perf(aigateway): encode and gzip community-cache batches in a worker thread`;
  `fix(aigateway): refuse a page whose gateway does not report a revision the local side uses`.
  Gates (`run_gates.py aigateway`): ruff check, ruff format, pyright, no-enterprise, full pytest
  with coverage ≥80% — all green. Three new tests; no prior test changed.
- **Deviations:**
  - #8's message tells the user to apply the gateway's migrations, not to start the gateway:
    migrations never run at app startup (DEPLOYMENT.md "Migrations").
  - #10 reverses the earlier deviation for one direction only: a revision only the local side
    reports is now `revision_mismatch` (owner's choice, fail closed); a revision only the hosted
    side reports still passes. A local-only plugin that registers a revision would need the rule
    refined first (AIDEV-NOTE in `check_revisions`).
  - New loader reason `outdated_gateway_database` beside `not_a_gateway_database` and
    `revision_mismatch`; the client (PR 2) should handle it.

## Follow-up from the SDK PR review (#1446, 2026-10-17)

- **`check_database(database)`** — public, so the client can refuse a database it could not load
  into before signing in or downloading anything (#1446 review finding 7). It opens the file
  `mode=rw` (a missing file is refused as `not_a_gateway_database`, never created) and runs the
  same schema check as `load_page`, which keeps its own.
- **Docstring corrected** (#1446 review finding 9): the loader is one transaction per
  `load_page` call; the SDK calls it per 500-row batch. Measured on a WAL database the ORM
  created (600k rows, ~3 KB each): per-batch connect+commit 75 s, one connection per-batch commit
  65 s, one transaction per page 38 s. Per-page transactions were not adopted: with rows loading
  as a page streams, the write lock would be held for the page's download, and the running
  gateway's writers wait 5 s. A time-bounded commit (page end or ~1 s) is the possible follow-up.
- **Tests (append-only):** four `check_database` tests (ORM-created passes; not-a-gateway,
  pre-`metadata_json`, missing-and-not-created refused). Gates (`run_gates.py aigateway`) green.

## Review round 2 (PR #1433 review by HupBaHa at `9c2369e`, fixed 2026-10-20)

All seven findings were valid; the owner chose skip-and-count for invalid rows. One commit.

- **Memory (blocking 1):** batches are bounded by bytes as well as rows: a size-only keyset query
  reads the next ≤100 keys with their `response_size_bytes`, keeps up to `BATCH_BYTES` (8 MB; at
  least one row), then reads those rows. A request holds ~24 MB at most (rows, encoded lines,
  joined chunk). The cursor and the page count come from the keys, so a row deleted between the
  two queries neither ends the page nor moves it back, and a byte cut on the table's last fetch
  loses no row.
- **Unservable rows (blocking 2):** `_parameters` admits only rows a local lookup can serve
  (hex hashes, column lengths, `store.decode_cached_response` — the lookup's decoder, lifted out
  of `store.get` so there is one — size bounds, aware in-range timestamps, not expired). A row
  that fails is skipped and counted (`PageLoad.skipped`), never written, so it cannot hold its key
  against a later valid row. Unreadable or oversized metadata is stored NULL, as a lookup reads it.
- **`Accept-Encoding` (blocking 3):** RFC 9110 negotiation — case-insensitive codings, `q=0`
  refuses, `*`, and the strict qvalue grammar (`q=2`, `1e-1`, `+0.5` refuse); table-tested.
- **Non-blocking:** `check_database` also requires the unique index on `key_hash`; a timestamp
  outside the UTC range (`OverflowError`) is an invalid row; spec decisions 6 and 11, the plan and
  `DEPLOYMENT.md` describe per-batch transactions, the byte bound and the skip rule; `next` is
  null exactly when no eligible row follows the page (`has_rows_after` look-ahead), so a last page
  of exactly `limit` rows says so.
- **Tests:** the loader's two malformed-row tests now pin skip-and-count (the contract changed
  by the owner's decision); new tests for every validation, the same-key repair, NULL metadata,
  the lookalike table, the byte bound, the end-of-table cut, the look-ahead and the negotiation
  table. All are in files this PR added, so no approval manifest changes.
