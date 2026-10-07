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
  `tests/integration/test_writer_floor_refresh_postgres.py` (3).
- **Commits:** pending.
- **Gates:** `uv run .claude/scripts/run_gates.py aigateway --base origin/main` — ALL GATES GREEN
  (append-only, ruff check, ruff format, pyright, no-enterprise, pytest with coverage ≥ 80%); full
  suite 5242 passed, 100 skipped; the append-only check passes on the owner-approved transition
  recorded in `.claude/test-change-approvals/OME-1497.json`. RED: 6 of the first 11 new tests failed for the defect (refresh
  published over an ownership change); the others are regression guards. PostgreSQL lane
  (`AIGW_TEST_PG=1 uv run pytest -m needs_postgres`): all three new races pass; 5 failures in
  `test_cache_snapshot_upload_postgres.py` are the local `pg_dump` 15 vs 16-alpine server mismatch
  (`request_cache` untouched); 58 passed, including the re-pointed H-1 race.
- **Mutation checks:** dropping `hold_pair` fails the two marked-pair tests; dropping the owner
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
- **Known risk (owner decision 2026-10-07, option a — keep the spec's pair-wide check):** a
  generation move that does not touch this blob (another Connection created or started on the same
  provider during the ~1 s provider round trip) also makes the refresh lose. With a rotating
  refresh token the provider has already consumed the old one, so the next refresh of that owner
  may need a re-auth. Deferred fix (b), about half a day: check the blob's own revision plus a blob
  row lock instead of the pair generation; it also closes two rare review cases (an account with no
  per-account index row; a Profile and a Connection sharing one address).
- **Deviations:**
  - The capture happens per refresh inside the strategy lock, right before the network call, not
    when the strategy is built; a cached strategy is therefore never stuck on an old generation.
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
