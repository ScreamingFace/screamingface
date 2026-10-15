---
ticket: OME-1618
stack: aigateway
status: in_progress   # planned | in_progress | done | blocked
started: 2026-10-14
finished:
---

# e1-successor-reauth-url — every re-auth pointer names a live Connection route

## Intent

Landing E1 of Stage E (`OME-1209`, spec `docs/spec/2026-10-14-OME-1209-retire-legacy-profiles.md`
R2, plan §3 E1). Every refusal the gateway sends for an unusable stored credential carries a
`reauth_url`; today most of them point at `/v1/auth/{provider}/profiles/{name}`, a route E3 retires.
This unit points every one of them at the Connection successor, so E3 can retire the Profile routes
without sending callers to a 410. Every pair in dev, stage and prod is `migrated` (census
2026-10-15), so the Connection the pointer names is the one chat reads.

## Planned changes

Under `apps/aigateway/src/aigateway/`:

- `core/provider_access/profile_authorize.py`: `reauth_url_for(auth_type, *, connection_id=None)`
  is the one builder: api-key with a Connection → `/v1/oauth/connections/{id}/api-key`; api-key
  without one → `/v1/oauth/connections/api-key`; OAuth, and `None` (target unknown at resolve
  time) → `/v1/oauth/connections`.
- `core/provider_access/profile_backed.py`, `connection_authority.py`, `connection_facade.py`,
  `routes/auth.py`: the five inline legacy strings go through the builder; a migrated api-key
  target names its own Connection.
- `apps/aigateway-ui/README.md`: "finds a profile" reworded to Connection terms (plan §3 E1).
- Tests: new cases first; prior tests that pin the legacy URL change their expected value only,
  through `.claude/test-change-approvals/<issue>.json`.

## Test plan

- Builder: the four shapes above; no output contains `/profiles`.
- Every resolve-time refusal (Profile error, Connection error, migrated reauth at resolve, refresh
  facade) and every authorize-time refusal (Profile, Connection, migrated) carries a successor.
- Each emitted URL resolves to a live route of the built app (`app.router` match on the path with a
  sample id), so a later retirement cannot silently strand it.
- No 401 body from the chat path contains `/profiles`.

## Acceptance

- `uv run .claude/scripts/run_gates.py aigateway --base origin/main` green.
- `git grep '/profiles/{' -- apps/aigateway/src` finds only route declarations, none in a
  `reauth_url`.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned. Source: `profile_authorize.py`, `profile_backed.py`,
  `connection_authority.py`, `connection_facade.py`, `routes/auth.py`. Tests: new
  `test_successor_reauth_url.py`; a Connection twin in `test_connection_backed_resolve_contract.py`;
  expected URL values in the prior tests listed in `.claude/test-change-approvals/OME-1618.json`.
  Docs: the accepted Stage E spec and plan (`docs/spec/` and `docs/plan/`
  `2026-10-14-OME-1209-retire-legacy-profiles.md`), the aigateway-ui README sentence, the task mirror.
- **Commits:** see the PR.
- **Gates:** ruff and pyright clean; full aigateway suite 5794 passed, 1 failed: the timing test
  `test_login.py::test_unknown_user_timing_close_to_wrong_password`, unrelated and green on rerun.
- **Deviations:** the api-key contract test is not re-run over the Connection-backed harness; its
  Connection twin asserts the exact `/v1/oauth/connections/{id}/api-key` instead, so both backings
  keep an exact assertion. The spec and plan land in this PR rather than in a separate docs PR.
