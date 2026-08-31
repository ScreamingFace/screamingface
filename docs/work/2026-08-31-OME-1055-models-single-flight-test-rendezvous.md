---
ticket: OME-1055
stack: aigateway
status: in_progress   # planned | in_progress | done | blocked
started: 2026-08-31
finished:
---

# OME-1055 — Make the /v1/models single-flight concurrency test deterministic

## Intent

`test_concurrent_callers_share_one_upstream_fetch_chain_and_all_get_200` fails
intermittently in CI on Python 3.12 with `assert 4 == 6`, which intermittently blocks every
aigateway PR (first observed on PR #782 / OME-1044, whose diff touches none of the code
under test). The failing assertion is the test's own self-check that six callers overlapped,
not the product invariant — `assert http.dialed == [LIVE_MODELS_URL]` passes on every run.
The overlap is currently arranged by a fixed `await asyncio.sleep(0.2)` racing six thread
startups; on a loaded runner two threads land late, get served by the completed refresh, and
never overlap. This unit replaces the timed window with an explicit rendezvous so the overlap
is a fact rather than a race, keeping both existing assertions intact.

Introduced by `cc9deb4a` / PR #739 (OME-972), merged 2026-08-27; latent through ~16 runs.

## Planned changes

- `apps/aigateway/tests/unit/core/test_models_route_live_catalog.py` — MODIFY
  `test_concurrent_callers_share_one_upstream_fetch_chain_and_all_get_200` only:
  - add a module-level `_RENDEZVOUS_TIMEOUT_S` constant
  - add an `asyncio.Event` the counting wrapper sets once `depth["now"]` reaches `callers`
  - `_SlowClient.get` awaits that event under `asyncio.wait_for` instead of
    `asyncio.sleep(0.2)`; a timeout records a flag rather than raising inside the app stack
  - add an assertion on that flag, ahead of the peak assertion, so a genuine failure to
    overlap reports itself instead of surfacing as `4 == 6`
  - `WHY:` anchor recording why a rendezvous replaces a timed fetch

No production code changes. No other test touched.

## Test plan

This unit's deliverable IS a test change, so the RED/GREEN evidence is behavioural rather
than a new test file:

- **RED (reproduce the defect's mechanism):** force the failure deterministically by making
  the rendezvous unreachable — set the barrier target above the caller count — and confirm
  the new timeout assertion fires with its diagnostic message rather than `assert N == 6`.
  This proves the new guard detects a real overlap failure instead of masking it.
- **GREEN:** the test passes with the rendezvous in place.
- **Determinism:** run the target test in a loop (>=25 iterations) and the whole test file,
  with coverage on, and additionally under CPU restriction (`taskset -c 0,1`) — the
  condition the fixed sleep was sensitive to.
- **No weakening:** both original assertions (`http.dialed == [LIVE_MODELS_URL]` and
  `depth["peak"] == callers`) remain present and unmodified in meaning.
- **Full suite:** the whole aigateway suite stays green (the test shares the app fixture with
  4107 other tests).

## Acceptance

- The fake upstream fetch completes only after all `callers` callers have entered the catalog.
- Both original assertions still asserted; neither relaxed.
- A failure to rendezvous fails loudly with a diagnostic, bounded by a timeout — never hangs.
- Target test green repeatedly (>=25 consecutive runs) under coverage, including pinned CPUs.
- `uv run .claude/scripts/run_gates.py aigateway --skip-append-only` all green.
- CI green on both 3.12 and 3.13.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** <vs planned>
- **Commits:** <sha — message>
- **Gates:** <run_gates.py result line / counts>
- **Deviations:** <anything that differed from the plan, or "none">
