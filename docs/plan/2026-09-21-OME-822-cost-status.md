# OME-822 — Plan

Spec: `docs/spec/2026-09-21-OME-822-cost-status.md`
Ledger: `docs/work/2026-09-21-OME-822-cost-status.md`
Branch: `OME-822-require-run-cost` (PR `#841`), rebased onto `origin/main` 2026-09-21.

## Step 0 — the approved fixture edit, first

`tests/unit/scores/test_model_identities.py:66` gains `run_cost_usd` in the local `_submission()`
helper. Owner-approved exception. Done before anything else so the 18 unrelated failures stop
masking real ones for the rest of the unit.

That helper sends no status either, so it gains both — which makes it the first exercise of the
new contract.

## Step 1 — RED

Append to `tests/unit/scores/test_schemas.py` and `tests/unit/scores/test_store.py`:

1. a submission with neither amount nor status is rejected with a field error
2. `complete` without an amount is rejected — the pairing, not just presence
3. an amount with `partial` is rejected — the same pairing from the other side
4. `complete` + amount round-trips; the stored amount is the submitted one
5. `partial` stores `null` for the amount **and persists the status**
6. `unavailable` does the same with its own member
7. a stored unpriced row is absent from `compute_pareto_frontier_ids` — asserted through the
   function, never by reading the `is not None` guard
8. a replay fills amount and status **together**, never one without the other

Run; confirm each fails for the stated reason.

## Step 2 — GREEN

`scores/schemas.py`

- `RunCostStatus = Literal["complete", "partial", "unavailable"]`
- `run_cost_status: RunCostStatus` required on `ScoreSubmission`
- `run_cost_status: RunCostStatus | None` on `ScoreSchema`, with `exclude_if` so a legacy row
  emits nothing — the `OME-1181` Q2 lesson: `ScoreSchema` feeds the byte-exact JSONL export whose
  digest authorises a private-board purge, and a new always-present key changes every historical
  digest
- a `model_validator` pinning §2.1: `complete` ⇔ an amount is present

`scores/models/score.py` — `run_cost_status = fields.CharField(max_length=16, null=True)`

`scores/migrations/0014_score_run_cost_status.py` — depends on `0013_score_models`

`scores/store.py` — store `null` for the amount when the status is not `complete`; carry the
status through `_submission_to_kwargs` and `_score_to_schema`; extend `_replay_updates` so amount
and status move as a pair

`routes/scores.py` — add the unpriced member to `ScoreRankingNotice.code`

**Not touched:** `pareto.py`, `portal/`. Spec §3.

## Step 3 — COVERAGE

Scoreboard gate is 80%. The three status members, both pairing rejections, and the replay pair
must each be hit.

## Step 4 — GATES

`uv run .claude/scripts/run_gates.py scoreboard --base origin/main`

Expect the append-only check to flag `test_model_identities.py` — that is Step 0's approved
exception and **nothing else**. Verify against the diff before using `--skip-append-only`; if a
second file appears, stop and ask.

Migration `0014` gets applied by hand against a fresh SQLite, as `0013` did — nothing in CI or
the gate runner runs migrations.

## Step 5 — LEDGER, COMMIT, PR

Fill the Outcome, commit with `Refs: OME-822`, push, update `#841`'s body. The PR body predates
this contract entirely and describes only the required-field change.

Also correct `OME-822`'s Linear body — its D1 bullet still names the gateway's `DirectCostStatus`
vocabulary, superseded by D4.

## Risks

- **`ScoreSchema` is public.** `exclude_if` is not optional; the export digest is the trap.
- **Migration `0014` is unverified by CI** by design. Hand-verify.
- **`#841`'s approval is void** — it predates both the bounds work and this. Expected.
