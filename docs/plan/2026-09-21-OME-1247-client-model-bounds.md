# OME-1247 — Plan

Spec: `docs/spec/2026-09-21-OME-1247-client-model-bounds.md`
Ledger: `docs/work/2026-09-21-OME-1247-client-model-bounds.md`
Lands on: the `OME-1180-send-models` branch (PR `#923`), per the owner decision recorded in the ledger.

## Step 1 — RED

Append to `packages/screamingface/tests/test_leaderboards.py`. Six cases, each pinning one
edge the spec names:

1. 32 distinct routes builds a payload; 33 raises `ValueError`
2. a 255-character route builds a payload; 256 raises
3. route count and per-route length all legal, serialization over 4096 bytes → raises
4. the byte cap is measured with compact separators and `ensure_ascii=False` — asserted by
   constructing a payload that passes under the board's spelling and fails under the default
   one, so a future edit to the serialization is caught rather than silently diverging
5. each message names the offending value, not just the limit
6. a candidate within every cap produces the payload unchanged from today

Run; confirm each fails for the stated reason and not an import error.

## Step 2 — GREEN

`packages/screamingface/src/screamingface/_scoreboard/leaderboards.py`:

- three constants beside `_MAX_AUTHORS` / `_MAX_AUTHOR_LENGTH` at lines 39-40 — the same kind
  of cap for the same kind of reason, so they belong in the same block, with a comment naming
  the board-side source of truth
- `_submission_models(models) -> list[str]`, mirroring `_submission_authors`: count, per-route
  length, then serialized size, each raising `ValueError` naming the cap and the actual value
- `_submission()` calls it for the `models` key instead of `list(candidate_result.models)`

`ran_with_providers` still derives from `candidate_result.models` unchanged — it is a different
field with no cap, and altering it would rewrite recipe identity on the board.

## Step 3 — REFACTOR / COVERAGE

Check the three raises and the pass-through are all exercised; the SDK gate is 95% coverage, so
an unhit branch fails the build rather than slipping through.

## Step 4 — GATES

`uv sync --all-extras` first (the suite fails collection on missing `ipywidgets` otherwise),
then `uv run .claude/scripts/run_gates.py screamingface --base origin/main`.

Expect the append-only check to flag `tests/test_leaderboards.py` — this branch already carries
the owner-approved exception from `OME-1180` for
`test_the_submission_payload_gains_only_the_cost_key`. That exception covers a single added
string. **If this unit needs to touch that test again, stop and ask** rather than widening a
recorded exception silently.

## Step 5 — LEDGER, COMMIT, PR

Fill the ledger Outcome, commit with `Refs: OME-1247`, push, and update `#923`'s body to
describe both changes. The PR carries two tickets now; say so plainly rather than leaving the
extra scope for a reviewer to discover.

## Risks

- **Re-review.** `#923` is approved at its current head; this invalidates that. Expected and accepted.
- **The byte cap is the subtle one.** Route count and length are obvious; serialization is where
  the two ends can silently diverge. Step 1 case 4 exists specifically for that.
