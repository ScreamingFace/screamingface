---
ticket: OME-1389   # existing bug issue; no new issue is filed
stack: aigateway
status: in_progress
started: 2026-10-08
finished:
---

# ome-1389-refusal-log — log a migrated pair's access refusal and pin the ticket's path

## Intent

OME-1389 reported a migrated provider slot listed as `connected` while every chat call was refused
with `401 auth_required`. On current main the listing part is already fixed: the availability
overlay reads the effective Connection (#1029) and an OpenRouter 401 records the operational
`needs_reauth` outcome (#1240, OME-1250). A run of the ticket's exact path on main confirmed it.
Two things remain: no test walks the ticket's path end to end on a slot migrated FROM a Profile
(provider 401 → listing), and a refusal that never reaches the provider writes no log line, so the
cause took a database query to find. This unit adds that end-to-end test and one structured WARNING
when a migrated pair's resolve is refused because its credential is not usable (missing, pending,
or needing re-entry), carrying identifiers only.

## Planned changes

- `apps/aigateway/src/aigateway/core/provider_access/connection_backed.py` — log a refused resolve
  on a migrated pair (provider, account, effective Connection id and status, refusal kind, policy).
- `apps/aigateway/tests/unit/openrouter/test_migrated_rejected_key_availability.py` (new) — the
  ticket's path on a Profile-migrated OpenRouter slot, a pre-#1240 errored row, and the refusal log.

## Test plan

- Characterization (expected to pass on main): legacy api-key Profile → `profile_only` migration →
  provider 401 → Connection still `active`, listing `needs_reauth`, the next chat refused without a
  provider call; a row already in `status=error` lists `error` and is refused.
- RED: a refused resolve on a migrated pair writes exactly one WARNING with provider, account,
  Connection id, status, refusal kind and policy — for `needs_reauth`, an errored row, a pending row
  and a missing Connection; an allowed resolve writes none.
- INVARIANT: the record carries no key, no `credential_locator`, no provider error text.

## Acceptance

- The ticket's path is pinned by a test: a Profile-migrated slot whose key was rejected is never
  listed `connected`.
- A refusal from a non-usable effective Connection writes one structured log line with no secret.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned — `core/provider_access/connection_backed.py` (a refused migrated
  resolve → one WARNING naming the refused Connection) and the new
  `tests/unit/openrouter/test_migrated_rejected_key_availability.py` (9 tests).
- **Commits:** pending.
- **Gates:** `uv run .claude/scripts/run_gates.py aigateway --base origin/main` — ALL GATES GREEN
  (append-only, ruff check, ruff format, pyright, no-enterprise, pytest with coverage ≥ 80%); full
  suite 5348 passed, 97 skipped (after the review fixes).
- **RED:** the two ticket-path characterization tests and the allowed-resolve test passed on main
  as expected (the listing fix is #1029 + #1240); all five refusal-log tests failed for the
  missing record. Mutation checks: no log call (5 fail), status dropped (3), the refusal's text in
  the record (4), `TargetPending` not logged (1), the Connection's `error_message` in the record
  (4), the matched row ignored on the no-document path (1).
- **Review:** no blockers. Fixed: (1) on the no-document path the record named the pair's
  effective Connection although the refusal was for the row matched there (an errored effective
  Connection plus another active one whose blob is gone) — each path now logs the row it refused,
  pinned by a test that failed first; this also drops the extra effective-Connection read the
  first version added to that path. (2) The parametrized refusal test now pins the HTTP status per
  case (401 / 409 / 404). Left as is: model admission resolves with the default `dispatch` policy,
  so its refusals log `policy=dispatch` like chat's (admission runs only for models not yet
  admitted; low volume); and a client that keeps calling a refused slot writes one WARNING per
  call, one per `401` already in the access log, with no rate limit.
- **Deviations:**
  - The ticket's path was run on main before any change (a scratch run on `21132c8d0`): an
    OpenRouter 401 on a Profile-migrated slot keeps the Connection `active`, records the operational
    `needs_reauth` outcome and lists `needs_reauth`; a row errored by the pre-#1240 path lists
    `error`. Part 1 of the ticket therefore needed no code change, only the end-to-end test.
  - Only the three "credential not usable" refusals are logged; selector and store refusals already
    name their cause in the response.
  - `needs_reauth` exists only for OpenRouter (the one plugin with an operational classifier);
    another api-key provider's 401 still lists `error`. Rows errored before #1240 stay `error`
    until the key is entered again (no data migration). Both are owner questions, not this unit.
