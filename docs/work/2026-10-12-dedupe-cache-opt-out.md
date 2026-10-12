---
ticket: OME-1527
stack: screamingface-engine
status: done
started: 2026-10-12
finished: 2026-10-12
---

# dedupe-cache-opt-out — one helper for a Judge call that skips the gateway cache

## Intent

The AI Gateway keeps a global exact-request cache, so a Judge re-ask that sends the same bytes
must opt out or it gets the stored, unusable reply back. Two merged PRs (#1321 for the inspect
judge redraw, #1324 for the fresh Judge retry) each built that opt-out inline: the caller's
request scope with only `CachePolicy(participate=False)` changed. This unit names it once.
No behaviour change.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/world/fresh_judge_retry.py`: add
  `without_gateway_cache(scope)`; `scope_for_this_send` calls it; export it.
- `apps/screamingface-engine/src/screamingface_engine_inspect/judge_provider.py`:
  `_gateway_cache_opt_out` calls it; drop the now-unused `replace` and `CachePolicy` imports.

## Test plan

- No new test: pure code motion. The existing opt-out tests pin both call sites:
  `tests/unit/test_fresh_judge_retry.py` (connector retry) and
  `tests/unit/inspect/test_judge_redraw.py` (inspect redraw, including the no-scope refusal).
- `tests/unit/test_layering_world.py` and `tests/unit/test_cache_policy_threading.py` for the
  layering rule and the policy-to-body threading.

## Acceptance

- Both sites call one helper; the four test files pass; ruff and extra-less pyright are clean on
  the touched files.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus this ledger.
- **Commits:** see the PR — refactor(screamingface-engine): one helper for skipping the gateway cache
- **Gates:** 56 passed across the four test files above (with the `inspect` extra); ruff check
  and format clean; pyright 0 errors in an extra-less venv. Full gate left to the pre-push hook
  and CI.
- **Deviations:** none. Home is `world/fresh_judge_retry.py`, which already owns the "re-ask a
  Judge fresh" policy and its imports, and keeps clear of `request_scope.py`, which an open PR
  edits.
