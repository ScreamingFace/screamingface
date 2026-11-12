# Importing external result metadata

Use the existing operator command, `python -m scoreboard.import_baselines`, with
`--baselines-json` or `SCOREBOARD_SEED_BASELINES_JSON`. The target benchmark must
already exist. This command writes to the configured scoreboard database; check
the target environment before running it.

Example input (illustrative values, not a published result):

```json
[
  {
    "benchmark_id": "example-benchmark",
    "model_name": "Example model",
    "score": 0.75,
    "source": "example-paper-table",
    "source_url": "https://example.org/paper/table",
    "metric_name": "accuracy",
    "observed_at": "2026-11-03T10:00:00Z",
    "attached_by": "operator-handle",
    "metadata": {"comparison_note": "Describe any known evaluation differences."}
  }
]
```

| Field | Meaning |
| --- | --- |
| `score` | The value in board units. A comparison review must record the original value and an exact supported conversion; the importer verifies the supplied result. |
| `source` | Stable source identifier; part of the row's identity alongside benchmark and model. |
| `source_url` | HTTP(S) link to the original result. |
| `metric_name` | Metric reported by the source, such as `accuracy`; at most 128 characters. |
| `observed_at` | When you read the source. Include a time zone. This is not when the model ran. |
| `attached_by` | Internal attribution for the person attaching this observation; at most 255 characters. Omit for an automated pull with no human attribution. Stored but never returned by the public leaderboard API. |
| `metadata` | Optional bounded source-specific details, including comparison notes. |

Supply all known fields on every import. The new provenance fields are optional
for compatibility with existing imports. Unknown values remain null; the importer
does not guess them. Text fields are trimmed and reject blanks, Unicode control/format characters (including
invisible text-direction controls), and lone surrogates.

Repeated imports of the same benchmark/model/source update the same row. Each
input replaces the current observation: omitted metadata is cleared, not copied
from a previous score. This prevents an old read date being presented as the date
of a new observation. Changed observations are retained as immutable versions; importing identical data again only refreshes the server import time.

The API returns `imported_at` (first import) and `last_imported_at` (latest import).
Both are server timestamps; neither proves the source was checked. Old rows have
no `last_imported_at` until imported again. Import clients cannot set these fields. The latest import time never precedes the first
import or moves backwards during overlapping imports or a clock adjustment.
One invalid row rolls back the entire batch, including metadata and import times.

Metric, dates and the existing source-specific `metadata` are public, including on
private boards. `attached_by` stays in its dedicated database column and is absent
from public responses. Do not duplicate attribution or other private information
inside `metadata`. Attribution is operator supplied, not proof of identity. This
change adds no public write API and does not determine who may add/edit results
through a future manual-entry UI.

Storage does not confer a rank. See [comparison policy and SAT-English audit](external-result-comparison.md)
for `metadata.comparison`, evidence requirements and supported conversions. The
public `ranking_eligible` boolean is computed on every read, defaults to false, and
cannot be supplied by an importer. The example above lacks a review and remains
unranked. Invalid supplied reviews fail before writing; missing reviews can be
stored for later investigation.


## Edit history

Every changed observation creates a version: score, metric, source link, source-read date,
metadata and internal attribution are compared. Initial imports are version 1 and are
not shown as updates. Importing the same observation again preserves its version and
update date. Only the latest eligible observation affects rankings.

The leaderboard exposes `observation_revision` and `observation_updated_at`. Its
Updated link opens a separate history page with current and previous scores, source
links, dates and comparison details. The public history endpoint is
`GET /v1/leaderboard/{benchmark_id}/external-results/{baseline_id}/history`.
It defaults to 20 versions, accepts a limit of 1–100, and returns `next_before` for
older pages. Supply that value as `before` to continue. Both history and current
external observations are public even on private boards; attaching-person attribution
stays internal in both. No public edit or restore endpoint is added.

Old rows are not backfilled with invented versions. Their current value is captured
before the first subsequent import; its version date is unknown because previous
edits were not tracked. Earlier overwritten values cannot be recovered. Snapshots
and current-row changes share one transaction, so a failure rolls back both. History
cannot be replaced or removed by the importer. Benchmark/model/source remain the
row identity: changing one of those creates a different row.

Deploy migration 0023 before this application version. Pause operator import jobs
while rolling out, then resume them using the new image; an older importer cannot
retain history. No extra migration job is needed: the existing deployment migration
hook applies this migration. Merely importing again is not proof the source was
checked; `observed_at` records when it was actually read.


### Withdrawing a published result

A correction import preserves the old value publicly. It is not a takedown. When an
operator must withdraw a result and its old source links/metadata, this release uses
a manual database operation; there is no public delete or restore endpoint. Record
the authorization, reason, benchmark and baseline UUID in the internal operator log,
and keep a restricted backup before removal. Pause imports for that result so a
queued import cannot recreate it.

For PostgreSQL, set `benchmark_id` and `baseline_id` as psql variables to the reviewed
values, then execute the following in the intended database. The initial row must
match exactly one result; otherwise roll back. Revisions are removed before their
parent because the foreign key deliberately prevents an accidental cascading delete.

```sql
BEGIN;
SELECT id, benchmark_id, model_name, source, observation_revision
FROM baselines
WHERE id = :'baseline_id'::uuid AND benchmark_id = :'benchmark_id'
FOR UPDATE;

DELETE FROM baseline_revisions
WHERE baseline_id IN (
    SELECT id FROM baselines
    WHERE id = :'baseline_id'::uuid AND benchmark_id = :'benchmark_id'
)
RETURNING revision;

DELETE FROM baselines
WHERE id = :'baseline_id'::uuid AND benchmark_id = :'benchmark_id'
RETURNING id;
COMMIT;
```

Verify that the history endpoint returns 404 and the row is absent from the board.
This withdraws the whole external result and its history, leaving other results and
community submissions untouched. Re-import only with reviewed, publishable metadata;
that creates a new result identity. A withdrawn URL may already exist in third-party
copies, which this operation cannot retract.
