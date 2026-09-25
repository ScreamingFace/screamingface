---
status: approved — §5 decisions and the §7 prior-test list signed off by the owner, 2026-09-25
---

# OME-1145 — the open share of the cost/score Pareto frontier

Ledger: `docs/work/2026-09-25-OME-1145-frontier-openness.md`. Investigation and the owner
decisions it builds on: `docs/work/2026-09-10-OME-1145-openness-metric-review.md` (D-A to D-N),
`OME-1179` (D1, D4, Q1), `docs/spec/2026-09-11-OME-1181-model-identities.md` (Q2, Q3).

## §1 The contract (OME-1179, as decided)

> Of the entries on the full-board cost/score Pareto frontier, report how many are **open**. An
> entry is open when every declared model route it names is open (Q1: downloadable, locally
> runnable weights). Any closed or unrecognised model makes the whole entry closed (D1, D4).
> Entries with no model identities are excluded from both numerator and denominator; their count
> is reported separately, as is the count of unrecognised models.

## §2 Which entries: the ranked route's frontier, exactly

`get_frontier` stops reading `list_all_for_benchmark` and uses the inputs `get_leaderboard`
already uses for its Pareto marks:

- `leaderboard_pareto_inputs(registered_revision, registered_case_count)`: best-per-spec, the
  registered revision only (fixes the live 10-vs-7), the OME-1056 case-count rule
- `compute_pareto_frontier_ids`: full board, never a page; an absent cost is excluded, so
  `partial` and `unavailable` rows are off it (D2, D6)
- the D12 `pinned` gate: a board with no registered revision has **no frontier**, so it has no
  share (§4)
- baselines leave the statistic (D-N): they have no cost and cannot be on a cost/score frontier

One definition of "the frontier" for the table marks and the card. They cannot disagree.

## §3 Which models: a bounded second read

`ParetoEntry` stays five fields (OME-1179 constraint 4). Models are fetched in a second query over
the frontier ids only, reading `id, models, openness_override`, chunked so a large `IN (...)`
never exceeds parameter limits. Entry verdict:

1. `openness_override` set → it wins (§5 D-Q4)
2. `models` null → **unidentified**: excluded, counted
3. otherwise `classify_model` per route: all `open` → open; any `closed` or `unknown` → closed.
   Each distinct `unknown` route is counted.

## §4 The response

Every field on one basis (D-L). Proposed:

```
{
  "benchmark_id": "draco-3pass",
  "frontier_available": true,        // false when the board has no registered revision
  "frontier_size": 3,                // entries on the frontier, before exclusions
  "open_count": 1,
  "closed_count": 1,
  "unidentified_count": 1,           // frontier entries with no models (legacy rows)
  "unrecognised_models": ["x/y"],    // distinct routes classify_model called unknown (D4)
  "open_share": 0.5,                 // open / (open + closed); null when that is 0 or no frontier
  "trend": [ { "at": ..., "open_share": ..., "open_count": ..., "closed_count": ... } ]
}
```

`current` is removed: "who holds the frontier" is the old score-only story (D-L). The
portal tooltip that read it changes with it.

**Trend (D-L):** replay the comparable submissions in `submitted_at` order. At each one, recompute
the best-per-spec frontier as it stood then, and emit a point when `open_share` changes. The
classification of historical members reuses §3's bounded read over the union of their ids.

## §5 Decisions (owner, 2026-09-25)

| # | Question | Decided |
| -- | -- | -- |
| **D-Q4** | `openness_override` loses its only consumers. | **Keep it working**: set on a frontier entry, it decides that entry's verdict and the models are not consulted (§3). No migration; the operator correction path stays. Closes OME-1179 Q4. |
| **D-S** | `open_share` when nothing is classifiable (empty frontier, every entry unidentified, or no registered revision). | **`null`**. 0% asserts a closed frontier; nothing measured asserts nothing. The portal shows no percentage. |
| **D-T** | How the unrecognised models are shown (D4). | **The distinct routes, capped at 20**, as `unrecognised_models`. Already public in `url4_expression`; the list names what to add to the registry. |
| **D-U** | The trend. | **Kept**, as the open-share-over-time series (D-L). One point on dev until real costs land (D-K). |

## §6 Test plan (new files)

- frontier basis: an off-frontier open entry does not count; a dominated row does not count
- revision: a superseded-revision row is not counted (the live 10-vs-7)
- case count: a partial-coverage run is not counted
- pinned gate: no registered revision → `frontier_available: false`, `open_share: null`
- D1: open+open → open; open+closed → closed; open+unknown → closed
- D4: unknown routes listed, distinct, capped
- unidentified: a null-`models` frontier entry is excluded and counted
- override wins per entry
- unpriced rows (`partial`, `unavailable`) are off the frontier and off the statistic
- trend: a point per change in share, chronological, over the comparable set only
- bounded read: chunked over ids, reads only `id, models, openness_override`
- private board: still 404 (the OME-894 guard's exits stay guarded)
- portal: `renderFrontier` shows the share, hides on `open_share: null`, and the tooltip names the
  unidentified and unrecognised counts

## §7 Prior tests this changes — approved (rule 5)

The migration replaces what these assert. D-N approved `test_frontier.py:92`; the owner approved
this full list on 2026-09-25. Anything outside it that breaks is a new Confidence-Gate stop.

| file | tests | why |
| -- | -- | -- |
| `tests/unit/scores/test_frontier.py` | all 9 | they pin the all-rows split and the score-holder trend, both replaced (D-L) |
| `tests/unit/test_leaderboard_routes.py` | `test_get_frontier_returns_empty_trend_for_a_benchmark_with_no_scores`, `test_get_frontier_reflects_real_submissions`, the OME-1056 case-count frontier test (`:1322`), and `_PUBLIC_FRONTIER_FIELDS` (`:726`) | they assert `current`, the holder trend and the exact field set |
| `tests/unit/guards/test_visibility_exit_guard.py` | `EXPECTED_UNGUARDED` entries for `get_frontier` if its exits change | the guard's recorded counts |
| `tests/portal/*.test.js` | any that read `current` | the portal stops reading it |

The two in `test_frontier.py` that pin real invariants (case count, no registered count) are
**re-expressed** in the new tests, not dropped. Nothing is weakened: each replaced assertion has a
stricter counterpart on the new basis.

## §8 Out of scope

- real costs on dev: `OME-1143` / `OME-1382`; until then the frontier on dev is one entry (D-K)
- the OME-1146 disclaimer
- publishing `models` on `LeaderboardEntry` (Q2 decided internal)
