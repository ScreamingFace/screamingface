# OME-1382 — rank and show the reproduction cost (board half)

Parent `OME-1251` (D5: the board sums spend and saving at the point of use; nothing stores the sum).

## Rule

```
reproduction_cost(spend, status, saving) =
    spend + saving   when status == "complete" and spend is not None and saving is not None
    spend            otherwise
```

- `complete` asserts the spend is exact. A saving beside it is the provider-reported money the
  cache avoided. From the `client-sf` half on, the SDK sends `complete` for a cached run only when
  every hit was provider-priced (owner, 2026-10-02, D1), so the sum is the full reproduction cost.
- `partial` and `unavailable` carry no amount (`schemas.py`, `validate_cost_matches_its_status`),
  so they serve `None` and stay off the frontier, as today. A saving beside `partial` is never
  promoted to a cost.
- A legacy row (`status` null) and a row with no saving serve their stored spend unchanged.

## Where it applies

Every read path that RANKS or DISPLAYS a cost, so the card, the marks, the chart and the history
can never show two numbers for one row (`OME-1145` D-L):

| path | builds | today reads |
| -- | -- | -- |
| `_build_leaderboard_query` → `LeaderboardStoreEntry` | the table and the chart | `run_cost_usd` |
| `_build_pareto_inputs_query` → `ParetoEntry` | the frontier marks and the card | `run_cost_usd` |
| `frontier_history_inputs` → `HistoryRow` | the open-share trend | `run_cost_usd` |
| `list_owned_entries` → `LeaderboardEntry` | a private board's own rows | `run_cost_usd` |
| `_history_submission` (route) → `HistorySubmission` | the spec history page | `run_cost_usd` |

**Not** `_score_to_schema`. It is the one row → `ScoreSchema` mapping, which feeds the score
receipt and `export_private_submissions.format_jsonl`, whose sha256 authorises a purge
(`delete_scores --expect-sha256`, the `OME-1181` Q2 trap). It keeps the stored spend, status and
saving as three separate fields. The 2026-09-29 note on the ticket said the export emits none of
the cost fields; it emits all three (`export_private_submissions.py:55`, `model_dump`), which is
why the sum stays out of this mapping.

## Approach A (decided 2026-09-29, confirmed 2026-10-02)

The served field keeps its name, `run_cost_usd`, its type and its six-decimal wire form. The
portal reads it unchanged (`costNumber`), so the chart plots the number the frontier ranks on with
no JS change.

## Out of scope

- The SDK rule (`client-sf` leaf under `OME-1251`).
- `archive_matched` money (`OME-1251` D3: never published).
- Historical $0 rows (`OME-1384`).
