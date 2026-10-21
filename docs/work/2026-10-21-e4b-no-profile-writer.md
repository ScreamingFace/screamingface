---
ticket: OME-1695
stack: aigateway
status: done   # planned | in_progress | done | blocked
started: 2026-10-21
finished: 2026-10-21
---

# e4b-no-profile-writer — no runtime path writes or removes a Profile document

## Intent

Stage E of `OME-1209` (epic `OME-1138`), landing E4b of E4 (spec §9 Q10, Q11; plan §3 E4b). E4a
made every reader Connection-only, but the runtime still writes the legacy Profile index: the
native OAuth callback mirrors its success onto a same-named document (D14), a native key
replacement mirrors the key onto the pair's documents and a native delete of the effective row
removes them, the D18 PUT writes an API-key mirror (and its siblings) and the D18 DELETE removes
the pair's documents, and an opt-in startup import seeds an Anthropic Profile. E4b removes every
one of those writes and the reads that only fed them, stops wiring `ProfileIndexStore` in
`main.py`, and keeps the index, its read models and the backfill tools for E5, reachable only
from the offline tools. No document or blob is deleted by this landing (R5).

## Planned changes

- `routes/auth.py`: the D14 mirror (`_mark_profile_authenticated`, `_index_store_for_app`) and the
  callback's two `CredentialBlobMutationConflict` arms go.
- `core/provider_access/connection_native.py`: `republish_effective_api_key` keeps its generation
  fence and loses the mirror; `retire_effective` keeps the marker work and loses the document
  removal; `credential_has_other_owner` loses the document check (and the marker read that only
  gated it). The now-unused `app` and `raw_api_key` parameters go; callers in
  `routes/oauth_connections.py` and `pair_admin_writes.py` follow.
- `core/provider_access/connection_admin.py`: `api_key_mirror`, `_mirror_siblings` and the index
  writes in `publish_api_key` go, with their `ProfileTransitionConflict` and
  `CredentialBlobMutationConflict` arms; `publish_api_key` returns the Connection.
- `core/provider_access/pair_admin_writes.py`: `_mirror_name` goes (a new row is named
  `default`); DELETE reads and removes no document.
- `core/provider_access/profile_admin.py`: `addressed_by_a_live_connection` and the `_index`
  property go.
- Profile bootstrap: `writer_floor.bootstrap_under_the_floor` (and `_NothingImported`),
  `plugins/anthropic_provider/bootstrap.py`, `bootstrap_profiles` on the plugin base and the
  Anthropic plugin, `BootstrapError`, and the Anthropic settings only the import read
  (`claude_code_keychain_service`, `bootstrap_user`). `main.py` logs a startup warning when
  `AIGATEWAY_BOOTSTRAP_FROM_CLAUDE_CODE=1`.
- `main.py`: no `ProfileIndexStore` import or `app.state.profile_index`.
- `core/provider_access/backfill_classify.py`: `BackfillContext.from_app` goes (`from_stores`
  stays); `core/provider_access/__init__.py` stops re-exporting the backfill modules and the
  bootstrap, so importing `aigateway.main` loads no `profile_index`.

## Test plan

New tests first (prior tests are append-only until the owner approves the test map):

- the native callback, native key replacement and native delete of a migrated pair's effective
  row, the D18 PUT and the D18 DELETE write and remove no Profile document (a class-level spy on
  every `ProfileIndexStore` write, plus the document read back unchanged);
- the native key replacement still advances the pair generation (a repair callback in flight
  loses);
- a native delete on a `none` pair whose Connection shares a document's blob address deletes the
  blob: a document is no longer an owner;
- startup with `AIGATEWAY_BOOTSTRAP_FROM_CLAUDE_CODE=1` logs the retirement warning and writes no
  document, blob or marker;
- `create_app()` wires no `profile_index`; a fresh interpreter importing `aigateway.main` has no
  `aigateway.core.profile_index` in `sys.modules`;
- the import boundary: only the offline backfill tools import `profile_index`;
- the removed names are gone (`api_key_mirror`, `addressed_by_a_live_connection`,
  `bootstrap_under_the_floor`, `bootstrap_profiles`, the bootstrap module, `BackfillContext.from_app`,
  `BootstrapError`);
- the backfill CLI still classifies, applies and rolls back from its own stores (existing CLI
  tests stay green).

## Acceptance

- The native callback, native re-key and delete, D18 PUT/DELETE and startup write and remove no
  Profile document; `main.py` wires no `ProfileIndexStore`; importing `aigateway.main` loads no
  `profile_index`; the import boundary allows it only in the offline tools.
- The backfill CLI still classifies, applies and rolls back from its own stores.
- Retired and adapted prior tests are listed in the approval manifest with their successors.
- `run_gates.py aigateway` green; the PostgreSQL lane green for the concurrency suites.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
  - Source, as planned: `routes/auth.py`, `routes/oauth_connections.py`, `main.py`,
    `core/errors.py`, `core/plugin_base/_provider.py`, `core/provider_access/{__init__,
    backfill_classify,connection_admin,connection_native,pair_admin_writes,profile_admin,
    writer_floor}.py`, `plugins/anthropic_provider/{plugin,settings}.py`; deleted
    `plugins/anthropic_provider/bootstrap.py`.
  - New tests: `tests/unit/core/provider_access/test_no_profile_writer.py` (7),
    `tests/integration/test_native_d18_writer_serialization_postgres.py` (2),
    `tests/unit/test_profile_index_offline_only.py` (6 functions, 10 cases).
  - Prior tests (owner-approved test map, 2026-10-21), 30 files under the append-only check,
    each listed in `.claude/test-change-approvals/OME-1695.json`:
    - Mechanical (stores built on the spot, class-level spies on `ProfileIndexStore`,
      `BackfillContext.from_stores`, the one-argument `credential_has_other_owner`, the import
      boundary owners): `provider_access_harness.py`, `backfill_probes.py`,
      `test_connection_only_resolve.py`, `test_provider_access_availability.py`,
      `test_provider_access_availability_route.py`, `test_migrated_rejected_key_availability.py`,
      `test_api_key_routes.py`, `test_api_key_validation_routes.py`, `test_main.py`,
      `test_provider_access_import_boundary.py` and the four PostgreSQL suites
      (`test_pair_admin_mutations_postgres.py`, `test_provider_access_backfill_postgres.py`,
      `test_provider_access_backing_postgres.py`,
      `test_provider_access_shared_addresses_postgres.py`).
    - Adapted (the document stays; the Connection is asserted instead):
      `test_pair_admin_mutations.py`, `test_pair_admin_connection_only.py`,
      `test_connection_backed_admin.py`, `test_connection_backed_admin_delete_list.py`,
      `test_connection_backed_native_routes.py`, `test_writer_floor_refresh.py`,
      `test_connection_backed_shared_addresses.py`, `anthropic/test_settings.py`,
      `test_profile_oauth_flow_ownership.py`, `test_auth_routes.py`, `test_bootstrap.py`,
      `test_pair_admin_publication.py`. Seven tests renamed to what they now pin.
    - Retired (22 test functions; each file or section keeps a WHY pointer to its successors):
      docstring-only shells `anthropic/test_bootstrap.py`, `test_writer_floor_bootstrap.py`,
      `test_writer_floor_native_compat.py`, `test_profile_publication_locking.py`; G1, G2, G4 and
      G5 in `test_pair_admin_publication.py`; the vanished-document re-key test; two rollback
      tests in `test_connection_backed_shared_addresses.py`; the `profile_index_conflict` 503
      test in `test_auth_routes.py`; three startup-import tests in `test_bootstrap.py`.
    - Successor pointers re-pointed in three existing shells (`test_provider_credential_admin.py`,
      `test_pair_shadow_identity_writes.py`, `test_writer_floor_legacy_admin.py`).
- **Commits:** squash-merged as `f7e54869b` (#1516) from `973f47876` (E4b) and `490a50d9a`
  (the native/D18 writer-race fix).
- **Review:** the independent read-only review found no E4b blocker. Its residual native-create/D18
  race is closed in the follow-up: `claim_native_write` holds a migrated pair's marker without
  advancing it, and PostgreSQL tests pin both commit orders.
- **Gates:**
  - `run_gates.py aigateway --base origin/main --skip-append-only`: ruff check, ruff format,
    pyright, enterprise guard and the full suite with coverage (`--cov-fail-under=80`) green.
  - Full unit suite: 6000 passed, 103 skipped.
  - The append-only check passes only through the approval manifest
    `.claude/test-change-approvals/OME-1695.json` (branch `OME-1695-e4b-no-profile-writer`).
  - PostgreSQL lane (`AIGW_TEST_PG=1 -m needs_postgres`): 58 passed; the 5 failures are all in
    `test_cache_snapshot_upload_postgres.py` (untouched): the local `pg_dump` 15 cannot dump the
    PostgreSQL 16 container. Every concurrency suite of this landing passed.
  - Race follow-up: the new PostgreSQL file passes 2/2; the writer-floor/native/D18 unit cluster
    passes 123 tests; the selected PostgreSQL writer-race cluster passes 14 tests; the full
    `run_gates.py aigateway --base origin/main` is green including append-only, Ruff, format,
    Pyright, enterprise guard and full coverage suite.
- **Deviations:**
  - The read-outage test of the D18 DELETE is adapted, not retired: it now fails the
    `OAuthConnectionStore.list` read and keeps its `CredentialStoreReadUnavailable` refusal.
  - The dead conflict arms stay until E5 (owner decision 2026-10-21):
    `main._profile_index_conflict`, the `chat._error_view` arm,
    `provider_access_http._write_conflict` `retry_exhausted` / `profile_conflict` and
    `WriteConflictKind` `"retry_exhausted"`.
  - `MASKED` stays defined in `connection_backed_admin_probes.py`; no test imports it now.
  - Four successor pointers that already dangled on `origin/main` after E4a are left as they are
    (out of scope).
  - Carried to E5 (separately authorised): collapse `ProfileBackedCredentialAdmin` into
    `ConnectionBackedCredentialAdmin`; the `stamp_refreshed` PENDING branch; `ProfileIndexStore`,
    its read models and the backfill tools; the dead conflict arms; the cleanup fixture where a
    Connection still uses a legacy-addressed blob, including a new reference between the check
    and the delete.
  - Deploy precondition (owner): the read-only census is re-run before this landing reaches
    stage and prod (spec §7 Q3).
