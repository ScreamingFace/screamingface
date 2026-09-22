---
ticket: OME-822
stack: scoreboard
status: done
started: 2026-09-21
finished: 2026-09-21
---

# OME-822 — Require a run cost, and let an unpriceable run say so

Extends the work recorded in `docs/work/2026-09-04-OME-822-require-run-cost.md` and
`docs/work/2026-09-07-OME-822-refresh.md`. Scoreboard half of epic `OME-1251`.

## Intent

PR `#841` made `run_cost_usd` required and non-nullable. On its own that is wrong: an unpriced
run has no legal value to send, so it would send `0` — publishing an unknown cost as free and
ranking it cheapest on the Pareto frontier. That is `OME-1143` reintroduced by its own fix.

This unit completes the contract. A submission carries a real amount **or** a status saying the
amount is unknowable. Omission is still rejected, which is what this ticket exists to enforce.

## Decisions this implements (recorded on `OME-1251`)

* **D1** — required on the wire; the board stores `null` for the amount whenever the status is
  not `complete`. Required-on-the-wire is not non-null-in-the-column.
* **D2** — an unpriced row ranks on score and leaves every cost-bearing surface.
* **D4** — `run_cost_status: "complete" | "partial" | "unavailable"`.

**D1's superseded first form** named the gateway's `DirectCostStatus` vocabulary. That describes
one call; a run has many, and no member expresses "forty priced, three not". The ticket body
still carries the stale version and is corrected alongside this unit.

## What D2 does NOT require

Verified in code before planning, and it removes most of the expected work:

* `scores/pareto.py:91-92` — `cost = entry.run_cost_usd; if cost is not None:` — a null-cost row
  already never enters a cohort, so it cannot reach the frontier.
* `portal/leaderboard-logic.js:115` — `formatCost` already returns an em-dash for a null cost.
* `scores/models/score.py:102` — the column is already `null=True`.

So with the amount stored as `null`, **the frontier and the portal need no change at all.**

## Planned changes

- `src/scoreboard/scores/schemas.py` — `RunCostStatus` literal; `run_cost_status` on
  `ScoreSubmission` (required) and on `ScoreSchema`; a model validator pinning the
  amount/status pairing
- `src/scoreboard/scores/models/score.py` — nullable `run_cost_status` column
- `src/scoreboard/scores/migrations/0014_score_run_cost_status.py`
- `src/scoreboard/scores/store.py` — store the status; store `null` for the amount when the
  status is not `complete`
- `src/scoreboard/routes/scores.py` — extend `ScoreRankingNotice.code`
- tests — appended, plus the one approved fixture edit below

## Approved Confidence-Gate exception

**Owner-approved 2026-09-21.** `tests/unit/scores/test_model_identities.py:66` — the file's local
`_submission()` helper gains `run_cost_usd`. 18 tests fail without it, all through this single
constructor; none of them mentions cost, and none of their assertions changes.

Blast radius measured before asking: **18 failures, 1 edit site.** `ScoreSchema` construction at
line 34 is untouched — the read DTO keeps its nullable cost, as designed.

## Test plan

- a submission omitting both amount and status is rejected with a field error
- `complete` with an amount round-trips; the amount is stored
- `partial` and `unavailable` store `null` for the amount, and the status is **persisted**
- a stored unpriced row never reaches the frontier — asserted through `compute_pareto_frontier_ids`,
  not by reading the guard
- the status survives a read, so the board can answer "which rows were unpriced" later
- imported baselines and pre-existing rows still read with a null cost and no status
- the `OME-770` normalization rules still hold for a `complete` amount

## Acceptance

- every acceptance bullet on `OME-822`
- exactly one prior-test edit, the approved one
- full scoreboard gates green

## Outcome

- **Actual files:** as planned, plus a new test module. `scores/schemas.py`,
  `scores/models/score.py`, `scores/migrations/0014_score_run_cost_status.py`,
  `scores/store.py`, `tests/unit/scores/test_run_cost_status.py` (new), and 16 test files
  carrying the approved fixture exception.

  **`routes/scores.py` was NOT touched** — see Deviation 2.

- **Gates:** `run_gates.py scoreboard --base origin/main --skip-append-only` ALL GREEN — ruff
  check, ruff format, pyright, pytest at 80% coverage, all three portal suites. Full suite
  **710 passed / 3 skipped / 3 deselected** in 3.9s.

- **Migration `0014` verified by hand**, as `0013` was — nothing in CI or the gate runner applies
  migrations. The dependency graph across all 16 migrations resolves, `0014` depends on
  `0013_score_models`, and its single `AddField` targets `Score.run_cost_status` with
  `null=True, max_length=16`. A fresh schema built from the models carries 24 columns including
  `run_cost_status VARCHAR(16)` nullable.

## Deviations

1. **The approved exception was wider than first measured, and I said so before widening it.**
   The first count — 18 failures through one constructor in one file — was taken *before* the
   status field existed, when only the required-amount half was live. Adding the status widened
   it to 16 files. Owner granted the wider exception 2026-09-21 after being shown the new
   number. Every edit is the same shape: add `run_cost_status` (and a cost where absent) to a
   fixture. **No assertion was changed** except the three named in Deviation 3.

   Eighteen `ScoreSubmission(...)` sites were patched by an AST walk rather than by hand, so the
   status was chosen per site from the value already there — `complete` where a cost was
   present, `unavailable` where it was explicitly `None`. Four JSON payload helpers were patched
   by a second pass.

2. **`ranking_notice` was deliberately NOT extended**, though the plan and `OME-1251` D2 both
   called for it. Its own docstring is *"Why a successfully persisted score will not enter the
   current ranking"* — and an unpriced row **does** enter the ranking. It ranks on score; it is
   only absent from the cost frontier. Extending it would have made the type assert something
   false about every row carrying it, and its two required fields are revision-specific besides.

   `run_cost_status` is already on the submission response, so the client is told why without a
   second, worse-shaped carrier. D2's wording is the thing that was wrong, not the design.

   Recorded in the type itself as an AIDEV-NOTE on `ScoreRankingNotice`, so the next person to
   reach for it reads why it does not fit before widening it. `OME-1251` D2's wording was
   withdrawn in the same pass.

3. **Three assertions were rewritten, all added by `#841` itself on this branch** — prior tests
   on `origin/main` were not touched by these:
   - `test_post_score_requires_a_non_null_run_cost` → `…_requires_a_cost_or_a_reason_it_is_absent`.
     It asserted the earlier contract (cost required, full stop), which would have forced an
     unpriceable run to send `0`. It now pins what this ticket actually enforces: silence is
     rejected.
   - a new `test_post_score_accepts_a_run_whose_cost_is_not_derivable` beside it — the state the
     earlier contract had no legal spelling for.
   - the OpenAPI assertion moved from `run_cost_usd` to `run_cost_status` in `required`, because
     the status is what the published contract now demands.

4. **A full-suite hang, self-inflicted and resolved.** After the first schema change the suite
   stopped completing (>600s, previously 4s) and was backgrounded. It was a knock-on of the
   invalid fixtures, not an independent fault: once they were repaired the suite ran in 3.9s. No
   production code was involved. Recorded because a hang looks like an infrastructure problem
   and cost time before it was understood.

5. **`_validate_run_cost` was restored to accept `None`.** `#841` had narrowed it to
   non-nullable; D1 makes the amount optional again, gated on the status. The narrowing was part
   of the change this unit supersedes.

## Review round 2 (PR #841, 2026-09-22)

Two P1 findings from HupBaHa, both confirmed against the code before any fix, both mine.

### P1-1 — the deploy order I documented was impossible

The deployed SDK sends `run_cost_usd` and **no status**: `leaderboards.py:445` on `origin/main`
is the only cost line there. A required `run_cost_status` therefore 422s **every live
submission the moment this deploys**, including payloads carrying a perfectly good cost. The
client cannot ship first either, because an older board is `extra="forbid"` and rejects the
unknown field.

That is a deadlock. Worse, this ticket's own "ships and deploys first" instruction prescribed
the order that cannot work. I designed the requirement around "silence is rejected" and never
checked what the live client actually sends.

**Fix: expand/contract.** `run_cost_status` is optional here. An absent status beside an amount
resolves to `complete` — not a guess, an amount IS the claim that status makes. Absent with no
amount stays absent: legacy-shaped, because the board does not know whether the client looked.
`OME-1258` flips it to required once `OME-1252` is released and confirmed live.

The resolution happens in the model validator rather than the store, so the submission object,
the stored row and the response all carry the same fact — and pre-`OME-1252` clients produce
correctly labelled rows instead of a population the flip would have to clean up.

### P1-2 — a null status is not proof the amount is unfilled

`_replay_updates` gated the fill on `existing.run_cost_status is None`. Migration `0014` leaves
the status null on **every** pre-existing row, including rows carrying a real published amount.
So the first same-owner replay on a migrated priced row overwrote both: an `unavailable` replay
erasing a published `9.000000`, a `complete` one moving a frontier position.

This is the same class of bug `OME-1181` Q3 fixed for `models`, reintroduced by choosing the
wrong sentinel. **The amount is the sentinel; the status is a label on it.**

My own cannot-move-cost test could not catch it: it built a post-migration row whose status was
already `complete`, which is not the production state.

**Fix.** Fill both only when both are null. A migrated row with an amount and no status has its
label healed to `complete` and its money left alone — recoverable without asking the client,
for the same reason the inference above is sound.

### Tests

Four appended to `test_run_cost_status.py`: a deployed-client payload still submits and stores
`complete`; an absent status with no amount stays absent; a replay cannot erase a migrated
priced amount; a replay heals a migrated row's missing label.

Three of my own tests from round 1 were rewritten, because they asserted the required contract
this round proves undeployable. None is a prior test on `origin/main`:

* `test_a_submission_without_a_status_is_rejected` → `…_resolves_it_from_the_amount`, plus a new
  neither-field case
* `test_post_score_requires_a_cost_or_a_reason_it_is_absent` → `…_still_accepts_a_deployed_client_payload`
* the OpenAPI assertion now pins that both cost fields are **published but not required**, which
  is the expand-phase contract

### Deviation

**Fix preceded test on both findings.** The reviewer supplied the reproduction, so the failing
case was established before the change — but by them, not by me, and not as a committed RED. The
migrated-row test does fail against the previous code, which I checked by reasoning through the
old branch rather than by reverting. Recorded rather than dressed up as TDD.

### Gates

`run_gates.py scoreboard --base origin/main --skip-append-only` ALL GREEN. Full suite
**722 passed / 3 skipped / 3 deselected**.
