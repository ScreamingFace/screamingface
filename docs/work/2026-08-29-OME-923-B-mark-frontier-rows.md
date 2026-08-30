---
ticket: OME-923
stack: scoreboard
status: done
started: 2026-08-29
finished: 2026-08-29
---

# OME-923 — Mark the Pareto frontier rows on the board (part B)

## Intent

Show which submissions hold the "best score for the money" claim. Part A computes the set;
this renders it. The API carries a per-row flag and the portal draws a mark in the reserved
`col-mark` column, distinct from the existing gold highest-score mark.

**Stacked on part A** (`OME-923-pareto-frontier`, PR #778) — that branch is the merge base, so
this branch's diff is part B alone.

## Explicitly NOT for merge yet

The ticket gates B on real cost data flowing. Every `run_cost_usd` on the live board is null, so
this renders nothing today. Built now to validate part A's contract while part A is still
changeable, and to show the assembled feature. **Do not merge before `OME-1029` (PR #770) is in
and a client has submitted a cost.**

## Decisions

| # | Decision | Source |
|---|---|---|
| D9 | **Computed server-side**; the API sends `on_pareto_frontier` per row and the portal only renders it. Supersedes `OME-770` spec §5 D9 ("the frontier maths belongs in `portal/leaderboard-logic.js`"), whose stated reason — avoiding a conflict with the then-unmerged PR #569 — has expired. Server-side also removes `OME-770` §2.4's lexicographic trap entirely: Python compares `Decimal`, so `"1000.00" < "3.50"` cannot arise. | owner, 2026-08-29 |
| D10 | The flag rides on `RankedLeaderboardEntry` **only**, not `LeaderboardEntry`. It is computed, like `rank`. This preserves `OME-894` D5 by construction: a private board returns `entries: []` and puts the caller's own rows in `my_submissions`, which are plain `LeaderboardEntry` — so the aggregate can never reach a private board and needs no special-casing. | derived from `OME-894` |
| D11 | The mark must not rely on colour alone, and must stay semantically distinct from the highest-score mark — a row can be one, both or neither. | ticket |

## Planned changes

- `src/scoreboard/routes/leaderboard.py` — `on_pareto_frontier` on `RankedLeaderboardEntry`;
  `_ranked_entry` takes it explicitly; the public board handler computes the frontier once.
- `portal/benchmark.js` — populate `renderMarkSlot`, which currently returns an empty `<td>`.
- `portal/portal.css` — the mark's styling.
- `tests/unit/test_leaderboard_routes.py` — route-level tests.
- `tests/portal/leaderboard-logic.test.js` — if any pure JS logic is added.

No schema change and no migration: the flag is computed per request, never stored. Stack rule S1
does not apply. `tortoise-dev`'s `when` does not match — no model, queryset or migration work.

## Test plan

RED first. The invariant under test is D10: **the aggregate never reaches a private board.**

- A public board with cost data flags exactly the frontier rows and no others.
- A public board with no cost data flags nothing and still returns 200.
- The flag is absent from `my_submissions` on a private board (they are `LeaderboardEntry`).
- A private board returns `entries: []`, so no flag is emitted for anyone, owner included.
- `_ranked_entry` keeps `LeaderboardEntry` and `RankedLeaderboardEntry` in step — the
  `extra="forbid"` splat still round-trips.
- Portal: a flagged row renders the mark plus its accessible text; an unflagged row renders the
  empty slot; a row that is both highest-score and on the frontier carries both marks distinctly.

## Acceptance

- Frontier rows are marked on the board, distinctly from the gold highest-score row.
- A board with no cost data renders without error and marks nothing.
- `OME-894`'s privacy rule holds: no frontier information on a private board.
- Full `scoreboard` gates green, including the Node portal test.

## Outcome

- **Actual files:** as planned, plus `portal/leaderboard-logic.js`. The mark predicate went into
  that file rather than inline in `benchmark.js` so it lands under the Node gate — `benchmark.js`
  has no test harness, `leaderboard-logic.js` does.
- **Gates:** ALL GREEN. Python 529 → **532 passed**, 3 skipped. Node 25 → **30 passed**.
- **Mutation-checked, 3 of 3 caught:** marking every row fails the route tests; marking no row
  fails them; dropping `isParetoMarked`'s strict `=== true` fails the Node tests. Sources restored
  byte-for-byte.
- **Verified end to end against a seeded local board**, which is the point of building B early:

  | | rank | spec | score | cost |
  |---|---|---|---|---|
  | | 1 | big-panel-5x | 0.842 | $48.10 |
  | **◆** | 2 | claude-gemini-fusion | 0.842 | $12.40 |
  | | 3 | legacy-import | 0.810 | — |
  | **◆** | 4 | gpt-solo | 0.795 | $3.20 |
  | **◆** | 5 | cheap-trio | 0.771 | $0.94 |
  | | 6 | wasteful-duo | 0.760 | $9.80 |

  The rank-1 row is **not** on the frontier and the rank-2 row is — the two claims are genuinely
  separate, which is what D11 required and what a reader has to be able to see.

## Deviations

1. **`--skip-append-only` was used, with the owner's approval for the one substantive change.**
   The gate flagged two files. Verified before skipping: `git diff` shows **zero deleted lines**
   in both, so nothing was rewritten, weakened or skipped. `test_leaderboard_routes.py` has one
   in-place edit — adding `"on_pareto_frontier"` to `_PUBLIC_BOARD_ENTRY_FIELDS`, approved
   2026-08-29, with the assertion left as exact set-equality so it still catches any other field
   appearing on the public board. `leaderboard-logic.test.js` is a pure append the checker cannot
   verify because it does not parse JavaScript.
2. **`OME-770` spec §5 D9 is superseded** — see the decision table. Recorded because a future
   reader will find two written specs disagreeing on where the frontier is computed.
3. **No screenshot.** The DevTools MCP could not attach (another session holds the Chrome
   profile) and headless Chrome hung. The board was verified through the API instead, and the
   table above is that response. Re-runnable locally, see below.

## Reproducing the board locally

```sh
uv run python <seed>          # register a benchmark, submit rows, set run_cost_usd
SCOREBOARD_DATABASE_URL=sqlite://<db> SCOREBOARD_PORT=9166 uv run scoreboard
curl -s localhost:9166/v1/leaderboard/<id> | jq '.entries[] | {spec_id, on_pareto_frontier}'
open http://127.0.0.1:9166/benchmark.html?id=<id>
```

## Known gap, surfaced not fixed

**The portal still has no Cost column** — the mark renders beside no money figure, so a reader
cannot tell why a row won. `OME-770` was pass 1 of 2 and its spec puts the Cost column in pass 2,
which never ran. Out of scope for B as written; needs an owner call on whether it joins B, joins
C, or becomes its own item.


## Review-fix pass — PR #778 findings, applied here (2026-08-29)

Part A carried the contract; part B is the only caller, so both fixes land on this branch.

| Fix | Change |
|---|---|
| Revision keying | The mark is now `(row.spec_id, row.benchmark_revision) in frontier`. One spec can hold rows on several non-comparable revisions and each is judged only within its own. |
| `top_n` truncation | New `ScoreStore.frontier_candidates()` returns the ranked board **unbounded**; `_build_leaderboard_query` takes `top_n: int | None`. The route computes the frontier from that, never from the truncated `rows`. |

Python suite 532 → **535 passed**. Mutation-checked, both caught: reverting to
`compute_pareto_frontier(rows)` fails; keying the mark on `spec_id` alone fails.

### The board has no tiebreaker among equal scores — worth someone's attention

Making the truncation test deterministic exposed this. The board's outer ordering is
`score DESC` with **no** secondary key, so the order among rows tied on score is whatever the
backend returns: alphabetical by `spec_id` on SQLite (index scan), insertion order on Postgres
(heap scan). `test_get_leaderboard_breaks_accuracy_ties_by_newer_submission` does not cover
this — it ties two rows of the SAME spec, which the inner `rn` window orders by
`submitted_at DESC`. Ordering *across* specs is undefined.

Consequences beyond this ticket: `rank` is not stable for tied rows, and which tied row falls
outside `top` can differ between environments. The new test works around it by naming the
hidden row `z-cheapest` and inserting it last, so it sorts out of `top=2` under either scan —
recorded in an `AIDEV-NOTE` on the test, because renaming those specs would leave the test
green while proving nothing. **Not fixed here** (it is a pre-existing board-ordering question,
not a frontier one) and not filed — owner's call.


## Self-review pass — privacy regression fixed (2026-08-30)

Ten independent lens-reviews of this branch returned 24 findings. Nine of them shared one root
cause: the two-query split introduced by the previous pass to fix the `top_n` finding.

### The regression, reproduced before fixing

`frontier_candidates()` was issued **after** the `turned_private()` guard. On `origin/main` that
guard was the last `await` before the response — deliberately, per PR #719 (OME-894 review round
21) and its own docstring: *"the decision is re-checked against fresh state before anything
unscoped leaves."* The new call put the widest read on the whole path after it: unbounded, every
spec, with `submitted_by` and `run_cost_usd`.

Reproduced with the repo's own race harness, `_flip_private_during("frontier_candidates")`:

```
AssertionError: LEAKED 2 rows
```

Both participants of a private board published, with `scoped_to_caller: false`, on a board that
was private by the time it answered. Exactly what
`test_a_flip_during_the_ranking_query_does_not_publish_the_board` exists to prevent.

### The fix — one read, taken before the guard

`ScoreStore.leaderboard` now accepts `top_n: int | None`; `None` returns the board whole. The
route takes **one** read, before the guard, computes the frontier from it, and serves the page
as a prefix of the same list. `frontier_candidates()` is deleted.

Chosen over a new store method deliberately: the existing race test hooks
`ScoreStore.leaderboard`, so routing around it would have left that test green while testing
nothing.

This closes four of the reported findings at once — the privacy race, the snapshot skew (a mark
computed about a different version of a row than the one displayed, including a null-cost row
being marked), the self-contradicting response body, and running the app's most expensive query
twice per request.

### Guards added

- `test_the_public_board_takes_exactly_one_ranking_read` — pins the SHAPE of the fix, so a
  reintroduced second query fails even when the leak itself is hard to time.
  Mutation-checked: putting a second read back after the guard fails it.
- `test_the_board_can_be_read_whole` — the `top_n=None` seam.

Suite 535 → **542 passed**.

## Still open from the self-review — NOT fixed here

1. **A submitter can mint their own revision cohort.** `benchmark_revision` is free-form client
   input (`_resolve_benchmark_revision`, and the store's own comment: "metadata is
   client-supplied and unvalidated"). On a benchmark whose `Benchmark.revision` is NULL the
   board filters nothing, so a submitter sending a unique revision becomes a cohort of one and
   is unconditionally marked "best score for cost". This is a consequence of the per-cohort
   decision taken 2026-08-29; the alternative considered then — no marks on an unpinned board —
   would have closed it. **Owner decision required.**
2. **The mark is unreadable to sighted users.** The diamond is `aria-hidden`, the only text is
   `.sr-only`, the column header is empty, and there is no legend or `title`. A screen-reader
   user is told "best score for cost"; a sighted user sees an unexplained blue diamond, with no
   Cost column to infer it from.
3. **`OME-770` D11 provenance** — the mark asserts a cost claim built on self-reported numbers
   without saying so.
4. **O(n^2) frontier runs synchronously in an async route**, over an unbounded row count with no
   cap or rate limit.
5. **Test gaps** — no second-benchmark test (cross-benchmark scoping is correct in code but
   unpinned); `renderMarkSlot` is never executed by any test; the a11y contract is unasserted.
