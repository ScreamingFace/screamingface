---
ticket: OME-923
stack: scoreboard
status: done
started: 2026-08-29
finished: 2026-08-29
---

# OME-923 — Compute the Pareto frontier (part A)

## Intent

Mark the submissions where no other submission on the same board is **both** higher-scoring and
cheaper. This unit is **part A only**: the pure computation that decides what the board will
claim. Parts B (marking rows) and C (the accuracy-vs-cost chart) follow and are explicitly
gated — the ticket allows A against fixtures now, but forbids B/C from merging until real cost
data flows.

## Why now

`OME-303` (per-call cost, Done 2026-08-14) and `OME-304` (cumulative run cost, Done
2026-08-19) closed the producer chain. `OME-1029` (PR #770) makes the SDK send the run total.
`OME-923` itself has an empty `blockedBy`, and Irina answered all four design questions on
2026-08-24, so the semantics are settled rather than assumed.

## Decisions

| # | Decision | Source |
|---|---|---|
| D1 | Cost is the **whole benchmark run**, not per case | Irina, 2026-08-24 |
| D2 | The frontier mark is "Pareto-frontier SOTA"; absolute SOTA stays the highest score, a separate mark | Irina, 2026-08-24 |
| D3 | Imported baselines are **excluded** | Irina, 2026-08-24 |
| D4 | 3D charts are **out of scope** here — `OME-923` covers accuracy vs cost only; `OME-324` keeps 3D | Irina, 2026-08-24 |
| D5 | New identifiers must **qualify** — `frontier.py`, `compute_frontier`, `FrontierPoint`, `FrontierResult` are `OME-323`'s and keep their meaning | ticket |
| D7 | **Standard Pareto dominance**, not the ticket's literal wording. A row is dominated when another is at-least-as-good on both axes and strictly better on one. The ticket says "no other has **both** a higher score **and** a lower cost", which read strictly would keep a row scoring the same at 9x the cost — indefensible on a "best score for the money" board. Exact ties on both axes still both qualify, which is what the ticket's "ties both qualify" line means. | owner, 2026-08-29 |
| D12 | **Rows are compared only within one `benchmark_revision`**, and the key is `(spec_id, benchmark_revision)`. Supersedes D8. Raised in review of PR #778. | owner, 2026-08-29 |
| D13 | The caller must pass the **whole ranked set**, never a truncated page. Documented as an `AIDEV-NOTE`; enforced by the only caller, part B. Raised in review of PR #778. | owner, 2026-08-29 |
| D8 | ~~Returns `frozenset[str]` of `spec_id`~~ — **superseded by D12**. Original text: Robust to the re-sorting the ranking route does; safe because `leaderboard()` collapses to best-per-spec. **INVARIANT: not for `list_owned_entries()`**, which deliberately does not collapse. | owner, 2026-08-29 |
| D6 | A null cost is **excluded, never zero**; exclusion follows the missing value, so a row joins automatically if cost is populated later | ticket + `OME-770` |

## Planned changes

- `apps/scoreboard/src/scoreboard/scores/pareto.py` — new, the pure function
- `apps/scoreboard/tests/test_pareto.py` — new, the tests that carry this unit

No schema change, no migration, no route change, no store change in part A. `tortoise-dev`'s
`when` condition (models/querysets/migrations/transactions/signals/lifespan) does **not** match
this unit — it is a pure function over already-fetched schemas.

## Test plan

RED first. The invariant under test is D6: **a null cost never reads as zero and never wins.**

- Empty input → empty frontier.
- Single priced row → that row.
- Strictly dominated row (lower score AND higher cost) → excluded.
- Cheaper-but-worse and dearer-but-better → **both** on the frontier.
- Equal score, different cost → the cheaper one only.
- Equal cost, different score → the higher-scoring one only.
- Exact tie on both score and cost → **both** qualify (D6 ties).
- Null cost alongside priced rows → excluded, and never treated as 0 even when it holds the
  top score.
- **All** rows null cost → empty frontier, no error (the board-with-no-cost-data case).
- A zero cost is a real value, distinct from null, and can win.

## Acceptance

- The frontier is correct for ties, domination, and excluded null-cost rows, unit-tested with
  no database.
- `OME-323`'s open/closed frontier keeps its name, endpoint and meaning — untouched.
- Full `scoreboard` gates green.

## Outcome

- **Actual files:** exactly as planned — `scores/pareto.py` and `tests/unit/scores/test_pareto.py`
  added, nothing modified. No schema, migration, route or store change, so `tortoise-dev`'s
  `when` never matched and stack rule S1 is satisfied vacuously.
- **Gates:** ALL GREEN — append-only check, ruff check, ruff format, pyright (no `type: ignore`),
  pytest `--cov-fail-under=80`, and the Node portal test. Suite 518 → **529 passed**, 3 skipped.
- **Mutation-checked, both guards, re-verified after the formatter rewrote `_dominates`:**
  reading a null cost as `0` fails 3 tests; the ticket's literal strict-both dominance fails 3
  tests. Source restored byte-for-byte after each.
- **Blast radius: zero.** Nothing imports `pareto.py` yet — part B wires it. `frontier.py`,
  `compute_frontier`, `FrontierPoint` and `FrontierResult` are untouched, so `OME-323` keeps its
  name, endpoint and meaning.
- **Deviations:**
  1. **No `docs/spec/` or `docs/plan/` artifact.** The ticket body carries the spec and Irina's
     2026-08-24 comment locks every open decision, so a separate spec would have duplicated the
     issue — which `task-management` explicitly forbids ("they cross-reference, never duplicate").
     The ledger carries the plan. Matches the `OME-1029` precedent, a comparable single-function
     unit that shipped ledger-only; specs/plans here are reserved for design-heavy units
     (`OME-901`, `OME-1004`, `OME-986`). Flagged rather than skipped silently.
  2. **D7 contradicts the ticket's literal wording** and was escalated rather than assumed. See
     the decision table.

## Still gated — do NOT merge parts B or C on this branch

Part B (marking rows) and part C (the accuracy-vs-cost chart) must wait for real cost data:
`OME-1029` (PR #770) merged, a client release carrying it, and a submission that reports a cost.
Every `run_cost_usd` on the live board is null today, so B would render a frontier of nothing and
C would chart an empty axis. Part A is safe to merge alone precisely because nothing calls it.


## Review response — PR #778 (2026-08-29)

Two P2 findings, both verified against the query before acting on them. Both were correct.

### 1. The revision must be preserved and partitioned on — CONFIRMED, reproduced

`_build_leaderboard_query` partitions its window by `(spec_id, benchmark_revision)` and applies
the revision filter **only** when the benchmark has a registered revision:

```python
if registered_revision is not None:
    ranked = ranked.where(scores.benchmark_revision == registered_revision)
```

I had checked that `leaderboard()` collapses best-per-spec, but only on the registered-revision
path. On the other branch — the legacy boards the code's own AIDEV-NOTE names — nothing is
filtered, so a spec appears once per revision and D8's `INVARIANT: one row per spec_id` was
false. Reproduced before fixing: a row beaten on **both** axes was marked, because it inherited
the mark its own spec earned on a different revision.

Fixed per D12. Note the deliberate consequence, pinned by
`test_a_lone_priced_row_on_a_revision_is_that_revisions_frontier`: a revision with a single
priced row marks that row, since it is trivially the best value available on that revision. The
two rows were never comparable, which is why the cohorts exist.

### 2. Boundary score ties at the `top_n` cutoff — CONFIRMED, documented here, enforced in part B

`leaderboard()` ends `.orderby(ranked.score, order=Order.desc).limit(top_n)` — cost never enters
the ordering. A row just past the cutoff can tie the boundary score at a lower cost and dominate
a visible row it was never compared against, so the frontier would change with `top`.

One refinement to the report: this bites **only** on an exact score tie. Rows past the cutoff
have score ≤ the boundary and dominance requires score ≥, so a strictly-lower-scoring omission is
harmless. The reviewer's 51-equal-scores example is the reachable case.

A pure function cannot defend against what it was not given, so part A carries the contract as an
`AIDEV-NOTE` (D13) and **part B, the only caller, fetches the full ranked set**. Not reachable on
today's data — real boards hold ~6 rows against a cutoff of 50 — but wrong by the ticket's own
wording ("no other submission on the same board"), independent of row counts.

### Gates after the fix

ALL GREEN, append-only included. 17 unit tests on this module (11 → 17). Mutation-checked:
collapsing every revision into one cohort fails; dropping the revision from the key fails.
