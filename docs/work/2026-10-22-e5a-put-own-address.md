---
ticket: OME-1715
stack: aigateway
status: done   # planned | in_progress | done | blocked
started: 2026-10-22
finished: 2026-10-22
---

# e5a-put-own-address — the D18 PUT mints a Connection address (Stage E history cleanup, E5a)

## Intent

The E5 purge (`docs/spec/2026-10-21-OME-1715-e5-history-cleanup.md`) deletes credential blobs no
Connection addresses. Today a D18 PUT on a pair with no reusable row mints its row at the `default`
Profile address, so it can adopt a blob left there, and `ORMStore.write` (get, then UPDATE by id)
silently loses the key if the purge deletes that blob in between. This unit removes that path at its
source: a minted row takes its own `<account_id>:<connection id>` address, as a native API-key row
does, and the Profile name the PUT carried (`DEFAULT_LEGACY_NAME`, `PairMutation.profile_names`)
goes with it. Plan `docs/plan/2026-10-21-OME-1715-e5-history-cleanup.md` §3 E5a.

## Planned changes

- `apps/aigateway/src/aigateway/core/provider_access/connection_admin.py`: `publish_api_key` loses
  `name`; a minted row's locator is its own address.
- `apps/aigateway/src/aigateway/core/provider_access/pair_admin_writes.py`: no
  `DEFAULT_LEGACY_NAME`, no `PairMutation.profile_names`.
- `apps/aigateway/src/aigateway/core/provider_access/profile_admin.py`: deleted; its strategy,
  eviction and typed persist move into `connection_admin.py`.
- `apps/aigateway/src/aigateway/core/pending_auth.py`: `pop_for_pair` matches Connection ids only.
- `apps/aigateway/src/aigateway/routes/admin_connections.py`: passes the ids only.
- Dead conflict arms: `main.py` (`_profile_index_conflict` and its registration),
  `routes/chat.py` (`_error_view`), `routes/provider_access_http.py` (`_write_conflict`,
  `_successor_write_conflict`), `core/provider_access/types.py` (`WriteConflictKind`,
  `WriteSubject`).
- New test files `apps/aigateway/tests/unit/core/provider_access/test_pair_put_own_address.py`
  and `apps/aigateway/tests/unit/test_profile_conflict_arms_retired.py`.
- Prior tests per the E5a test map (A1-A9, B1-B6, C1-C2, D1-D4), after the owner approves the
  manifest.

## Test plan

- RED first: a PUT on an empty pair stores the key at the row's own address; beside a leftover
  blob at the `default` address that blob stays byte-equal and is not adopted; a PUT that reuses a
  migrated row still writes its legacy-addressed blob; the pending-flow drop ends the captured
  Connection's flow and leaves a flow that only shares the old `default` name. Only the offline
  `ProfileIndexStore` calls `ORMStore.mutate`; the app registers no `profile_index_conflict`
  handler; a captured call replays a mutation conflict as the generic 500; `WriteConflict` is only
  ever a superseded Connection.
- Then the full suite; the prior tests that move must be exactly the map's rows.

## Acceptance

- New tests green; prior tests changed only as the approved manifest lists.
- `run_gates.py aigateway --base origin/main` green; PostgreSQL lane green for the pair-mutation
  suites.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned. Source: `core/provider_access/connection_admin.py`,
  `pair_admin_writes.py`, `types.py`, `profile_admin.py` (deleted), `core/pending_auth.py`,
  `main.py`, `routes/admin_connections.py`, `routes/chat.py`, `routes/provider_access_http.py`.
  New tests: `tests/unit/core/provider_access/test_pair_put_own_address.py` (4),
  `tests/unit/test_profile_conflict_arms_retired.py` (4). Prior tests: the 11 files of the approved
  test map plus the remote-endpoint harness helper (see Deviations), pinned by the test-change
  manifest.
- **Commits:** squash-merged as `8cb1e54e0` (#1541) from `46d66aab8` (docs(aigateway): add the
  E5 history-cleanup spec and plan) and `a3ba63a05` (refactor(aigateway): mint a D18 PUT's row at
  its own address and retire the dead Profile conflict arms).
- **Gates:** RED first: the 4 address tests failed 3/4 on the base (the migrated-pair case is a
  guard and passed), the 4 retired-arm tests 3/4. Then the full unit suite before the prior tests
  moved: exactly the map's rows failed (20 tests, 2 collection errors), nothing else. After the
  approved edits: `run_gates.py aigateway --base origin/main` all green (append-only check with
  the manifest, ruff, ruff format, pyright, no-enterprise, pytest with coverage at or above 80).
  PostgreSQL lane (`AIGW_TEST_PG=1 pytest -m needs_postgres`): 64 passed; the pair-mutation,
  backing, native-repair and backfill suites 12/12, including the two-first-PUT race (map A9).
- **Deviations:**
  - Rebased onto `origin/main` `ae1292505` before the gates; the only shared file, `main.py`, had
    no overlapping hunk.
  - Rebased again onto `bdf5746a4` (hosted BYOM). One textual conflict, in the `routes/chat.py`
    imports: main's `endpoint_access` import stays, E5a's removal of the
    `CredentialBlobMutationConflict` import stands. One semantic conflict: the new remote-endpoint
    harness helper `stored_key` read the key at the `default` Profile address, so 13 BYOM tests
    failed once the PUT minted its own address. With the owner's approval (2026-10-22) the helper
    reads the address the pair's live Connection names; `tests/unit/remote_endpoint/conftest.py`
    joins the manifest. All 326 remote-endpoint tests pass.
  - Map D2 became one unparametrised test (one kind, one subject remain); D4 also dropped the
    `SimpleNamespace` import only the retired class used.
  - PostgreSQL lane: 5 tests in `test_cache_snapshot_upload_postgres.py` fail locally because the
    host `pg_dump` is 15 and the test container is PostgreSQL 16. Environment only; this unit
    changes no cache-snapshot code.
  - `tests/unit/test_chat_global_cache_route.py::test_cache_failure_logs_escape_caller_controlled_model_newlines`
    failed once in seven isolated runs during this unit (a real dispatch that sometimes answers
    500); it passed in every full run. Pre-existing, untouched.
