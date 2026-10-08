---
ticket: OME-1458
stack: aigateway
status: done
started: 2026-10-08
finished: 2026-10-08
---

# attempts-gateway-cache — each Attempt of a Case gets its own global cache entry (PR 4 of 7)

## Intent

The AI gateway side of OME-1458 (plan `docs/plan/2026-10-08-OME-1458-attempts-per-case.md`,
PR 4). The global exact-request cache would serve Attempt 2 of a Case the reply stored for
Attempt 1, because the two requests are identical. The Engine sends Attempt 2..N with
`cache: {"attempt": i}`; the gateway keys the reply on the request plus that number, so
Attempt 2 is asked afresh once and replayed on every rerun (spec rules 2 and 3).

## Planned changes

- `apps/aigateway/src/aigateway/core/request_cache/global_controls.py` — the grammar accepts
  `attempt` (an integer of at least 2).
- `.../global_keys.py` — `GlobalChatCacheKey.attempt`, rendered only when set;
  `build_attempt_cache_key`.
- `.../global_plan.py` — route an Attempt-numbered request to that builder.
- `apps/aigateway/tests/unit/test_global_cache_attempts.py` — new.
- `apps/aigateway/DEPLOYMENT.md`, `apps/aigateway/charts/aigateway/README.md` — one line each.

## Test plan

- Grammar: `{"attempt": 2}` participates and is carried; absent carries None; 1, 0, -2, "2",
  2.0, True, None are malformed; combines with an opt-out; the control object is still stripped.
- Key: the bare digest is the pinned one; Attempt 2's digest differs; no `attempt` member when
  unset.
- Route: Attempt 2 is not served Attempt 1's stored reply (acceptance 4); a rerun serves both
  Attempts from cache with zero dispatches (acceptance 5); the provider never sees the control.

## Acceptance

- Spec acceptance 4 and 5, pinned at the gateway.
- `test_chat_global_cache_key_parity.py` and every existing cache test pass unmodified.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned.
- **Commits:** see the PR.
- **Gates:** `ruff check`, `ruff format --check`, `pyright` (0 errors); full unit suite
  `pytest -m "not live and not needs_postgres"` green (counts in the PR).
- **Deviations:** the plan put an `attempt` keyword on `build_global_cache_key`. That builder's
  parameter set is pinned by `test_the_builder_accepts_no_identity_profile_or_credential_input`
  (no caller identity may enter the key), so an Attempt-numbered request goes through a second
  builder, `build_attempt_cache_key`, which reuses the same DTO and adds the number. Every
  ordinary request still goes through the unchanged builder, and no prior test changed.
