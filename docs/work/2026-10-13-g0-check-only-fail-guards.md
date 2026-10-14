---
ticket: OME-1497
stack: aigateway
status: done   # planned | in_progress | done | blocked
started: 2026-10-13
finished: 2026-10-13
---

# g0-check-only-fail-guards — error marks check the observed pair generation (G0, part 3 of 3)

## Intent

Third and last PR of the G0 writer floor (`docs/spec/2026-10-02-provider-credential-admin-contract.md`
§5.3, plan section B; part 1 merged as #1271, part 2 as #1299). §5.3: "OAuth failure and error
marks only check the observed generation where a lockable row exists and never advance it."

The inventory on `origin/main` (2026-10-13) found 14 writers that set an error state:

| Writer | Sites | Existing fence | Gap |
|---|---|---|---|
| `ProfileIndexStore.mark_authenticated_error` | `profile_authorize.mark_profile_error_fresh`, legacy refresh route | state, `auth_type` and `last_refreshed_at` of the credential version used; every key write moves `last_refreshed_at` | none |
| `mark_pending_error` (index and Connection) | legacy and native OAuth callback failures | only this flow's own `pending` document or row | none |
| `OAuthConnectionStore.mark_error` on a `none`/`quarantined` pair | `profile_authorize._refuse_unusable`, `profile_authorize.record_dispatch_failure`, `token_service`, the native refresh route | `id` + `status=active` only | an API-key Connection is re-keyed **in place**, so a stale 401 from the old key marks the new key `error` |
| `mark_error` on a `migrated` pair | `connection_authority` (2), `connection_facade._mark_failed` | the migrated paths' own fences | out of scope: §5.3 "migrated paths keep the advances they already make" |

Owner decisions (2026-10-13): check the pair generation as §5.3 states (not the blob revision); a
lost check marks nothing and the caller gets today's answer (401 reauth or the provider failure);
the already-fenced Profile and OAuth-failure paths get tests only, no second check.

## Planned changes

All under `apps/aigateway/src/aigateway/` unless noted.

- `core/provider_access/writer_floor.py`: `check_observed(observed)` — the §5.3 check for a writer
  that never advances: a marked pair is held at the observed generation (`hold_pair`); an unmarked
  observation requires the marker to be still absent (a row that appeared since is a lost check;
  an absent row has nothing to lock). `mark_error_checked(store, connection, message, observed)` —
  the check and `mark_error` in one transaction; a lost check marks nothing.
- `core/provider_access/types.py`: `CredentialTarget._observed_pair` (private, excluded from
  equality and repr, as `_backing`).
- `core/provider_access/connection_backed.py`: a non-migrated `resolve` carries the pair it read.
- `core/provider_access/profile_authorize.py`: the two Connection marks go through
  `mark_error_checked` with the target's observed pair.
- `core/oauth/token_service.py`, `routes/oauth_connections.py` (refresh): read the pair before the
  provider call and mark through `mark_error_checked`.
- Tests: `apps/aigateway/tests/unit/core/provider_access/test_writer_floor_error_marks.py` (new).

## Test plan

RED first (each fails on `origin/main`):

- Dispatch failure recorded after an ownership change on a marked `none` pair: the Connection stays
  `active`, the answer is unchanged (`None`), the generation is not advanced by the mark.
- Same on an unmarked pair whose first marker appeared after resolve.
- Rejected credential at authorize, with the ownership change inside the provider window: still
  `TargetReauthRequired`, the Connection stays `active`.
- Real scenario: a native key replacement between resolve and the dispatch-failure record keeps the
  new key `active`.
- Token endpoint and manual refresh: a refresh rejected after an ownership change answers 401 as
  today and marks nothing.
- Quarantined pair: lost check keeps state and note.

Guards against over-correction (pass on main and after):

- No interference: the mark still happens, and the generation is unchanged (check, never advance).
- A `migrated` pair keeps today's marking.

Pins for the already-fenced paths (pass on main):

- A Profile dispatch failure recorded after a legacy key PUT leaves the new key's Profile
  `authenticated`.
- A legacy OAuth callback failure after a legacy key PUT leaves the document untouched.

## Acceptance

- The four `mark_error` sites on non-migrated pairs never mark after an ownership change; marking
  without interference is unchanged; no writer here advances the generation.
- `uv run .claude/scripts/run_gates.py aigateway --base origin/main` green, plus the PostgreSQL lane
  for the touched race tests.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `tests/unit/core/provider_access/test_error_mark_inventory.py`
  (every direct `mark_error` call is the check or a migrated path; a new one fails), the
  PostgreSQL race `tests/integration/test_writer_floor_error_marks_postgres.py`, and the
  `OME-1497` mirror's ledger links.
- **Commits:** `fix(aigateway): check the pair before marking a Connection error (G0 3/3)`.
- **Gates:** `uv run .claude/scripts/run_gates.py aigateway --base origin/main` — ALL GATES GREEN
  (append-only, ruff check, ruff format, pyright, no-enterprise, pytest with coverage >= 80%);
  full suite 5553 passed, 105 skipped. RED: 7 of the 12 new tests failed on `origin/main` for the
  defect (the old key's rejection marked the replaced key `error`); the others are over-correction
  guards and pins. PostgreSQL lane (`AIGW_TEST_PG=1`, the writer-floor and lifecycle race modules):
  14 passed, including the new race.
- **Mutation checks, each caught:** no check before the mark (7 tests fail); the unmarked branch
  accepts a marker that appeared (1); resolve drops the observed pair (5); the token route passes
  no observer (1); the refresh route observes nothing (1); every mark unchecked (7); the check
  claims instead of holding (1); no check on PostgreSQL (the race fails).
- **Review fix:** an independent review found that on an unmarked pair the check could miss a
  first claim not yet committed (no row to lock), while the mark waited on the Connection row
  and then marked the replaced key `error` on PostgreSQL. `mark_error_checked` now re-checks after
  the mark in the same transaction; the PostgreSQL race
  `test_an_error_mark_on_an_unmarked_pair_loses_to_a_first_claim_on_postgres` fails without the
  re-check (`error` != `active`) and passes with it.
- **Deviations:**
  - Profile marks and OAuth-callback failures got tests only (owner decision): the Profile mark
    already compares the credential version, and a callback failure touches only its own pending
    row or document.
  - The token service takes the observer as an optional argument: its unit tests use store fakes
    without a database, and the only production caller passes it (pinned by a route test).
  - `routes/oauth_connections.py` was already over 450 lines; it grew by 3 lines of wiring and no
    new responsibility.
  - A target with no observed pair (only the scaffold-only Profile-backed fallback) marks
    unchecked, as before; noted, not changed.
  - `migrated` pairs are unchanged (§5.3). **Open question for the owner:** their in-place key
    replacement leaves the same stale-mark window for `authorize_migrated`,
    `record_dispatch_failure_migrated` and the facade refresh.
