---
id: OME-923
linear_url: https://linear.app/openmined/issue/OME-923/add-a-pareto-frontier-to-the-leaderboard-mark-the-best-score-for-cost
status: in_progress
type: feature
priority: 2
labels: [scoreboard, agentic, autonomous]
created: 2026-08-20
closed:
---

# Add a Pareto frontier to the leaderboard: mark the best score-for-cost submissions

Mark the submissions where no other submission on the same board is both better and cheaper.
Multiple winners are expected and wanted — the frontier is a set, so more than one participant
can hold a defensible "best score for the money" claim on one board.

## Parts

| Part | What | State |
|---|---|---|
| A | Compute the frontier — a pure function, unit-testable without a DB | **Done**, PR #778 |
| B | Mark qualifying rows, distinct from the gold highest-score mark | gated |
| C | Accuracy-vs-cost chart with the frontier drawn | gated |

A → B → C. A gates the other two. B carries most of the value at a fraction of C's cost.

## The gate on B and C

`run_cost_usd` is null on every row today. B and C must not merge until real cost data flows:
OME-1029 (PR #770) merged, a client release carrying it, then a submission reporting a cost. An
empty frontier rendering cleanly is acceptable; a cost claim computed over nulls is not. Part A
merges alone safely because nothing imports it.

## Decisions

Irina answered the four open questions on 2026-08-24:

1. **Cost is the whole benchmark run**, not per case.
2. **"Pareto-frontier SOTA"** for this mark; absolute SOTA remains the highest score, a separate
   and visually distinct mark.
3. **Imported baselines are excluded** — they have no run cost and were never run by us.
4. **3D charts are out of scope here.** OME-923 covers accuracy vs cost only; OME-324 keeps 3D.

Two further decisions were escalated during part A (2026-08-29):

5. **Standard Pareto dominance**, not the ticket's literal *"no other has both a higher score and
   a lower cost"*. Read strictly, that keeps a row scoring the same at nine times the price
   because nobody outscored it. Exact ties on both axes still both qualify.
6. **Part A returns `frozenset[str]` of `spec_id`** — robust to the ranking route's re-sorting.
   Valid only for the collapsed board; `list_owned_entries()` does not collapse and is not a
   valid input.

## Don't regress

- OME-323's open/closed frontier keeps its name, endpoint and meaning. It owns `frontier.py`,
  `compute_frontier`, `FrontierPoint`, `FrontierResult`. The new code is `pareto.py` /
  `compute_pareto_frontier` so a grep for either stays honest.
- A null cost never reads as zero and never wins a comparison.
- The highest-score mark keeps its current meaning and wording.
- Neither mark relies on colour alone.

## Ledger

`docs/work/2026-08-29-OME-923-pareto-frontier-compute.md` (part A)
