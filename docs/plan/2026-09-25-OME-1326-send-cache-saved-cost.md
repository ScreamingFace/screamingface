# OME-1326 — Plan

Spec: `docs/spec/2026-09-25-OME-1326-send-cache-saved-cost.md`
Ledger: `docs/work/2026-09-25-OME-1326-send-cache-saved-cost.md`
Branch: `OME-1326-send-cache-saved-cost`, from `origin/main` at `eaae03b5`.

## Step 1 — RED

New file `packages/screamingface/tests/test_cache_saved_cost_submission.py`:

1. a result carrying a saving sends it as a decimal string
2. a result with no saving omits the key entirely (not `null`)
3. the archive-matched figure never appears in the payload, and nothing sums the two
4. no result the evaluation path can build pairs `unavailable` with a saving
5. `to_dict()` carries the saving, and carries it as null when absent
6. the full path: an `_RunOutcome` with a reported saving produces a `CandidateResult` and a payload
   carrying it

Run; confirm each fails for the stated reason. **Mutation-check after GREEN**, because this is the
pattern that failed twice on this epic: swap the reported and archive sums in the pass-through and
confirm a test fails.

## Step 2 — GREEN

1. `report.py` — `cache_saved_cost_usd: Decimal | None = None` on `CandidateResult`, validated as
   finite and non-negative, emitted by `to_dict()`
2. `_evaluation/results.py` — `cache_saved_cost_usd=outcome.cache_saved_cost_usd`
3. `_scoreboard/leaderboards.py` — add the key only when not null, via the existing `_cost_text`

## Step 3 — PUBLIC SURFACE

Regenerate the snapshot per its documented procedure. **Expected diff: one field on
`CandidateResult` plus its `__init__` signature.** Anything more means the change leaked.

## Step 4 — GATES

`uv run .claude/scripts/run_gates.py screamingface --base origin/main`

Expect the append-only check to flag **only** `tests/public_surface_snapshot.json`. That needs an
owner exception, as it did for `OME-1252`. `tests/test_leaderboards.py` should NOT be flagged: §3
keeps its exact key set unchanged. If it is flagged, stop.

## Step 5 — COMMIT, PUSH, PR, DO NOT MERGE

Open the PR with the merge gate stated at the top: **not before PR #1055 is deployed on dev and
confirmed live.**

## Risks

- **Merging early** is the one that matters. It 422s cached runs as soon as a post build ships.
- **#1055's contract can still change in review.** §4 is pinned to `0357d7bd`.
- **The snapshot exception** needs the owner's approval before gates can pass.
