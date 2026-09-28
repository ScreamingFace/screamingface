---
id: OME-822
linear_url: https://linear.app/openmined/issue/OME-822/require-run-cost-usd-on-direct-leaderboard-submissions
status: done
type: task
priority: 2
labels: [scoreboard, agentic, autonomous]
parent: OME-1251
created: 2026-08-13
closed: 2026-09-22
---

# Require a run cost, and let an unpriceable run say so

Scoreboard half of epic `OME-1251`.

**Rescoped 2026-09-21.** The original scope — make `run_cost_usd` mandatory and non-null — was
wrong on its own. An unpriced run has no legal value to send, so it would send `0`: publishing
an unknown cost as free and handing it the cheapest slot on the Pareto frontier. That is the bug
`OME-1143` describes, reintroduced by its own fix.

## What ships

A submission carries a real amount **or** a status saying the amount is unknowable.

**Rescoped again 2026-09-22, at review.** This section read *"Omission is still rejected, which is
what this ticket exists to enforce."* **It is not, and this ticket does not.** A required status
422s every live submission the moment the board deploys, because the deployed SDK sends an amount
and no status — and the client cannot ship first, because an older board is `extra="forbid"`. The
contract was split: `OME-822` ships the field **optional** (expand), `OME-1252` makes the SDK send
it, and `OME-1258` flips it to required. The goal is unchanged; the phase is.

| | |
| -- | -- |
| Wire | `run_cost_status` **optional** — the expand phase. `run_cost_usd` optional but **gated**: a model validator refuses `complete` without an amount, and an amount without `complete`. An absent status beside an amount resolves to `complete`. **Both absent is accepted** and stores unlabelled; `OME-1258` starts refusing it |
| Vocabulary | `complete` \| `partial` \| `unavailable` — run-level, NOT the gateway's per-call `DirectCostStatus` (`OME-1251` D4) |
| Storage | The status is a **stored column** (`0014_score_run_cost_status`). The amount stores `null` whenever the status is not `complete` |
| Frontier | **No change** — `scores/pareto.py:91` already skips a null-cost entry, and `formatCost` already renders an em-dash |

Null for both fields stays a third, distinct state: the row predates this field. That is not the
same as `unavailable`, where a client looked and could not determine the cost.

## Not a `ranking_notice`

`OME-1251` D2 originally said an unpriced row would carry one. Withdrawn. That type means *"why a
score will not enter the current ranking"*, and an unpriced row **does** rank — it is absent only
from the cost frontier. Recorded as an `AIDEV-NOTE` on `ScoreRankingNotice`.

## Artifacts

- Spec: `docs/spec/2026-09-21-OME-822-cost-status.md` (extends `2026-09-04-OME-822-require-run-cost.md`)
- Plan: `docs/plan/2026-09-21-OME-822-cost-status.md`
- Ledger: `docs/work/2026-09-21-OME-822-cost-status.md`
- PR: #841 — approved at `c4346e02`, squash-merged `99e2d4b2` on 2026-09-22
- Doc alignment follow-up: `OME-1265`

Related: `OME-1252` (the client half), `OME-1258` (the flip to required), `OME-1143` (the bug
this serves), `OME-770`, `OME-1181`
(whose Q2 `exclude_if` and Q3 fill-only-under-lock rules are both reused here).
