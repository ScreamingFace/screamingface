---
ticket: OME-1600
stack: repo
status: done
started: 2026-10-13
finished: 2026-10-13
---

# OME-1600 — backfill a local gateway's response cache into production

## Intent

contracteval, gdpval-text and frontierscience were run against a local AI Gateway. Its cache rows
never reached dev or prod, so prod reruns of those boards pay for live calls and can drift. Copy
the local `request_cache_entries` to prod unchanged, the way `OME-1526` copied dev.

## Source

- Two local `aigateway.sqlite3` copies (with `-wal`/`-shm`) from the owner, 2026-10-13. Working
  copies outside the repo: `$CLAUDE_JOB_DIR/tmp/gwcache/{base,inc-FS}/`. Zips deleted from the repo root.
- `inc-FS` is a strict superset of `base` (120,198 vs 120,148 keys; the 120,148 shared rows are
  byte-identical). `inc-FS` is the source.
- 120,198 rows, all `openrouter`, 2026-09-28 → 2026-10-13 15:39 UTC, no `expires_at`, 13-column
  layout. Cost metadata: 119,939 `reported`, 259 `unavailable`. About 1.16 GB of response JSON.
- Offline delta: 0 of the 120,198 keys appear in any earlier prod upload (the OME-1501 footprint,
  the draco seed, and the OME-1526 full dev copy, from `~/draco-rerun/prod_migration*/`).

## Progress (2026-10-13)

- **Prod read (firecall, read-only):** prod image `main-a502cb99` (2026-10-06); revisions
  `aigw-parameter-contract-2026-08b`, `openrouter-global-cache-2026-08d` (unchanged since August, so
  the local keys are valid), Tavily `aigw-tavily-retrieval-2026-08a` (not needed: no Tavily rows).
  Prod cache total 471,289. 24 of the 120,198 local keys already exist on prod, all with a
  different response and metadata (independent live calls).
- **Owner decision:** keep prod's 24 answers; exclude those keys, so the merge is insert-only.
- **Snapshot built** (`~/ome1600-snapshot/`): 8 parts split by the first hex character of
  `key_hash`, 120,174 rows, 324 MB gzip, manifests with the two chat revisions. Checks passed:
  header and terminator, row counts, prefix groups, 100 random rows per part identical to the
  source, Postgres test load per part, every kept key exactly once, no excluded key, sha256.
- **Next:** owner uploads the 8 parts (merge); expected inserted 120,174, replaced 0, prod total
  591,463. Then verify and probe.

## Planned changes

No repo code changes. Operational steps:

1. Compare with prod (firecall, read-only): shared keys and differing responses; prod's `/cache`
   revision constants.
2. Build the snapshot: COPY text of `request_cache_entries` from the SQLite rows, unchanged; header
   `COPY public.request_cache_entries (<13 columns>) FROM stdin;`, `\.` terminator; gzip; split into
   parts of 100 MB gzip or less; one `.manifest.json` each (`screamingface.cache-snapshot.v1`,
   `row_count`, `sha256` of the `.sql.gz` bytes, `revisions` equal to prod's).
3. Back up prod's rows for any shared keys.
4. Owner uploads each part at `aigw-admin.screamingface.ai/cache`, merge mode, one at a time.
5. Verify with one cached probe per board on prod.

## Test plan

- Round-trip check before upload: parse each part back (row count, distinct keys, header layout,
  sha256 matching its manifest), and compare 100 random rows field by field against the SQLite source.
- After upload: prod's cached-response count grows by the inserted total; probes show 0 misses.

## Acceptance

- Every local row is on prod with an identical `key_hash`, `response_json` and `metadata_json`.
- One cached probe per board on prod: 0 misses, about $0.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** this ledger and the `docs/tasks` mirror only; no code. The snapshot parts and
  scripts lived outside the repo and are deleted.
- **Upload (owner, aigw-admin `/cache`, merge, 2026-10-13 23:31-23:45 local):** 8 parts, 120,174
  inserted, 0 replaced. Part 7 was uploaded twice; the second run replaced its 14,949 rows with
  byte-identical content.
- **Verified on prod (firecall, read-only, in-pod comparison):** total 591,463 (= 471,289 + 120,174);
  120,174 / 120,174 uploaded keys present with response and metadata identical to the source; the
  24 excluded keys still hold prod's own answers.
- **Probe (one case each, SDK 0.1.2, prod engine, never submitted):** gdpval-text 56 hits / 0 misses /
  $0 spend (saved $0.85, all priced); inspect-frontierscience 1 hit / 0 misses / $0, but the case
  scored null (judge not reached; cause not checked).
- **Probe 2 (2026-10-14, same setup, never submitted):** inspect-frontierscience 3 cases, 5 hits /
  0 misses / $0, score 0.6 (case 1 failed again, cases 2-3 scored); contracteval 2 cases with the
  rebuilt `claude-fable-5.1` recipe (same `max_tokens=32768`, `reasoning_effort=high` as the stored
  recipes), 2 hits / 0 misses / $0, score 1.0. All three boards hit with 0 misses.
- **Commits:** the docs PR that lands this ledger and the mirror.
- **Gates:** docs only; CI on the PR.
- **Deviations:** the 24 keys prod already held (different answers) were excluded by owner decision,
  so the merge was insert-only. A first split by OFFSET/LIMIT was replaced with a key-prefix split
  and full checks, at the owner's request. frontierscience's prod revision (`fb33b1e6a2cf0c12`)
  differs from the local run's (`34155c32aec9841b`); its probed call still hit.
