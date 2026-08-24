# OME-951 — Admin cache-snapshot upload (spec)

Status: draft 2026-08-22 — awaiting owner approval in plain words.

Related: the global request cache's create-only lane (OME-305 plan §5.3), the DRACO seed
runbook (`draco-cache-seed-v3/RUNBOOK.md`), the OpenRouter global-cache projection (OME-884),
and `local_k8s_deployment.sh` (`snapshot-cache` / `restore-cache` commands).

Linear: epic [OME-951](https://linear.app/openmined/issue/OME-951/admin-cache-snapshot-upload-epic),
sub-issues [OME-952](https://linear.app/openmined/issue/OME-952/aigateway-cache-snapshot-upload-routes-and-loader)
(aigateway), [OME-953](https://linear.app/openmined/issue/OME-953/aigateway-ui-response-cache-console-section)
(aigateway-ui), [OME-954](https://linear.app/openmined/issue/OME-954/snapshot-cache-emits-a-revision-guard-manifest)
(repo script).

## Outcome

An administrator uploads a response-cache snapshot — a gzip'd single-table `pg_dump` of
`public.request_cache_entries`, exactly what `snapshot-cache` produces — through the admin
console. The gateway loads it into the live database with **merge** semantics: keys in the
snapshot replace the stored rows, all other live rows stay. A **replace** mode exists behind an
explicit loss acknowledgement. The console shows load progress and the result. A revision guard
refuses snapshots that were produced under different gateway revision constants, because those
rows would load cleanly and then never be served — a silent 100% miss.

## Background — why SQL-direct, not a row loader

Snapshots are not generated data; they are `pg_dump` output of a table a running gateway wrote.
Every row already carries its final `key_hash`, `prompt_hash` and response payload. The DRACO
seed loader (`seed_cache.py`) exists for a different input: rows generated offline that needed a
manifest to prove servability. For snapshots, the dump's COPY block can be fed back to Postgres
without parsing one value. Measured on this stack: a COPY load of ~190k rows takes seconds; the
row-by-row ORM lane takes minutes. `restore-cache` in `local_k8s_deployment.sh` already proves
the COPY-block reload works end to end.

## Contract

### Routes (all behind `CurrentAdmin`; audited by `AdminAuditRoute`)

| Route | Purpose |
|---|---|
| `GET /v1/admin/cache/info` | Live cache state: serving flag, row count, this gateway's revision constants. |
| `POST /v1/admin/cache/snapshots` | Accept one upload (multipart), start one load job, return `202` + the job record. |
| `GET /v1/admin/cache/snapshots/jobs` | List job records (newest first). |
| `GET /v1/admin/cache/snapshots/jobs/{id}` | One job record, for polling. |

### `AdminCacheInfoOut`

- `serving: bool` — the store's availability gate (`cache_available`).
- `row_count: int` — live `request_cache_entries` count.
- `revisions: {parameter_contract: str, openrouter_adapter: str}` — the two constants every
  cache key embeds (`PARAMETER_CONTRACT_REVISION`, `GLOBAL_CACHE_ADAPTER_REVISION`).

### `AdminCacheJobOut`

- `id: UUID`, `state`, `created_at`, `finished_at`, `actor` (the admin's normalised address).
- `state` is one of `validating`, `loading`, `merging`, `complete`, `failed`, `refused`.
  `refused` is terminal for a rejected input (no COPY block, checksum mismatch, revision
  mismatch without `force`, unsafe replace without acknowledgement). It is a recorded outcome,
  not an HTTP error — the upload itself was accepted.
- Counters: `staged_rows`, `live_before`, `live_after`. In merge mode also a best-effort
  `inserted_rows` / `updated_rows` split (mechanism is plan-level).
- `warnings: [str]` — non-blocking findings, e.g. `revisions_unverified`.
- `error: str | None` — terminal failure reason.

### Upload parameters

- `mode`: `merge` (default) or `replace`.
- `force`: boolean. Overrides a revision **mismatch** only. Nothing else.
- `acknowledge_loss`: boolean. Required for `replace` when the live table holds more rows than
  the snapshot — those rows were written after the snapshot and would be destroyed
  (same rule as `FORCE_RESTORE` in the deployment script).

## Load algorithm

1. **Spool.** The uploaded file streams to a temp file on disk. Size cap on the compressed
   upload, default 256 MiB, configurable. The file is never held in memory whole.
2. **Slice.** Stream-gunzip and line-scan for the COPY block of
   `public.request_cache_entries` — the header line `COPY public.request_cache_entries (…) FROM stdin;`
   through the `\.` terminator. No COPY block → `refused` (`no_copy_block`).
3. **Stage.** Feed the block to Postgres through its own COPY protocol into a staging table
   (`request_cache_entries_staging`), same columns. This is the same trust boundary
   `restore-cache` uses: Postgres re-reads its own dump format; no value is parsed by the
   gateway.
4. **Verify.** With a manifest present: `sha256` of the upload must match, and staged rows must
   equal `row_count`. Mismatch → `refused`.
5. **Revision guard.** Compare the manifest's `revisions` against the live constants
   (from `AdminCacheInfoOut`). Match → proceed, job notes `revisions_verified`. Mismatch →
   `refused` unless `force` (job notes `revision_mismatch_forced`). No manifest → proceed, job
   carries warning `revisions_unverified`.
6. **Merge (default).** One transaction:
   ```sql
   INSERT INTO request_cache_entries
            (key_hash, prompt_hash, provider, model, response_json,
             response_size_bytes, expires_at, hit_count, last_hit_at, created_at)
   SELECT    key_hash, prompt_hash, provider, model, response_json,
             response_size_bytes, expires_at, hit_count, last_hit_at, created_at
     FROM request_cache_entries_staging
   ON CONFLICT (key_hash) DO UPDATE SET
     prompt_hash = EXCLUDED.prompt_hash,
     provider = EXCLUDED.provider,
     model = EXCLUDED.model,
     response_json = EXCLUDED.response_json,
     response_size_bytes = EXCLUDED.response_size_bytes,
     expires_at = EXCLUDED.expires_at,
     updated_at = now()
   ```
   Content columns come from the snapshot. `id`, `created_at`, `hit_count` and `last_hit_at`
   of the live row survive: serving history belongs to this deployment, not to the snapshot
   it was copied from.
7. **Replace.** Safety check first: `live_count > staged_rows` → `refused`
   (`newer_rows_would_be_lost`) unless `acknowledge_loss`. Then, in one transaction:
   `TRUNCATE request_cache_entries` + `INSERT … SELECT` from staging.
8. **Finish.** Drop the staging table (or `TRUNCATE` it), record counters, set `complete`.

## Invariants

1. The gateway **never executes uploaded SQL**. Only the COPY block is extracted, at line
   level; nothing else in the file is read, and nothing from the file is ever sent to Postgres
   as statements. `CREATE TABLE` lines in the dump are ignored, not run.
2. Merge never deletes a live row. It is create-or-replace, the same lane discipline as
   `set_if_absent` — a stored answer may be replaced by its snapshot version, never removed.
3. Replace refuses to discard rows newer than the snapshot unless the admin acknowledges the
   loss in the same request.
4. `response_json` bytes are not parsed, re-serialised, or normalised by this path. The stored
   payload is byte-identical to the dump's.
5. One load job runs per deployment at a time. A second upload while one runs gets `409`.
6. Every route sits behind `CurrentAdmin`; `AdminAuditRoute` logs every attempt including
   refusals, with the actor named.
7. The load never blocks serving. Staging and the final transaction run beside normal traffic;
   readers see the old table until the transaction commits (MVCC), then the new one.
8. Revision constants are compared, never trusted from the file alone: `force` overrides a
   mismatch but the override is recorded on the job and in the audit line.

## Revision-guard sidecar (produced by OME-954)

The snapshot producer (the local `snapshot-cache` script, or any tool that follows this format) writes `<name>.manifest.json` beside `<name>.sql.gz`:

```json
{
  "schema": "screamingface.cache-snapshot.v1",
  "generated_at": "2026-08-22",
  "row_count": 197130,
  "sha256": "<hex digest of the .sql.gz>",
  "revisions": {
    "parameter_contract": "aigw-parameter-contract-2026-08b",
    "openrouter_adapter": "openrouter-global-cache-2026-08d"
  }
}
```

The constants are read from the aigateway image in the cluster (a one-shot Job, the same
mechanism `restore-cache` uses for `generate_schemas`) — not from the host checkout, which may
be older or newer than the deployed code. The upload reads the manifest as a second multipart
part when the operator attaches it.

## Scope split (epic → sub-issues)

| Issue | Stack | Scope |
|---|---|---|
| OME-952 | `apps/aigateway` | Routes, schemas, job runner, COPY/merge loader, revision guard, tests, OpenAPI. |
| OME-953 | `apps/aigateway-ui` | "Response cache" console section: info panel, upload form, job list with polling; TS client + regenerated types. |
| OME-954 | local | `snapshot-cache` emits the sidecar manifest — **kept local, deliberately untracked in this repo** (owner decision 2026-08-24); the manifest FORMAT below is the durable contract, any producer may emit it. |

## Non-goals

- No TTL, eviction, or sweeping behaviour — `expires_at` travels with the rows, unchanged.
- No delete-by-snapshot, no selective key filtering, no cross-table dumps.
- No scheduling or recurring sync between deployments.
- No Engine, SDK, or scoreboard change; the upload path never touches the inference surface.
- No change to how the cache is read or written at request time.
- No multi-instance job coordination — see limitations.

## Known limitations

- **Job records are in-memory** on `app.state`. A restart forgets reports; the loaded data
  stays, its report does not. Accepted: the deployment is single-instance today, and the
  durable truth is the table itself plus the audit log.
- **Postgres only.** The COPY protocol path is Postgres-specific. A non-Postgres DSN refuses
  the upload (`cache_upload_unsupported_database`). The hosted stack and the kind stack both
  run Postgres.
- **Replace discards concurrent writes** made during the load window (between the safety count
  and the commit). Documented in the UI next to `acknowledge_loss`.
- **Unverified snapshots load.** A dump produced before manifests existed carries no manifest;
  it loads with a warning. The guard is best-effort for old files and strict for new ones.
- **Proxy body limits** must admit the cap (Envoy/nginx in front of the console→gateway hop).
  A deployment prerequisite, not code.

## Acceptance

1. Uploading a manifest-matching snapshot in `merge` mode replaces matching keys, keeps
   unmatched live rows, and reports `staged_rows` / `live_before` / `live_after` correctly.
2. On key conflict, local `id`, `created_at`, `hit_count` and `last_hit_at` survive; content
   columns match the snapshot.
3. `response_json` in the table is byte-identical to the value in the dump.
4. `replace` without `acknowledge_loss` refuses when `live_count > staged_rows`, naming the
   number of rows at risk; with the acknowledgement it replaces the contents.
5. A revision mismatch refuses; `force` overrides and the override is visible on the job and in
   the audit line.
6. A manifest checksum mismatch refuses before any staging write.
7. A file with no COPY block for `request_cache_entries` refuses; a file whose other lines
   contain SQL has that SQL never executed.
8. A second concurrent upload receives `409`.
9. Every route refuses an unauthenticated or non-admin caller exactly as the account routes do.
10. Serving traffic during a load is unaffected; a concurrent cache read sees either the old or
    the new contents of a key, never partial rows.
11. The console section uploads, polls, and renders job states and warnings without an untyped
    object reaching the generated client.
12. `snapshot-cache` emits a manifest whose constants match the deployed gateway, verified by
    `GET /v1/admin/cache/info`.
