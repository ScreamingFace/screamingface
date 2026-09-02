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


## Legibility + fail-closed pass (2026-08-31)

Rebased onto `main` — part A merged as `7cd43141`, so this branch now carries part B alone.

Two owner decisions taken today, both closing self-review findings.

| # | Decision | Source |
|---|---|---|
| D12 | **No marks on a benchmark with no registered revision.** Fail closed: if the board cannot say which revision it is about, it makes no best-value claim. | owner, 2026-08-31 |
| D13 | **Add the Cost column and a legend**, completing the minimum of `OME-770` pass 2. The mark is a claim about money and the money was nowhere on the page. | owner, 2026-08-31 |

### D12 — why the gate lives in the route

`benchmark_revision` is free-form client input (`_resolve_benchmark_revision`; the store's own
comment: "metadata is client-supplied and unvalidated"), and `_build_leaderboard_query` filters on
revision **only** when the benchmark has a registered one. So on a NULL-revision board a submitter
could send a unique revision, land in a cohort of one, and be marked "best score for cost"
unconditionally.

`compute_pareto_frontier` is pure over rows and merged — it cannot see the benchmark. The gate
therefore sits in the route, which already holds `benchmark.revision`. The function keeps its
per-cohort behaviour for any caller that legitimately has mixed revisions, with the restriction
stated as an INVARIANT and pinned by a test, so the trap is documented rather than latent.

Unaffected: DRACO, IFEval and HealthBench all registered revisions under `OME-775`, so their
queries filter to one revision and they mark exactly as before. Only the legacy demo boards
(`hle`, `livetruth`) lose marks — and `OME-986` is retiring those.

### D13 — the display trap this walks into

`OME-770` §2.4 is explicit: the wire form is a **string** at fixed 6dp, and JavaScript compares
strings lexicographically, so `"1000.000000" < "3.500000"` is `true`. Any sort or comparison in
the portal must `parseFloat` first. D2 of the same spec requires rounding for display so a
six-decimal figure cannot overflow the column. Both belong in `leaderboard-logic.js` where the
Node gate can see them, not inline in `benchmark.js`.

The legend also carries `OME-770` D11's provenance requirement — costs are self-reported — which
closes a third self-review finding.

### Also in this pass

The three test gaps the self-review named: cross-benchmark scoping (correct in code, unpinned),
`renderMarkSlot` never executed by any test, and the mark's accessibility contract unasserted.

**~~Not fixed, deliberately: the O(n²) dominance scan.~~ REVERSED 2026-08-31 — see below.**
The reasoning recorded here was that the scan is "bounded by priced rows within one cohort,
which grows with distinct specs rather than submissions". That is not a bound: `spec_id` is a
client-supplied `CharField(255)`, so distinct specs are exactly what a submitter chooses.


### Outcome of this pass

- **Files:** `routes/leaderboard.py` (the D12 gate), `portal/leaderboard-logic.js`
  (`costNumber` / `compareCost` / `formatCost`), `portal/benchmark.js` (Cost column, cost
  comparator branch, legend visibility), `portal/benchmark.html` (the legend),
  `portal/portal.css` (legend layout; the mark selector unscoped from `.col-mark` so it can be
  reused in the key), plus tests on both sides.
- **Gates:** ALL GREEN. Python **543 passed**, Node 30 → **39 passed**.
- **Mutation-checked, 4 of 4 caught:** removing the D12 gate; letting cost fall through to the
  generic numeric compare; comparing the cost string without `parseFloat`; collapsing sub-cent
  costs to `$0.00`.

### A trap found while wiring the column

`benchmark.js`'s generic numeric comparator is `(av || 0) - (bv || 0)`. Pointing the new Cost
column at it would have coerced a **null cost to 0 and sorted unpriced rows as the cheapest on
the board** — the same "a null cost never reads as zero" rule the frontier itself rests on,
broken in the UI rather than the maths. Cost therefore gets its own comparator that converts
first and keeps unpriced rows last in **both** directions. That is now the single most
load-bearing of the new Node tests.

### Verified against a seeded board

Eight rows on a pinned revision, including two the earlier demo could not exercise: a
cache-served run at exactly `$0.000000` and a sub-cent run at `$0.000900`.

| | rank | spec | score | cost |
|---|---|---|---|---|
| | 1 | big-panel-5x | 0.842 | $48.10 |
| **◆** | 2 | claude-gemini-fusion | 0.842 | $12.40 |
| | 3 | legacy-import | 0.810 | — |
| **◆** | 4 | gpt-solo | 0.795 | $3.20 |
| **◆** | 5 | cheap-trio | 0.771 | $0.94 |
| | 6 | wasteful-duo | 0.760 | $9.80 |
| **◆** | 7 | cache-served | 0.702 | $0.00 |
| | 8 | sub-cent | 0.688 | $0.0009 |

`cache-served` at a genuine `$0.00` takes a mark; `sub-cent` is correctly dominated by it on
both axes. `legacy-import` renders an em dash and neither qualifies nor dominates.

### Still not pinned by a test

`renderMarkSlot`, the Cost cell and the legend are DOM code in `benchmark.js`, which has no test
harness — the card's gate names `tests/portal/leaderboard-logic.test.js` explicitly, and adding
a second JS test file would need a card change. All the *decisions* live in
`leaderboard-logic.js` and are covered; what remains unpinned is the wiring, verified visually
instead. Recorded rather than papered over.


## P1 from review — the unbounded quadratic frontier (2026-08-31)

Reviewer, verbatim: *"`top_n=None` removes the public endpoint's previous 200-row bound, then
`compute_pareto_frontier` compares every priced row against every other row."*

Confirmed on every point, and it is worse than the earlier note admitted:

| | |
|---|---|
| `origin/main` public path | `leaderboard(top_n=min(top, MAX_LEADERBOARD_TOP))` — bounded at 200 |
| this branch, before the fix | `leaderboard(top_n=None)` — unbounded |
| `spec_id` | client-supplied `CharField(255)` — so `n` is attacker-chosen |

The privacy fix removed an existing bound and put a quadratic scan behind it. Both halves are
mine and the dismissal above was wrong.

### Fix — sort-and-sweep, O(n log n)

`_cohort_frontier` now walks the distinct costs cheapest-first, carrying the best score seen at
any strictly lower cost. Within one cost only the rows at that cost's best score can survive;
those qualify exactly when they beat everything cheaper. Whole-board semantics are unchanged —
this is the same answer, computed differently.

Measured on this machine over a trade-off curve where nothing dominates anything:

| n | build rows | sweep | pairwise |
|---|---|---|---|
| 3,000 | 0.01s | 0.002s | 0.41s |
| 8,000 | 0.02s | 0.006s | 2.82s |
| 12,000 | 0.03s | 0.008s | **6.38s** |

### The first version of the guard test was worthless

`test_a_large_board_does_not_take_quadratic_time` originally built 5,000 rows with **random**
costs — and a reintroduced pairwise scan **passed it in 0.4s**. `any()` short-circuits the
moment a dominator is found, and over random points nearly every row is dominated immediately,
so the scan never reaches its quadratic case. Caught by mutation-checking the test rather than
trusting it.

Rewritten against the worst case: a perfect trade-off curve at n=12,000 where every row
qualifies and nothing can short-circuit. The 2s bound now has ~50x headroom green and fails a
pairwise scan by 3x.

### Guards

- `test_the_sweep_agrees_with_the_pairwise_definition` — 300 randomised boards against a
  brute-force oracle written the obvious slow way, over a deliberately tiny value space so ties
  on one axis, both axes, and across revisions occur constantly.
- `test_a_large_board_does_not_take_quadratic_time` — as above.

Mutation-checked, 3 of 3 caught: reintroducing the pairwise scan (6.5s, fails), dropping ties so
only the first row at the best score wins, and relaxing `>` to `>=` so an equal-scoring dearer
row survives. All 17 pre-existing part A tests pass unchanged, which is the real safety net —
the sweep had to reproduce them exactly.

**Residual, stated plainly:** the row *load* is still O(n) and unbounded, because whole-board
semantics require it. That is one query returning one row per (spec_id, benchmark_revision),
which is the same shape of read the endpoint always did; what is gone is the quadratic
amplification on top of it.

## Self-review round 1 (2026-08-31) — 14 findings, 6 distinct issues

Five lenses over the state after the fail-closed and Cost-column pass. Fixed:

| Issue | Fix |
|---|---|
| `formatCost` rendered one cent two ways — `0.009999` printed `$0.0100`, `0.010000` printed `$0.01`. Same money, two formats, and in the ascending Cost column the four-decimal string sits above the two-decimal one and reads as larger. | Branch on the ROUNDED value. |
| Two costs inside one cent render identically while only one is marked — the board contradicting itself with nothing on the page to explain it. | The cost cell carries a `title` with the exact stored figure. |
| `test_get_leaderboard_marks_nothing_when_no_row_reports_a_cost` had gone **vacuous**. Its board is unpinned, so D12 returns an empty frontier before `compute_pareto_frontier` is ever reached. Proven in review by patching the frontier to mark EVERY row: the test still passed. | Pinned the board. Mutation-checked: it now catches a null cost read as zero. |
| The legend advertised the frontier mark on boards where the gate guarantees none, and on the empty board. A key for a symbol that appears nowhere reads as "nothing here is good value" — the opposite of what the gate is saying. | The frontier item hides itself unless a row carries the mark; the whole legend hides on an empty board. Separators are CSS-generated so hiding an item leaves no dangling middot. |
| The label said "best score for cost", but frontier membership means only "not beaten on both axes" — so the cheapest row carries that claim however badly it scores. | Both the legend and the sr-only label now read "no submission is both better and cheaper". |
| A board the gate closes still read UNBOUNDED, dropping `origin/main`'s 200-row cap for no gain. | The whole board is read only when a frontier will be computed from it. |

Mutation-checked, 3 of 3 caught. Python 546, Node 40.

### Open, needs an owner call

**The Cost column re-introduces horizontal overflow.** Two lenses measured it independently in
Chrome against the real stylesheets: table min-content 802px to 905px. At a ~858px content box
(roughly a 900px window — a half-screen laptop, tablet landscape) `.table-wrap` overflow goes
from 0 to 47px, pushing about half the "Run Locally" Copy button behind the scroll. Below 640px
`.col-run` collapses, so mobile is unaffected; the window is viewport ~700-1010px.

This is the exact failure `benchmark.js`'s own comment records as the reason `total_questions`
was removed — the precedent being that a new column is paid for by removing one.

**Owner decision, 2026-08-31: keep the scroll, keep the columns.** No column is dropped for now.

That made a second defect the reason this was worth acting on at all: `.table-wrap` had
`overflow-x: auto` but **no `tabindex`**, so the scroll existed only for a mouse. A keyboard-only
user could not reach anything off-screen — which at these widths is the entire "Run Locally"
Copy button (WCAG 2.1.1 Keyboard). The container is now `tabindex="0"` with `role="region"` and
an `aria-label` (a focusable region needs an accessible name), plus a `:focus-visible` ring so
the focus lands somewhere visible.

Worth noting the scroll predates this ticket — every board wider than its container had the same
unreachable-content problem. The Cost column made it reachable in practice, not novel.

### Not acted on at the time — now fixed, see below

- Two independent `SELECT`s of `Benchmark.revision` (the gate's and the query's) could disagree
  within one request.


## Round 2 did NOT run (2026-09-01)

All five agents failed with a session limit; the workflow returned an empty findings array and
its journal holds zero result lines. **That empty result is a failure, not a clean round** — it
is exactly the shape of false reassurance this ledger keeps recording, so it is written down as
a non-result rather than a pass.

Reviewed directly instead, without subagents.

### Verified sound

- `Decimal("0.10")` and `Decimal("0.1000")` compare equal AND hash equal, so they share one cost
  group in the sweep; the lower-scoring row is correctly dominated.
- `Decimal("-0")` collapses onto `Decimal("0")` the same way.
- A cohort of one, and a cohort tied on both axes, both behave.
- Float scores differing in the last bit (`0.1 + 0.2` vs `0.3`) count as strictly better. That is
  consistent with `frontier.py`'s existing rule — scores are carried through from the database
  unchanged, never arithmetic — so it is not a new hazard.
- The tab strip navigates by `href`, a full page load, so the legend cannot go stale between
  benchmarks. Sorting re-renders rows but never changes which are marked.

### Found and fixed — the legend rendered a LEADING middot

The CSS-generated separator was written specifically to avoid a dangling middot when the
frontier item hides, and it did not work. `display: none` does not remove an element from the
sibling chain, so `.legend-item + .legend-item::before` still matched a hidden predecessor. On
any board that marks nothing the legend opened with a stray `·`.

Verified in Chrome against the real stylesheets before and after:

```
before:  ·  gold row = highest score ·  costs are self-reported…
after:      gold row = highest score ·  costs are self-reported…
```

Fixed with `:not([hidden])` on both sides, and the general sibling combinator so it stays correct
if more than one item ever hides.

Worth noting the shape: **I introduced this bug in the round-1 fix, in the very line whose
comment claims it prevents the problem.** Third time in this unit that a fix has landed a defect
next to itself.


## One read decides the gate and the filter (2026-09-01)

The route read `Benchmark.revision` through `_get_benchmark_or_404` to decide whether to compute
a frontier at all, and `ScoreStore.leaderboard` read the same row again to build the query's
revision filter. Two `SELECT`s, so a re-registration landing between them opens the gate on one
value while the query filters on another — the frontier is then computed over mixed revisions
and the cohort-of-one gap D12 exists to close is open for that request.

`leaderboard()` now takes `registered_revision` and does not re-read when given it; the route
passes the value it already holds. A sentinel distinguishes "not supplied" from "supplied None",
because `None` is meaningful here — it is what an unregistered benchmark has, and it means
"filter nothing".

This also removes a database round trip from every board request.

Mutation-checked: restoring the re-read fails
`test_the_board_query_trusts_the_revision_it_is_given`.

## Everything with a clear fix is now fixed

What remains, and why each is not a "clear fix":

| Item | Why it is not taken |
|---|---|
| `renderMarkSlot`, the Cost cell and the legend have no unit test | `benchmark.js` has no harness, and the card's gate names one JS file explicitly. Adding a second means changing `.claude/sdlc.local.md`, which is a card change, not a code fix. |
| The board has no tiebreaker among equal scores, so `rank` is unstable for ties | The *mechanism* is clear — add a secondary sort key. The *semantics* are a product decision: on a tie, does the newer submission rank higher, or the one that got there first? Extending the same-spec rule ("newer wins") to different participants is not obviously the fair answer on a public leaderboard. Pre-existing, unfiled. |
| A negative cost written out-of-band bypasses validation | Needs a `CHECK` constraint and a migration on a shared table, for a state only reachable by bypassing the API. Schema work under stack rule S1, and not this ticket's. |
| The row load is O(n) and unbounded on a pinned board | Inherent to whole-board semantics. The quadratic amplification is gone; what remains is one query returning one row per (spec_id, benchmark_revision), the same shape the endpoint always issued. |


## Tie ordering, and the negative-cost question (2026-09-01)

### D14 — on a tie, the earlier submission ranks higher

Owner decision. The outer ordering was `score DESC` with no secondary key, so the order among
tied rows was whatever the backend returned: alphabetical by `spec_id` on SQLite (index scan),
insertion order on Postgres (heap scan). `rank` was not stable across environments, and which
tied row fell outside `top` moved with it.

Now `score DESC, submitted_at ASC`. Deliberately ascending, while the `rn` window above it stays
`submitted_at DESC` — they answer different questions. The window picks WHICH submission
represents a spec, where the newest wins; this orders SPECS against each other, where the
earlier claim to a score ranks first.

`test_get_leaderboard_breaks_accuracy_ties_by_newer_submission` is unaffected: it ties two
submissions of the SAME spec, which the window resolves before the outer sort sees them.

The guard names its specs so alphabetical order contradicts arrival order, so it can only pass
if arrival time decides. And `test_a_frontier_mark_does_not_change_with_top` carried an
AIDEV-NOTE claiming its `z-` prefix was load-bearing because ordering was undefined — no longer
true, and corrected in place rather than left to mislead.

This closes the pre-existing item recorded twice above as "not a frontier problem, unfiled".

### Negative costs are already rejected

Checked rather than assumed. `ScoreSubmission.run_cost_usd` is
`Field(default=None, ge=0, allow_inf_nan=False)`, and `Decimal("-1.50")` is refused at the API
today. No operator module writes the column either — `seed.py`, `import_baselines.py` and
`retire_benchmark.py` never touch it.

So the exposure is only a direct database write, which nothing in the product does. The review
finding was about defence in depth, not a reachable bug.

**Out of scope here, and left unfiled:** a `CHECK (run_cost_usd >= 0)` constraint would close it
at the storage layer, but that is a migration on a shared table under stack rule S1, for a state
no code path can produce. It belongs with `OME-822`'s contract work, not with marking rows.


## Verified against the PUBLISHED client (2026-09-02)

`OME-1029`'s ledger recorded a deviation: the cross-package round-trip could not run inside the
suite, because the SDK and Scoreboard are separate deployables with separate venvs. That gap is
now closed with the real artifact rather than a substitute.

**The released client already sends the cost.** `screamingface 0.1.1.post7` (PyPI, 2026-09-01
17:43) contains `_cost_text` and `"run_cost_usd": _cost_text(candidate_result.usage.cost_usd)` —
read out of the downloaded wheel, not inferred. Note no git tag contains `ea4c866`: post-releases
are cut from `main` outside the tagged flow, so the GitHub release list still shows only v0.1.0
while the artifact shipped.

**End to end**, published wheel installed in its own venv, driving this branch's Scoreboard:

```
0.1.1.post7 builds   "run_cost_usd": "12.40"
POST /v1/scores  ->  HTTP 201, stored "12.400000"   (quantised to DECIMAL(12, 6))

 *  rank 1  released-client-check    0.842  12.400000
    rank 2  released-client-dearer   0.842  48.100000
```

Two submissions at an identical score; only the cheaper is marked. That is D7's dominance rule
deciding a public claim from a cost the **released** client produced — the first time this
feature has been exercised without a hand-written payload anywhere in the chain.

Incidental: `create_app` refused to start with `FORWARDED_ALLOW_IPS` overlapping
`SCOREBOARD_ALLOWED_NETWORKS`, explaining that uvicorn would rewrite `request.client.host` from a
client-supplied header before `peer_in_networks()` runs. That is `OME-894`'s fail-fast guard
working on a live boot, not just in tests.

### What this means for the gate

Part B's stated gate is "`OME-1029` merged, a client release carrying it, then a submission
reporting a cost". The first two are **done**. Only a real submission from someone running
`post6`/`post7` remains — no longer a release cycle, just one run. Whether any live row already
carries a cost is a production read and has not been checked from here.


## Integrated with partial-run coverage (2026-09-02)

`OME-1056`'s follow-up PR #820 merged as `2b47ae3c`. Part B was then merged with that
`main` as `32193f16`, preserving Part C's stacked ancestry rather than rebasing eleven reviewed
commits.

The conflict was semantic, not just textual. #820 makes `Benchmark.case_count` define which runs
are comparable; Part B adds a second, unbounded projection for Pareto membership. Filtering only
the visible table would let a hidden one-case run with a higher score and lower cost dominate a
complete row and suppress its mark. The route now passes one benchmark snapshot's registered
revision and case count to both the bounded display query and the minimal Pareto projection.

`test_a_partial_run_neither_ranks_nor_shapes_the_pareto_frontier` pins the combined invariant:
a one-case row scoring `0.99` at `$0.01` is absent and cannot dominate the complete row scoring
`0.80` at `$5.00`; the complete row remains marked.

Verification:

- focused cross-PR set: **110 passed**
- full Scoreboard Python suite: **576 passed, 3 skipped, 3 deselected**
- coverage: **88.54%** (80% gate)
- portal logic: **40 passed**
- `run_gates.py scoreboard`: append-only, Ruff, format, Pyright, pytest+coverage, and Node —
  **all green**

One diagnostic invocation was wrong: running the package-scoped pytest environment from the
monorepo root collected every package and failed on dependencies that environment deliberately
does not install. Re-running the identical command from `apps/scoreboard` produced the clean
576-test result above; the repository's gate runner had already passed.

The release/data gate is unchanged. A published client can send cost, but Part B still waits for a
real priced run to be visible on a live ranked board before merge.
