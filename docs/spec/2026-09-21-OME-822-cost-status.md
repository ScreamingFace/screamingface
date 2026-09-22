# OME-822 — A run cost that can say "I don't know"

Extends `docs/spec/2026-09-04-OME-822-require-run-cost.md`. Scoreboard half of `OME-1251`.

## §1 The three states that must stay distinguishable

| state | meaning | wire | stored amount | stored status |
| -- | -- | -- | -- | -- |
| known | every component priced | amount + `complete` | the amount | `complete` |
| unknowable | run happened, cost not derivable | `partial` or `unavailable` | `null` | that member |
| no cost concept | imported baseline, pre-`OME-770` row | n/a — not a submission | `null` | `null` |

Today the last two collapse into a bare `null`, which is why the frontier cannot tell a row it
should exclude from a row that never had a cost. The stored status is what separates them.

## §2 The wire contract

> **AMENDED 2026-09-22, after review of PR `#841`.** This section originally read: *"`run_cost_usd`
> is **required on the request**. `run_cost_status` is **required** alongside it."* That contract
> is **undeployable in one step** and was split into expand/contract. The goal below is unchanged;
> the phase it is enforced in is. `OME-1258` owns the flip.

**The goal:** a client that can determine its cost and stays silent is a client bug, and the board
should say so. Reached in two deployments, not one.

| phase | ticket | `run_cost_status` on the request |
| -- | -- | -- |
| **expand** | `OME-822` — **shipped** `99e2d4b2` | **optional** |
| client | `OME-1252` | the SDK sends it explicitly |
| **contract** | `OME-1258` | **required**; silence becomes a 422 |

**Why not one step.** The deployed SDK sends `run_cost_usd` and no status. A required status 422s
every live submission the moment the board deploys, including payloads carrying a perfectly good
cost — and the client cannot ship first either, because an older board is `extra="forbid"` and
rejects the unknown field. That is a deadlock (review finding P1-1, 2026-09-22).

The three members are unchanged:

* `complete` — the amount is present and exact.
* `partial` — the amount is absent; a cache saved-cost total exists, so a real lower bound is
  known even though the total is not.
* `unavailable` — the amount is absent and no cost evidence exists.

**§2.1 The pairing is validated, not assumed.** `complete` without an amount, or an amount with a
non-`complete` status, is a client bug and is rejected. A contract that permits both spellings of
the same fact gets both, and then the board has to guess which one meant it. **This holds in the
expand phase already** — it is a rule about a status that was *supplied*, so it costs no
deployed client anything.

**§2.2 Required on the wire is NOT non-null in the column.** The amount column stays
`null=True`. `OME-770` requires that for imported `OME-322` baselines, and D1 requires it so an
unpriced row stores `null` — which is what makes §3 free.

**§2.3 What the expand phase does with silence.** Two cases, and they are not the same:

* **status absent, amount present** → resolves to `complete`. Not a guess: an amount IS the claim
  `complete` makes. Resolving in the model validator rather than the store means the submission
  object, the stored row and the response carry the same fact, so pre-`OME-1252` clients produce
  correctly labelled rows instead of a population `OME-1258` would have to clean up.
* **both absent** → **accepted**, stored unlabelled, indistinguishable from a legacy row. The
  board does not know whether the client looked, and claiming it did would invent evidence. This
  is the row `OME-1258` starts refusing, and the one case where the goal above is not yet met.
  Pinned by `test_a_submission_with_neither_amount_nor_status_stays_unlabelled`.

## §3 What this deliberately does NOT change

Verified against `origin/main` before specifying:

* `scores/pareto.py:91-92` skips any entry whose `run_cost_usd` is `None`, so an unpriced row
  cannot reach a cohort, let alone the frontier.
* `portal/leaderboard-logic.js:115` renders `null` as an em-dash.

**No frontier change and no portal change.** D2's exclusion is a consequence of storing `null`,
not a feature to build. Rewriting either would be re-implementing behaviour that already holds
and risking a regression in the one path the openness statistic depends on.

## §4 The status must be STORED

`ranking_notice` is built in `routes/scores.py::_submission_response` via `model_copy` and never
persisted. Revision mismatch survives that because it is recomputable on read — compare the
stored revision against the registered one. **Unpriced-ness is not recomputable**: once the
amount is `null`, nothing distinguishes "we were told it was unknowable" from "this row predates
the field".

Emitting only the receipt would look correct in review and silently lose the evidence the
frontier's honesty rests on. The status is a column.

## §5 Replay

`content_hash` excludes cost (`OME-770` D8), so a recipe already stored without a cost cannot
later gain one — the replay dedups and the incoming value is discarded.

This is the identical class of bug `OME-1181` Q3 fixed: fill-only enrichment decided against a
row re-read under `select_for_update()` inside the transaction. Reuse `_replay_updates` and
`_apply_replay_updates` in `scores/store.py`. The amount and the status must move together or a
row can end up `complete` with a `null` amount.

## §6 Out of scope

- publishing a lower bound anywhere for a `partial` row — the data is stored, no surface reads it
- `archive_matched` money (`OME-1251` D3 — not published)
- the client half (`OME-1252`)
- providers reporting tokens rather than USD (`OME-1156`)
