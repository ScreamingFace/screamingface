# Cache-entry metadata — ERD

**Ticket:** OME-1155 · Companion to
[`2026-09-13-cache-entry-metadata-prd.md`](2026-09-13-cache-entry-metadata-prd.md)

> **Provenance.** Reconstructed on 2026-09-14 from the implementation that cites it, during the
> review of PR #930. See the PRD's provenance note — the same caveats apply: recovered from what
> the code demonstrably does, not from the lost original, and therefore not evidence that the
> implementation is correct.

---

## §3 The stored block

### §3.1 Where it lives

One nullable `TEXT` column, `metadata_json`, on `request_cache_entries`, carrying a
`aigw.cache-entry-metadata.v1` document. Nullable is load-bearing: see **E7**.

### §3.2 Shape

```jsonc
{
  "schema": "aigw.cache-entry-metadata.v1",
  "metadata_status": "complete" | "partial" | "archive_paired",
  "observed_at": "2026-09-13T12:00:00Z",   // or null
  "response_model": "anthropic/claude-haiku-4-5",  // or null
  "usage":       { /* canonical TokenUsage.as_json() */ },
  "direct_cost": { /* canonical DirectCost.as_json() */ },
  "latency":     { "provider_latency_ms": 812 }    // or null inside
}
```

`usage` and `direct_cost` are the canonical taxonomy dictionaries, stored **verbatim**. The value
object owns the persisted shape, the size cap and the codec — never the meaning of the values
inside those two sub-objects.

`metadata_status` vocabulary:

| Status | Written by | Certifies a price? |
|---|---|---|
| `complete` | the gateway, on a complete capture | yes |
| `partial` | the gateway, on an incomplete capture | **no** — an incomplete observation is not evidence of a price |
| `archive_paired` | the **out-of-band archive loader only** — no producer in this repo | yes |

`archive_matched` (a `direct_cost.status`) and `archive_paired` (a `metadata_status`) are two
different vocabularies for two different concepts, spelled similarly. Both are `Literal`-constrained.

### §3.5 Reference mapping

Mapping a stored block to the hit-path `CacheReference`:

- A `partial` capture is **excluded from certifying a price** — its `direct_cost` is downgraded to
  `unavailable` even when the underlying record said `reported` or `archive_matched`.
- The usage **source** is rewritten to `cached_converted_response` on replay: the numbers are
  real, but they are being replayed, and the source must say so.
- `provider_latency_ms` is stored and reported verbatim; omitted when null.
- Failure here is narrow and internal (`CacheEntryMetadataReferenceError`), caught by the caller,
  which then falls back to the provider's own mapper. It is never surfaced to a caller (**R2**).

## §4 The observation seam

Saved cost travels beside the cache outcome that explains it, on the same round trip:
`ModelResponse` carries `cache_saved_cost_usd` with its `cache_saved_cost_provenance`; the
aggregated `SpanData` carries `cache_saved_cost_usd` and `cache_saved_cost_archive_usd` as two
separate fields.

Two fields rather than one amount plus a provenance label, deliberately (**PRD S5**): a single
amount with a label invites a consumer to add the labels away, while two differently-named money
fields state the separation in the shape itself.

Neither rides in `CostBreakdown`, which is closed (`extra="forbid"`). Avoided money is not
consumption; smuggling it into the cost block would let one call be counted twice — once as spend
and once as saving.

**Pairing is enforced, not documented.** `AvoidedCost` and `ModelResponse` both refuse a shape
where the amount is set and the provenance is not, or the reverse. An unpaired amount cannot be
routed to either total, so it would silently land in the unpriced bucket — money that was
measured, reported and then quietly lost.

## §5 Persistence and movement

### §5.1 Migration 0011

Appends `metadata_json` **nullable, with no default, last**. On Postgres this is catalog-only —
no table rewrite, no backfill — but it still needs `ACCESS EXCLUSIVE` for the instant it applies,
and a queued request for that lock heads the lock queue, so every later cache read queues behind
it too.

> **Corrected in review round 2 (OME-1203).** This section previously read "no rewrite, no long
> lock, no backfill." The lock claim was wrong: see below.

The forward DDL runs under `SET LOCAL lock_timeout = '3000ms'` (`_bound_lock_wait`). It is tried
**exactly once** — if the timeout fires the migration fails and the operator reruns it; there is
no retry loop. `Migration.atomic` stays `True`, so the whole migration (including the SQLite
index-restore on downgrade) commits or aborts as one unit. A retry loop was tried and removed:
five attempts against the snapshot exporter's lock (held for up to 600 s) would nearly always
exhaust anyway, and making the migration non-atomic to permit retrying would have cost the
downgrade path its all-or-nothing property (ruling R10). The downgrade path (`DROP COLUMN`) sets
no `lock_timeout` and can queue for as long as whatever holds the conflicting lock does — out of
scope for this migration to fix.

On SQLite the migration is written so the reverse op restores the indexes the table rebuild
drops. Neither dialect rebuilds the table on upgrade.

*Pinned by `test_the_migration_gives_up_the_lock_queue_instead_of_blocking_readers` in
`apps/aigateway/tests/integration/test_cache_snapshot_entry_metadata_postgres.py`.*

### §5.2 Snapshot merge

`metadata_json` is **content**, so on conflict `EXCLUDED` wins — the incoming row's block replaces
the live one, exactly as `response_json` does. Identity and serving history (`id`, `created_at`,
`hit_count`, `last_hit_at`) are preserved.

The consequence is intended and irreversible: because a legacy 12-column archive carries no block,
`EXCLUDED` is `NULL`, so **merging a legacy archive degrades priced rows back to unknown**. A
restore may only degrade a block to unknown; it may never leave a stale block beside a replaced
response.

Since PR #930's review, the load **counts and reports** the rows it degrades, on the
`LoadOutcome`, on the job record, in the admin API, and as a warning. The erasure remains
permitted; it is no longer silent.

> **Added in review round 2 (OME-1203).** The merge transaction opens with `LOCK TABLE
> request_cache_entries IN SHARE ROW EXCLUSIVE MODE` before it counts and before it merges.
> Without it, the count and the merge are two statements under READ COMMITTED, each with its own
> snapshot; a cache fill landing between them would be degraded by the merge but missed by the
> count, so the report would understate the loss. `SHARE ROW EXCLUSIVE` blocks concurrent cache
> **writes** for the length of the transaction and leaves **reads** unaffected, which is what
> makes `metadata_degraded` exact rather than approximate. On a deployment with a global
> `lock_timeout`, the merge fails rather than waits.
>
> *Pinned by `test_a_legacy_merge_reports_how_many_blocks_it_degraded` and
> `test_a_racing_write_to_an_unrelated_row_blocks_the_merge` in
> `apps/aigateway/tests/integration/test_cache_snapshot_entry_metadata_postgres.py`.*

### §5.3 Stale-metadata trigger

> **Added in review round 2 (OME-1203).** Not recovered from the lost original — new specified
> behaviour, closing PR #930 review finding 1.

A Postgres-only `BEFORE UPDATE` trigger, `request_cache_entries_metadata_follows_response`
(function `request_cache_entries_clear_stale_metadata`), guards every writer, not only the
snapshot loader:

```sql
BEFORE UPDATE ON request_cache_entries
FOR EACH ROW
WHEN (NEW.response_json IS DISTINCT FROM OLD.response_json
      AND NEW.metadata_json IS NOT DISTINCT FROM OLD.metadata_json)
EXECUTE FUNCTION request_cache_entries_clear_stale_metadata()  -- sets NEW.metadata_json := NULL
```

Migration 0011 leaves pre-0011 binaries fully operational against the widened table. An old
writer that updates `response_json` without knowing `metadata_json` exists — during pod overlap
in a rolling upgrade, or after a rollback — would otherwise pair a NEW response with the
PREVIOUS response's cost, tokens and latency: a block that is well-formed and simply describes a
different answer, which nothing downstream can detect. The trigger degrades the row to `NULL` —
unknown — instead, which is the direction this feature already commits to (**E7**): unknown, not
wrong.

The `WHEN` clause is evaluated without entering the function body, so an ordinary
`hit_count`/`last_hit_at` bump — the hot path — never pays for this. Installed with `CREATE OR
REPLACE TRIGGER` (Postgres 14+) so re-running the forward migration against an already-migrated
table is idempotent; both the trigger and its function are dropped on reverse.

**Known false positive, deliberately accepted:** a writer that replaces the body and computes a
byte-identical block loses it anyway, because the trigger cannot distinguish "same answer" from
"no answer computed." The block carries provider latency, so two calls colliding on every field
is vanishingly rare, and the cost is one row degraded to the safe direction (unknown).

*Pinned by `test_replacing_a_response_alone_clears_its_metadata_block`,
`test_replacing_a_response_with_its_own_block_keeps_the_block`,
`test_a_hit_count_bump_never_touches_the_block`,
`test_the_merge_still_carries_a_real_block_through` and
`test_the_trigger_and_function_drop_together_on_reverse_and_recreate_idempotently` in
`apps/aigateway/tests/integration/test_cache_snapshot_entry_metadata_postgres.py`.*

### §5.4 Write path

`RequestCacheWrite.metadata` carries the block for the response being stored. Every step is
best-effort: a build, serialize or parse failure writes `NULL` and still serves the answer. A
block over the cap is dropped whole (**M9**), never trimmed.

### §5.5 Read path

`CachedEntry.metadata` is the parsed block, or `None` when absent or unreadable. On a hit it is
preferred over the provider plugin's mapper (**PRD S3/S4**).

## Invariants

| Id | Invariant |
|---|---|
| **E6** | The read path's half of the write/read contract, paired with E7. *(Not separately recoverable — see the PRD's unrecovered list.)* |
| **E7** | `NULL` means **unknown** and is never read as `0`. Legacy rows, seed rows with no block, and unreadable blocks are always `NULL` — never a fabricated or zero-shaped block. A snapshot merge can only degrade a block to unknown. |
| **E9** | The Tavily retrieval lane stays outside this feature and always writes `NULL` — it carries no cost signal, so an invented block would be worse than none. |
| **M1** | The builder is non-raising; the reference mapper raises narrowly and internally. |
| **M2** | `archive_matched` carries the same mandatory fields as `reported`. |
| **M5/M7** | Money and counts are re-validated through the canonical constructors on rebuild, not trusted verbatim from storage. |
| **M8** | Archive-matched money is never summed with provider-authored money. |
| **R2** | `CacheEntryMetadataReferenceError` is narrow and internal. No value is ever inferred from the cached response body. |
| **E10** | *(Added in review round 2, OME-1203.)* Any `UPDATE` that changes `response_json` without setting `metadata_json` in the same statement clears the block to `NULL` (§5.3). This is the automatic counterpart to E7's merge case — the same "unknown, never wrong" direction, enforced against every writer, not only the loader. |
| **E11** | *(Added in review round 2, OME-1203.)* A snapshot merge holds `SHARE ROW EXCLUSIVE` on `request_cache_entries` for its whole transaction (§5.2), so its `metadata_degraded` count is exact under a concurrent cache write, not merely likely. |

## Snapshot scenarios

| Id | Scenario | Behaviour |
|---|---|---|
| **S12** | A legacy 12-column archive is loaded. | COPY names the dump's own header columns; `metadata_json` loads `NULL` rather than being padded with an invented block. |
| **S13** | A row produced by a gateway older than the column. | `NULL`; the provider's existing mapper serves the hit. |
| **S20** | A merge drops a block. | Permitted (§5.2), counted and warned about. |
| **S21** | *(Round 2.)* A pre-0011 binary updates `response_json` on a row that already has a block (rolling upgrade or rollback). | The trigger (§5.3, **E10**) clears `metadata_json` to `NULL` before the row commits — never a stale block beside the new response. |

A staging twin left behind by a pre-0011 gateway is 12 columns wide, and `CREATE TABLE IF NOT
EXISTS` will not widen it. The loader issues an idempotent `ADD COLUMN IF NOT EXISTS` before the
COPY; without it the next 13-column COPY fails on the missing column.
