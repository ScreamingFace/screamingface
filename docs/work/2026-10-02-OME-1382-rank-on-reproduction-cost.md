---
ticket: OME-1382
stack: scoreboard
status: done
started: 2026-10-02
finished: 2026-10-02
---

# rank-on-reproduction-cost — rank and show spend plus cache saving (board half)

## Intent

`OME-1143`: a cached run spends about $0 and, marked `complete`, takes a frontier slot it has not
earned. The board stores the saving beside the spend (`OME-1325`) but nothing reads it. This unit
makes every ranking and display read path serve the **reproduction cost**, spend plus saving, for a
`complete` row that carries a saving, and leaves every other row exactly as today. It is inert until
the SDK sends such rows (the `client-sf` half, filed separately under `OME-1251`), so it ships and
deploys first (owner, 2026-10-02, D3).

## Planned changes

- `apps/scoreboard/src/scoreboard/scores/reproduction_cost.py` (new): one pure function,
  `reproduction_cost(run_cost_usd, run_cost_status, cache_saved_cost_usd)`.
- `apps/scoreboard/src/scoreboard/scores/store.py`: the ranked query and the Pareto query also
  select `run_cost_status` and `cache_saved_cost_usd`; the ranked rows, the Pareto inputs, the trend
  history and the owned-entries list serve `reproduction_cost(...)`. `_score_to_schema` is NOT
  touched: it feeds the private export, whose bytes are a purge digest.
- `apps/scoreboard/src/scoreboard/routes/leaderboard.py`: the spec-history DTO serves the same.
- Tests: `tests/unit/scores/test_reproduction_cost.py` (pure), and
  `tests/unit/test_reproduction_cost_routes.py` (table, frontier marks, chart input, trend, history,
  export unchanged).
- Mirror `docs/tasks/2026-09-25-OME-1382-*.md` if present, else created at PR-open.

## Test plan

- Pure: `complete` + saving sums; `complete` without saving, `partial`, `unavailable`, legacy
  `None` status are unchanged; a `partial` row with a saving still serves no cost.
- Routes: a cached `complete` row ranks and displays at spend plus saving; a dominated-by-the-sum
  case flips frontier membership; the trend uses the same cost as the current frontier; the
  history route agrees; the private export of the same row is byte-identical to before.
- Mutation: drop the status gate; drop the sum at the Pareto input only.

## Acceptance

- the frontier, the table, the chart input, the trend and history all serve one number per row
- a row with no saving ranks exactly as today; the export digest is unchanged
- full scoreboard gates green, including the portal Node suite

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus no mirror creation (the 2026-09-25 mirror exists and is
  updated). `scores/reproduction_cost.py` (new); `scores/store.py` (`_serve_reproduction_cost`,
  `cache_saved_cost_usd` added to the raw-row conversion, both raw queries select status and
  saving, five read paths served); `routes/leaderboard.py` (`_history_submission`).
- **Commits:** two, `Refs: OME-1382` (board half, then the D7 extension).
- **Gates:** `run_gates.py scoreboard --base origin/main` ALL GATES GREEN with NO skip (no prior
  test changed): ruff, format, pyright, pytest 871 passed / 7 skipped, coverage 90% (floor 80),
  `reproduction_cost.py` 100%, `store.py` 98%; portal Node suite green.
- **RED/GREEN:** 6 route tests failed for the stated reason before (`'0.010000' == '5.000000'`,
  frontier size `1 == 2`, trend costs, history, owned rows); 3 "nothing changes" tests passed
  throughout, as they pin today's behaviour.
- **Mutations (all caught):** drop the `complete` gate (legacy-with-saving test); Pareto input keeps
  the bare spend (frontier and card tests); sum inside `_score_to_schema` (export test, and the
  history test, which then double-counts).
- **Deviations:** the trend replay (`frontier_history_inputs`) and the private owned-rows list were
  not in the 2026-09-29 design and are added here: without them the trend's last point and a
  participant's own view would show a different cost from the card. The 2026-09-29 note that the
  export emits no cost field was wrong (it dumps all three), so the sum stays out of
  `_score_to_schema`.

## D7 extension (2026-10-02, same PR, owner's choice)

`OME-1251` D7 (owner, 12:57, reverses D3) publishes archive-matched cache money and supersedes the
"every hit provider-reported" rule recorded on OME-1382 at 12:17. Owner chose to extend #1227 rather
than stack a follow-up, and to keep the archive saving unlabelled now but separately stored.

- **Files:** `scores/models/score.py` (column), `scores/migrations/0017_score_cache_saved_cost_archive.py`,
  `scores/schemas.py` (submission field, validators, `ScoreSchema` field excluded when absent),
  `scores/store.py` (create, replay snapshot, receipt, both raw queries, all five read paths),
  `scores/reproduction_cost.py` (third operand), `routes/leaderboard.py`.
- **Tests:** `tests/unit/scores/test_cache_saved_archive.py` (12: contract, storage, receipt,
  export present/absent, replay fill, replay never on a priced row, guard on a direct-write row),
  3 more pure tests, 1 route test. RED first: 6 failed on `extra_forbidden`, 3 pure on the missing
  operand. The `unavailable` refusal test first passed for the wrong reason (it matched the field
  name in the unknown-field error); tightened to the real message.
- **Migration:** applied 0001-0017 to a fresh SQLite file; `tortoise makemigrations` then reports
  "No changes detected".
- **Mutations (all caught):** archive not summed (3 tests); archive left out of the replay guard
  (the direct-write guard test, added because no API path reached that branch); archive always
  exported (export-omits test); archive dropped on the read path (route test).
- **Gates:** `run_gates.py scoreboard --base origin/main` ALL GATES GREEN with no skip; 887 passed,
  7 skipped; coverage 90%; `reproduction_cost.py` 100%.
