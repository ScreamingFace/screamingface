# OME-1325 — Plan

Spec: `docs/spec/2026-09-24-OME-1325-store-cache-saved-cost.md`
Ledger: `docs/work/2026-09-24-OME-1325-store-cache-saved-cost.md`
Branch: `OME-1325-store-cache-saved-cost`, from `origin/main` at `b44fa781`.

**Phase 1 only** — store and persist. The frontier and the read path are phase 2, gated on
`OME-1287`.

## Step 1 — RED

New file `apps/scoreboard/tests/unit/scores/test_cache_saved_cost.py`, so nothing existing is
touched and the append-only check stays clean:

1. a submission carrying the field stores it
2. omitting it stores `null` — not `0`
3. an explicit `0` stores `0` and stays distinguishable from null (§4)
4. a negative amount is refused
5. a non-finite amount is refused
6. `999999.999999` is accepted; seven integer digits are refused (§3 bounds)
7. **`run_cost_status="partial"` with no saved cost is ACCEPTED** — §3.1, the case that would
   422 the SDK released today
8. a replay fills the field on a row that lacks it
9. a replay **cannot replace** a populated value
10. a replay filling this field does not disturb `run_cost_usd` or `run_cost_status`

Run; confirm each fails for the stated reason.

## Step 2 — GREEN, in dependency order

1. `scores/models/score.py` — `cache_saved_cost_usd = fields.DecimalField(max_digits=12,
   decimal_places=6, null=True)`, with the NULL-is-not-zero invariant recorded beside it
2. `scores/migrations/0015_score_cache_saved_cost.py` — `AddField`, `depends_on 0014`, no
   backfill, reason recorded as `0014` does
3. `scores/schemas.py` — `cache_saved_cost_usd` on `ScoreSubmission`, reusing `_validate_run_cost`
   through a `field_validator`; the `RunCostUsd` annotated type for the wire form
4. `scores/schemas.py` — the same field on `ScoreSchema` with `exclude_if=lambda v: v is None`
5. `scores/store.py` — the write path persists it; `_replay_updates` gains the fill-only block

## Step 3 — MIGRATION VERIFICATION

`0014`'s ledger records that nothing in CI or the gate runner runs migrations, so `0015` is
applied by hand against a fresh SQLite and the column confirmed present and nullable. A schema
change without a verified migration is an incomplete iteration (sdlc-python S1).

## Step 4 — EXPORT DIGEST

The acceptance bullet that cannot be assumed: **a row without the field must export byte-identical
to before.** Verify by constructing a row, serializing `ScoreSchema`, and asserting the key is
absent — not merely null. `exclude_if` is what makes this true and the `OME-1181` Q2 trap is what
makes it matter.

## Step 5 — GATES

`uv run .claude/scripts/run_gates.py scoreboard --base origin/main`

Expect the append-only check to **pass**: every test is a new file. If it flags anything, stop and
ask — that would mean a prior test moved, which this unit has no reason to do.

## Step 6 — LEDGER, COMMIT, PR

Fill the Outcome, commit with `Refs: OME-1325`, push, open the PR stating that phase 2 stays open
on the ticket and why.

## Risks

- **§3.1 is the subtle one.** A pairing validator looks correct and would deadlock the rollout.
  Test 7 pins its absence, and it is the test most likely to be deleted by someone tidying later.
- **The migration is unverified by CI** by design. Hand-verify or it is not verified.
- **`exclude_if` is easy to omit** and its absence is invisible until a purge fails to authorise.
- **Scope creep toward the frontier.** `pareto.py` is one line away and must not be touched.
