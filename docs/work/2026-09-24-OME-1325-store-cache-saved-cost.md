---
ticket: OME-1325
stack: scoreboard
status: done
started: 2026-09-24
finished: 2026-09-24
---

# OME-1325 — Accept and store the cache saved cost

Scoreboard half of decision **D5** on `OME-1251`. Branch from `origin/main` at `b44fa781` — the
merge of `OME-1252`, so the client that will eventually send this field is already in the base.

## SCOPE CUT TAKEN AT START — phase 1 only

The ticket carries two phases with **different gates**, and its own body says they should be
split at planning. Doing that now:

| phase | this unit | gate |
| -- | -- | -- |
| **store** — accept and persist the field | ✅ **yes** | none; purely additive |
| **rank** — frontier reads `spend + saved` | ❌ **no** | `OME-1287` (E2) must land first |

Until E2 prices every call from a central per-model list, the saved figure is incomplete — some
cached calls have no recorded price — so the sum **understates** the true cost. Ranking on it
early repeats today's failure at a smaller scale.

`OME-822` mixed a safe expand with a gated contract and had to be split at review under time
pressure. Filing pre-split is the learned behaviour; this is that split.

The read-path open question (what the portal's Cost column serves) belongs to phase 2 and is
untouched here, because nothing reads the new field yet.

## Intent

`OME-1143`: a cached run publishes ≈$0.00 and takes a Pareto frontier slot it has not earned.
`OME-822` and `OME-1252` gave the board a vocabulary for saying a cost is *unknown*. Neither
carries what a run costs to **reproduce**.

D5 decided the shape: spend and savings travel as **two separate fields**, and the board adds
them at the point of use. This unit builds the second field and nothing else.

## Planned changes

- `scores/schemas.py` — `cache_saved_cost_usd` on `ScoreSubmission` (optional) and on
  `ScoreSchema` (with `exclude_if`)
- `scores/models/score.py` — nullable `DecimalField(max_digits=12, decimal_places=6)`
- `scores/migrations/0015_score_cache_saved_cost.py` — `AddField`, no backfill
- `scores/store.py` — `_replay_updates` fills it under the fill-only rule

## Test plan

- a submission carrying the field stores it; omitting it stores null
- null stays null and never becomes `0`
- a negative or non-finite amount is refused, like `run_cost_usd`
- the bounds mirror `DECIMAL(12, 6)` exactly — `999999.999999` accepted, seven integer digits refused
- **a pre-`OME-1326` client sending `partial` with no saved cost is still accepted** — the case
  that would 422 the SDK released today
- a replay fills the field on a row that lacks it, and **cannot replace** one that has it
- the export digest of a row without the field is byte-identical to before

## Acceptance

- every test-plan bullet
- the frontier is **untouched** — `pareto.py` still reads `run_cost_usd` alone
- full scoreboard gates green, including the portal Node suite

## Outcome

- **Actual files:** exactly as planned — `scores/models/score.py`, `scores/schemas.py`,
  `scores/store.py`, `scores/migrations/0015_score_cache_saved_cost.py`, and one new test file
  `tests/unit/scores/test_cache_saved_cost.py`. **88 production lines added, 0 removed.**

- **Gates:** `run_gates.py scoreboard --base origin/main` — **ALL GATES GREEN**, and notably
  **without** `--skip-append-only`. Every test is in a new file; no prior test moved, and none
  needed to.

- **Migration verified by hand**, as `0014`'s ledger warns is necessary — nothing in CI or the
  gate runner runs migrations. Applied the real runner
  (`python -m tortoise -c scoreboard.db.TORTOISE_CONFIG migrate`) against a fresh SQLite: all 15
  applied OK, and `PRAGMA table_info(scores)` shows `cache_saved_cost_usd VARCHAR(40) NULLABLE`,
  the same shape `run_cost_usd` already has.

- **Frontier untouched, verified.** `scores/pareto.py` is not in the diff. Ranking on the sum is
  phase 2.

- **Deviations:**

  1. **Scope cut at start: phase 1 of two.** The ticket carries a store phase (ungated) and a
     ranking phase (gated on `OME-1287`), and its own body says to split them at planning. Done.
     `OME-822` mixed a safe expand with a gated contract and had to be split at review under time
     pressure; this is that lesson applied before the fact rather than after.

  2. **Two RED tests passed vacuously.** The negative-cost cases raised `ValidationError` in RED
     for the wrong reason — the unknown field, not the negative value — so RED could not
     distinguish them. Closed by mutation after GREEN: removing `ge=0` and neutering the
     validator failed 3 tests, including both negatives. Without that check the rule would have
     been unprotected and the suite would have looked fine.

  3. **No pairing rule against `run_cost_status`, deliberately** (spec §3.1). A `partial` run has
     a saved-cost sum by definition, so refusing `partial` beside a null here looks correct — and
     would 422 the SDK released today, because `OME-1252` ships the status without this field.
     That is the `#841` P1-1 deadlock exactly. Pinned by
     `test_a_partial_run_without_a_saved_cost_is_still_accepted`, which is the test most likely
     to be deleted by someone tidying later; its docstring says so.

  4. **The replay gates on its OWN null**, not on the amount. The `#841` P1-2 trap does not apply:
     that bug existed because `0014` left the status null on rows holding published money, making
     the status the wrong sentinel. Here the field IS the amount and no row has ever held one, so
     null is unambiguous and nothing published can be overwritten.

  5. **Two gate failures, both mine, both fixed not suppressed** — a 103-character line, and a
     test helper typed `str` where the schema wants the `RunCostStatus` literal.
