---
ticket: OME-1497
stack: aigateway
status: in_progress   # planned | in_progress | done | blocked
started: 2026-10-07
finished:
---

# g0-refresh-guarded-publish — split OAuth refresh into a network fetch and a guarded publish (G0, part 2 of 3)

## Intent

Second PR of the G0 writer floor (`docs/spec/2026-10-02-provider-credential-admin-contract.md`
§5.3, plan section B step 3; part 1 merged as #1271). Today the four OAuth plugins (anthropic,
codex, gemini, antigravity) write the refreshed token into the credential blob inside
`_refresh_credential`, with no check of who owns the pair. A refresh whose provider round trip
overlaps a key replacement or a delete therefore writes the old credential's tokens over the new
owner's blob (or resurrects a deleted blob). After this unit a refresh publishes only while the
same owner still holds the pair at the generation captured before the network call, and it never
advances the generation (refresh is not an ownership change).

## Planned changes

All under `apps/aigateway/src/aigateway/` unless noted.

- `plugins/{anthropic,codex,gemini,antigravity}_provider/auth.py`: `_refresh_credential` only
  fetches and normalizes; it no longer writes.
- `core/oauth_base.py`: `BaseOAuthStrategy` captures before the network call and publishes after
  it through a `RefreshPublication` port. The default publication writes directly (a strategy built
  outside the app keeps today's behaviour). A lost publication drops the cached creds and raises
  `RefreshSuperseded`.
- `core/errors.py`: `RefreshSuperseded` — deliberately NOT an `AuthError`, so no caller marks a
  row errored or answers 401 for a lost race.
- `core/provider_access/refresh_guard.py` (new): the guard for a Connection owner and a Profile
  owner. Capture reads the pair marker. Publish, in one short transaction: a marked pair holds the
  marker row at the captured generation (`hold_pair`), then locks the owner (Connection row
  `SELECT … FOR UPDATE`, not revoked; or the account index row, document still present); an
  unmarked pair locks the owner first and then requires the marker to be still absent; then the
  blob is written. Order marker → owner → blob, as the ownership writers.
- Bind the guard where the app builds a strategy that can refresh: `profile_authorize._strategy_for`
  (Profile or Connection backing), `connection_authority._strategy_for`,
  `connection_facade.refresh_facade`, `core/oauth/token_service.py`, `routes/oauth_connections.py`
  (refresh), `routes/auth.py` (legacy refresh).
- Map `RefreshSuperseded` to the existing conflict outcomes: Profile paths → 409
  `profile_conflict`, Connection paths → 409 `connection_conflict`; the cache entry is evicted
  where the caller owns the cache (the strategy itself always drops its cached creds); nothing is
  marked errored.

## Test plan

RED first (`tests/unit/core/provider_access/test_writer_floor_refresh.py`, plus a PostgreSQL race):

- Legacy refresh route: a key replacement during the provider window → 409 `profile_conflict`, the
  blob holds the new key, the document is not marked errored.
- Native connection refresh and token endpoint: a delete or an ownership claim during the window →
  409 `connection_conflict`, no blob resurrected, no error mark.
- Dispatch (chat) on a Profile target and on a migrated target with expired tokens and an ownership
  change during the window → 409, no error mark, the new owner's blob intact.
- Migrated facade refresh with a delete during the window writes no blob (H-1 extended).
- A refresh with no interference publishes and never moves the marker (marked and unmarked pairs).
- Start re-auth → ordinary refresh publishes → callback with the original generation succeeds.
- A cached strategy refreshes again after an unrelated legitimate generation change (capture is per
  refresh, never at build).
- Unbound strategy (plugin level) still writes on refresh.
- PostgreSQL: an old refresh publication after a key replacement loses on an unmarked `none` pair.

## Acceptance

- Every refresh persistence path found by the inventory is guarded or shown not to refresh.
- The falsifiers above pass; refresh never advances the generation.
- Full `aigateway` gates and the PostgreSQL lane green; prior tests unchanged unless approved.
- No new API, error code, schema migration, lock table or job.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `core/profile_index.py` (`lock_account_index`, the account
  index row lock the Profile-owned publication takes; `ProfileIndexStore.stamp_refreshed`, a
  lock-free metadata stamp on the current document) and the `core/provider_access/__init__.py`
  exports (`ConnectionRefreshOwner`, `ProfileRefreshOwner`, `guard_refresh`). New tests:
  `tests/unit/core/provider_access/test_writer_floor_refresh.py` (19),
  `test_writer_floor_refresh_reauth.py` (3), `test_writer_floor_native_compat.py` (1),
  `test_writer_floor_refresh_revision.py` (8), `test_refresh_guard_inventory.py` (3),
  `tests/integration/test_writer_floor_refresh_postgres.py` (3).
- **Commits:** pending.
- **Gates:** `uv run .claude/scripts/run_gates.py aigateway --base origin/main` — ALL GATES GREEN
  (append-only, ruff check, ruff format, pyright, no-enterprise, pytest with coverage ≥ 80%); full
  suite 5257 passed, 100 skipped (gates run against the merge base, since main moved by an unrelated
  `usage_accounting` change); the append-only check passes on the owner-approved transition
  recorded in `.claude/test-change-approvals/OME-1497.json`. RED: 6 of the first 11 new tests failed for the defect (refresh
  published over an ownership change); the others are regression guards. PostgreSQL lane
  (`AIGW_TEST_PG=1 uv run pytest -m needs_postgres`): all three new races pass; 5 failures in
  `test_cache_snapshot_upload_postgres.py` are the local `pg_dump` 15 vs 16-alpine server mismatch
  (`request_cache` untouched); 58 passed, including the re-pointed H-1 race.
- **Mutation checks (pair-generation version, before the narrowing below):** dropping `hold_pair` fails the two marked-pair tests; dropping the owner
  lock on the marked branch fails the revoked non-effective row test; dropping the stamp from the
  publication fails the dispatch stamp test; unbinding the guard fails all three PostgreSQL races.
- **Review:** an independent review found two blockers, both fixed. (1) The metadata write after
  the guarded publication upserted a pre-fetch snapshot, which could revert a key replacement
  committed right after the publication (document back to `oauth`, next dispatch marks it
  errored). `last_refreshed_at` and the AUTHENTICATED state are now stamped inside the guard
  transaction on the document as committed (`stamp()` on both owners); the legacy route returns
  the document read after the refresh; the migrated facade mirrors with `stamp_refreshed`. (2) The
  marked-pair branch was untested; the falsifiers above now cover `hold_pair` and the owner lock.
  Minor: `profile_authorize` now invalidates the session on a lost refresh, as the other Profile
  paths do.
- **Second review (delta after the first fixes):** one blocker and two minor points, all fixed.
  (1) `stamp_refreshed` promoted a PENDING document to AUTHENTICATED, so a legacy re-auth started
  during a dispatch refresh window (unmarked pair, no marker move) lost its callback with a false
  409 `profile_auth_conflict` — a regression against main for dispatch, and pre-existing for the
  legacy refresh route, which is fixed too. The stamp now keeps PENDING and only updates
  `last_refreshed_at`. Falsifiers: `test_writer_floor_refresh_reauth.py` (dispatch and route;
  both failed before the fix). (2) The Profile owner presence check was pinned by no test (every
  remover also claims the pair); a document removal without a marker move now pins it. (3) The
  native callback's compat-document conflict (`CredentialBlobMutationConflict`) was being turned
  into 503 `connection_activation_failed` with the Connection marked errored; it again rolls back
  and answers the existing 503 `profile_index_conflict` with the Connection still pending
  (`test_writer_floor_native_compat.py`, failed before the fix). Consistency:
  `authorize_migrated` now also invalidates the session on a lost refresh. Confirmed by the
  review: lock order and the lock-free stamp hold, the guard inventory is complete, a cached
  strategy is never rebound to another owner, no token reaches a log or an error body.
- **Native callback skips the compat update when nothing activates:** the duplicate-identity
  return, `label_required` and a label conflict no longer flip a same-named Profile to
  AUTHENTICATED/`oauth` (main did, with no blob or row published). Intended.
- **Refresh check narrowed (owner decision 2026-10-07, after the PR review; supersedes the
  earlier "known risk, option a"):** the publication no longer checks the pair generation. It
  captures its own blob's row id and `credential_revision` before the fetch, then locks the owner
  and the blob row and requires both unchanged (lock order owner → blob, a suffix of the writers'
  marker → owner → blob). The revision already existed (store increments it on every value write,
  a PostgreSQL trigger covers older binaries; dispatch outcome writes leave it alone), so no
  migration. Effects: an ownership change elsewhere on the pair no longer burns a rotating refresh
  token; a rewrite, delete or recreation of the refreshed blob without a marker move — which the
  pair check missed — now makes the refresh lose (closes the two rare review cases: an account with
  no index row, a Profile and a Connection sharing an address). Spec §5.3 and §9 updated. Tests:
  `test_writer_floor_refresh_revision.py` (5; the first four failed before the change). This PR's
  own tests that used a bare pair claim as "the other writer" now use a rewrite of the refreshed
  blob. Mutation checks: no revision check (8 fail), revision without the row id (1), no owner lock
  (2), publishing over a blob absent at capture (1).
- **Observation bound to the credential read (third review blocker):** the narrowed check still
  captured at refresh time, so a cached strategy whose blob was rewritten after its read (or a
  rewrite between a fresh read and the capture) published the old credential's refreshed tokens
  over the new key — the pair-generation version had the same hole. `BaseOAuthStrategy` now takes
  the observation around its own read (equal before and after, else it re-reads, at most 3 times,
  then refuses with the superseded conflict) and adopts the observation each publication returns
  for what it wrote; the refresh checks that one, never a fresh capture. Tests (all in
  `test_writer_floor_refresh_revision.py`): a cached strategy refreshing after a rewrite loses and
  keeps the new key; a rewrite between the read and the refresh is re-read and served, nothing
  spent; a credential that changes under every read is refused (both of the first two failed
  before the fix). Mutation checks: a fresh capture at refresh time (1 fails), no bracket after the
  read (1), no re-read (1), not adopting the published observation (1).
- **Guard inventory pinned:** `test_refresh_guard_inventory.py` scans `src/` for every function that
  builds a credential strategy and fails on an unclassified site, an unguarded refreshing site, or a
  "no refresh" site that starts refreshing (falsified with an added site and an unbound one). Site
  names are class-qualified, and a factory reached through an import alias or `getattr` with a
  literal name is still found (falsified with both); `refresh` counts as a refresh call. A
  dispatch target with no stored backing is ambient (no blob), which is why it passes unguarded.
- **Open question for the owner (not blocking):** a Profile delete that leaves the blob in place
  for a live Connection at the same address makes an in-flight Profile-owned refresh lose, and a
  rotating provider has then already spent the refresh token the Connection still holds. An option
  is to publish when the blob is unchanged even though the owner is gone (no stamp, still 409).
  Left as is: the window is one provider round trip, and the Connection recovers by re-auth.
- **Third review (delta after the read-bound fix):** no blockers. Two nonblocking notes, left as
  is: a strategy loaded under the direct publication and guarded later would refresh with no
  observation and lose (latent — every site binds the guard before the first load); and a request
  that reads `_cached` after the lock while a concurrent refresh loses can raise instead of
  answering 409 (pre-existing on main).
- **Deviations:**
  - The observation is taken with the strategy's read of the blob and renewed by each publication,
    not when the strategy is built and not at refresh time; a cached strategy therefore checks
    exactly the credential it holds.
  - Dispatch on a migrated target answers the `connection` subject (409 `connection_conflict`):
    the owner is the Connection, and the request carries no Profile name to echo.
  - The token endpoint answers 409 `{"code": "connection_conflict"}`, the body the native refresh
    route already uses for a lost race. It does not evict: its cache port has no `evict`, and the
    strategy already dropped its cached creds.
  - A refresh of a non-effective native row of a migrated pair is checked against the marker like
    every other owner (one rule); its false-loss window is the provider round trip only.
  - The native refresh route's `complete_active` still writes label and identity from the row read
    before the fetch (pre-existing, unchanged here).
  - The prior PostgreSQL race `test_profile_refresh_publication_loses_to_committed_delete_on_postgres`
    probes the removed post-refresh `index.upsert`; the invariant it protects (no resurrection,
    409) is now held by the guard and proven by the new delete race. With owner approval
    (2026-10-07) its probe moved to the guarded publication's entry and it drives a real OAuth
    refresh against a mocked provider; every assertion is unchanged. The probe sits at the entry,
    not at the owner lock, because a marked pair waits on the marker row first (marker → owner).
  - Folded in the PR 1 leftover (owner decision 2026-10-07): the native OAuth callback now claims
    the pair and updates a same-named compat Profile inside the activation/blob transaction, so a
    failed publication rolls everything back (two new tests in `test_writer_floor_native.py`; the
    PR 1 ledger records the change).
