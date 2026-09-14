---
ticket: OME-1199
stack: screamingface-engine
status: done
started: 2026-09-14
finished: 2026-09-14
---

# OME-1199 — Pin Engine worker profile-variable inheritance and Local connection ambiguity

## Intent

Stage 0 (Engine half) of the adapter-first convergence (`OME-1138`). The selector sunset (Stage D)
will reject present profile selectors; the Engine today carries the selector through the
environment into workers differently for the queued and the in-process runner, and the Local
listing has an ambiguity rule that the gateway-side availability listing (A3/A4) must not silently
change. Pin both. No change under `apps/screamingface-engine/src`.

## Planned changes

- `apps/screamingface-engine/tests/unit/test_profile_env_characterisation.py` (new; tests only).

## Test plan

- Worker `_child_env` (`worker/supervisor.py:729-744`) inherits an ambient `AIGATEWAY_PROFILE` from
  the supervisor process environment; a message-carried profile replaces it.
- The in-process runner (`adapters/inprocess.py:179-185`) removes `AIGATEWAY_PROFILE` when the
  request carries none; a requested profile replaces the ambient one.
- Local connections listing (`connections/aigateway.py`) refuses with 409 when more than one
  non-revoked managed row of any status exists.

## Acceptance

- All new tests pass at HEAD 17048f5d with `apps/screamingface-engine/src` untouched; existing tests
  unedited.
- Engine gates green (ruff, format, pyright, layering, full suite with coverage).

## Outcome

- **Actual files:** `apps/screamingface-engine/tests/unit/test_profile_env_characterisation.py`
  (new, 10 tests, 298 lines). Nothing under `apps/screamingface-engine/src` changed; no existing
  test edited (append-only check vs 17048f5d green).
- **What is pinned (all green at HEAD 17048f5d):**
  1. Through the real `Worker` claim path with a capturing spawn: a child spawned for a message
     without a profile inherits the ambient `AIGATEWAY_PROFILE`; a message-carried profile wins.
  2. `InProcessJobRunner` with an ambient profile in `base_env`: a request without a profile gets
     NO `AIGATEWAY_PROFILE`; a requested profile replaces the ambient one.
  3. `AigatewayConnections.list` refuses with `ConnectionConflict` for one active plus one
     managed row of status pending/expired/error/revoked, and for two non-active managed rows;
     a single non-active managed row is selected, not refused. The adapter is status-blind; the
     gateway's default listing is what hides revoked rows.
- **Commit:** `test(engine): characterize profile selector behavior` (this commit).
- **Gates:** `uv run .claude/scripts/run_gates.py screamingface-engine --base 17048f5d` →
  ALL GATES GREEN (append-only test check, ruff check, ruff format --check, pyright,
  check_layering, pytest with coverage ≥80%). Counts (separate `uv run pytest --cov -q` run,
  same tree): 2717 passed / 9 skipped, total coverage 93%. Re-run green on 2026-09-14 as the
  A1 consumer gate (`OME-1200`) with no Engine change.
- **Deviations:** source paths in the plan (`runner/supervisor.py`, `inprocess.py`) corrected to
  `worker/supervisor.py` and `adapters/inprocess.py`. The 409 rule is pinned at the adapter
  (port exception) rather than through the REST layer; the status mapping is owned by
  `connections/upstream_errors.py` and already tested there.
