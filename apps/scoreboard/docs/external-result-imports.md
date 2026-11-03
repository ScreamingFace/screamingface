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
| `score` | The reported value, expressed in this board's units. Import does not convert or verify units. |
| `source` | Stable source identifier; part of the row's identity alongside benchmark and model. |
| `source_url` | HTTP(S) link to the original result. |
| `metric_name` | Metric reported by the source, such as `accuracy`; at most 128 characters. |
| `observed_at` | When you read the source. Include a time zone. This is not when the model ran. |
| `attached_by` | Internal attribution for the person attaching this observation; at most 255 characters. Omit for an automated pull with no human attribution. Stored but never returned by the public leaderboard API. |
| `metadata` | Optional bounded source-specific details, including comparison notes. |

Supply all known fields on every import. The new provenance fields are optional
for compatibility with existing imports. Unknown values remain null; the importer
does not guess them. Text fields are trimmed and reject blanks and control characters.

Repeated imports of the same benchmark/model/source update the same row. Each
input replaces the current observation: omitted metadata is cleared, not copied
from a previous score. This prevents an old read date being presented as the date
of a new observation. Historical versions are not retained by this command yet.

The API returns `imported_at` (first import) and `last_imported_at` (latest import).
Both are server timestamps; neither proves the source was checked. Old rows have
no `last_imported_at` until imported again. Import clients cannot set these fields.
One invalid row rolls back the entire batch, including metadata and import times.

Metric, dates and the existing source-specific `metadata` are public, including on
private boards. `attached_by` stays in its dedicated database column and is absent
from public responses. Do not duplicate attribution or other private information
inside `metadata`. Attribution is operator supplied, not proof of identity. This
change adds no public write API and does not determine who may add/edit results
through a future manual-entry UI.
