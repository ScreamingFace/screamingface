---
ticket: OME-1710
stack: aigateway
status: in_progress
started: 2026-10-21
finished:
---

# community-cache-keyset-range — start each community-cache batch at its cursor in the index

## Intent

A pull of the hosted community cache (epic OME-1311) was measured on dev at ~33 s per 5,000-row
page, ~55 min for the whole ~580k rows, against the spec's ~2.4 min. The cause is the keyset
condition in `community_pages._after()`: `updated_at > X OR (updated_at = X AND key_hash > Y)`.
Postgres cannot turn that OR into an index range, so every batch walks the
`(updated_at, key_hash)` index from its start and filters out everything before the cursor. Dev
holds two runs of ~188k rows that share one `updated_at` (bulk restores), so even a redundant
`updated_at >= X` bound leaves ~116k rows filtered per batch. Measured on dev with
`EXPLAIN ANALYZE` at a cursor 200k rows in: 1,379 ms for the OR form, 705 ms with the redundant
bound, 0.74 ms with an index range on both columns. A pull is ~100 such queries a page, so the
walk is quadratic today.

## Planned changes

- `apps/aigateway/src/aigateway/core/request_cache/community_pages.py`: `_after()` becomes two
  index ranges — the rest of the cursor's tie run (`updated_at = X AND key_hash > Y`, in
  `key_hash` order) and everything later (`updated_at > X`). `_next_keys` reads the tie run
  first and fills the batch from the later range; `has_rows_after` and `count_rows` combine the
  two. Portable Tortoise filters (SQLite and Postgres); Tortoise has no row-value comparison.
- `apps/aigateway/tests/unit/test_community_cache_pages.py`: new tests only.

## Test plan

- Each part of a cursor's continuation is an index search on `(updated_at, key_hash)` that starts
  at the cursor (SQLite `EXPLAIN QUERY PLAN`: `SEARCH … USING INDEX … (updated_at=? AND
  key_hash>?)` and `(updated_at>?)`), never a scan of the rows before it.
- A tie run that ends inside a batch: the batch takes the run's remaining keys, then fills from
  later rows, in order, skipping and repeating nothing.
- Existing walk/tie/count/has-rows-after tests stay green unchanged.

## Acceptance

- Every keyset read after a cursor is an index range on Postgres and SQLite.
- The walk's order and completeness are unchanged (all existing tests pass).

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus the `docs/tasks` mirror.
- **Commits:** `cd5571ed7` perf(aigateway): start each community-cache batch at its cursor in the
  index; then this backfill.
- **Gates:** focused `test_community_cache_pages.py` + `test_cache_entries_route.py` (70 passed),
  ruff, ruff format and pyright on the changed files. Full local gates skipped by the owner's call;
  GitHub CI is the gate. Postgres plans re-checked on dev (read-only `EXPLAIN ANALYZE`): tie part
  0.48 ms, later part 1.28 ms, against 1,379 ms before.
- **Deviations:** none.

## Review fixes (code review of PR #1525, 2026-10-22)

- **A row read by both parts:** the tie run and the later rows are separate statements, so a
  merge restore that moves a tie-run row later between them put it in both reads; counted twice,
  the page ended a row short. `_next_keys` keeps only each key's later copy and says whether
  fewer keys than asked remain (from the raw read), so the page end is unchanged. Test: a row
  moved out of the tie run between its reads is taken once and the page still fills.
- **The plan test plans the sent query:** it now plans each part exactly as `_next_keys` sends
  it (ordered on both columns, with its limit), through the new `_keys_in` seam.
- Not taken: an empty tie-run read per batch (~0.5 ms, ~25 ms a page) and summed counts during a
  restore (`count_rows` is already approximate); avoiding either needs raw SQL.

## Second code review of PR #1525 (2026-10-22)

- **Fixed:** the module docstring's per-batch reads (a key read after a cursor is two
  statements); the plan test's comment (two ranges, 0.48 ms and 1.28 ms) and an unused unpacking.
- **Not taken:** a single row-value range `(updated_at, key_hash) > (X, Y)`, raised by both
  reviews. Tortoise cannot bind parameters inside it, so the timestamp would be inlined as a
  literal matching SQLite's stored text format and Postgres's `timestamptz` alike; that risk buys
  ~25 ms a page (the empty tie read). The cross-statement cases it would remove (a moved row's
  stale copy kept, `exhausted` read before duplicates drop, a moving row counted twice) can only
  shorten a page or raise the approximate count: the route's `next` comes from the scan cursor and
  `has_rows_after`, never a page's length, and the moved row is sent later at its new time — the
  same short page a row rewritten between the key and row reads already makes.
