# OME-1382 — rank and show the reproduction cost (board half)

Parent `OME-1251` (D5: the board sums spend and saving at the point of use; nothing stores the sum).

## Rule (amended by `OME-1251` D7, owner 2026-10-02)

```
reproduction_cost(spend, status, reported, archive) =
    spend + reported + archive   when status == "complete" and spend is not None
                                 (an absent saving adds nothing)
    spend                        otherwise
```

- `complete` asserts the spend is exact. D7 (reverses D3) publishes BOTH cache savings: the
  provider-reported one and the archive-matched one (measured from another call of the same model
  and kind). The SDK sends a cached run as `complete` only when every hit carries a price,
  reported or archive; any hit with no price makes it `partial` (the `client-sf` half).
- `partial` and `unavailable` carry no amount (`schemas.py`, `validate_cost_matches_its_status`),
  so they serve `None` and stay off the frontier, as today. A saving beside `partial` is never
  promoted to a cost.
- A legacy row (`status` null) and a row with no saving serve their stored spend unchanged.

## The archive saving (D7)

- New `cache_saved_cost_archive_usd`: optional on `ScoreSubmission` (same money domain as the
  reported saving), a nullable `DECIMAL(12, 6)` column (migration `0017`, not backfilled), and a
  `ScoreSchema` field excluded when absent so no pre-existing export changes its bytes.
- `unavailable` beside it is refused; an absent status beside only it resolves to `partial`, the
  same rules the reported saving follows.
- It joins the one-execution replay snapshot: a replay fills spend, status and both savings
  together, and only when all four are empty (`OME-1325`).
- **Owner, 2026-10-02:** not labelled "estimated" now, but kept as its own column and export field
  so it can be labelled later without a data change. Only `reproduction_cost` ever merges it.

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
- Labelling the archive-matched part. It IS published as part of the reproduction cost (D7), and
  stored and exported separately for provenance, so a later "of which estimated" label needs no
  data change.
- Historical $0 rows (`OME-1384`).

## Existing rows (accepted, owner 2026-10-02)

The rule applies to every `complete` row, including rows from clients that predate the D7
per-hit pricing proof (a `#1075`-era client sent `complete` with a reported saving whenever the
spend was priced). Those rows are summed too. This reinterpretation is intended; it was raised in
review of #1227 and confirmed.
