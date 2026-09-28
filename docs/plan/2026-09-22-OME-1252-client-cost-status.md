# OME-1252 — Plan

Spec: `docs/spec/2026-09-22-OME-1252-client-cost-status.md`
Ledger: `docs/work/2026-09-22-OME-1252-client-cost-status.md`
Branch: `OME-1252-client-cost-status`, from `origin/main` at `51e908d8`.

## Step 1 — RED

New file `packages/screamingface/tests/test_run_cost_status.py`, so nothing existing is touched:

1. a span carrying both saved-cost fields round-trips through `_span()`
2. two spans' `reported` amounts sum; `archive` amounts sum separately
3. no combined total is produced anywhere — structural, mirroring the engine's own guard
4. a priced run derives `complete`; the payload carries the amount as a decimal string
5. an unpriced run with a reported sum derives `partial`; the payload carries **no** amount
6. an unpriced run with only an archive sum derives `unavailable` (§3.1)
7. an unpriced run with nothing derives `unavailable`
8. a run with no cache activity is unchanged from today

## Step 2 — GREEN, in dependency order

1. `events.py` — two `Decimal | None` fields on `Span`, validated non-negative and finite like
   every other money field
2. `_engine/contract.py` — parse both in `_span()`; accumulate two separate sums on `_RunState`
3. `_core/ports.py` — `RunOutcome` carries the two sums
4. `_engine/contract.py` — pass them when building the outcome
5. `report.py` — `CandidateResult.run_cost_status`
6. `_evaluation/results.py` — derive the status; the sums stop here and go no further
7. `_scoreboard/leaderboards.py` — `_submission()` sends `run_cost_status`, and omits the amount
   whenever the status is not `complete` (§3.3 — the board refuses the mismatched pair)

## Step 3 — PUBLIC SURFACE

`CandidateResult` is public, so the snapshot moves. Regenerate deliberately and read the diff —
one added field and nothing else. A snapshot that grew more than expected means step 6 leaked
the sums.

## Step 4 — GATES

`uv run .claude/scripts/run_gates.py screamingface --base origin/main`

`uv sync --all-extras` does NOT work on this package (`inspect` and `runtime` are declared
conflicting); the gate runner selects extras per gate and is unaffected.

Expect the append-only check to flag `tests/test_leaderboards.py` if `_submission`'s exact-key
guard trips. **If it does, stop and ask** — that guard exists so a deliberate payload change is
recorded, and this is the second field added to that payload.

## Step 5 — LEDGER, COMMIT, PR

Fill the Outcome, commit with `Refs: OME-1252`, push, open the PR against the deploy-order
warning: merging is safe, **releasing** is not until `OME-822` is deployed and confirmed live.

## Risks

- **`CandidateResult` is public.** One field, chosen deliberately over three. Reversing it later
  is a breaking change.
- **The payload key-set guard** will likely trip and needs an owner decision, not a quiet skip.
- **§3.1 is the subtle rule.** Archive-only evidence is `unavailable`, not `partial`. Easy to
  get backwards, and a test pins it.
