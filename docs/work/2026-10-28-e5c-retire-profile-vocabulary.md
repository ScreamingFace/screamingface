---
ticket: OME-1759
stack: aigateway
status: done   # planned | in_progress | done | blocked
started: 2026-10-28
finished: 2026-10-29
---

# e5c-retire-profile-vocabulary — remove the Profile vocabulary from the gateway (Stage E history cleanup, E5c)

## Intent

Stage E ended Profile authority (E4a/E4b), and E5b's purge has removed the Profile index documents
from dev, stage and prod (applied 2026-10-28). Nothing at runtime reads or writes a Profile
document any more, yet the gateway still ships the Profile model, the index store, the offline
backfill and the purge command. This unit deletes them, as planned in
`docs/plan/2026-10-21-OME-1715-e5-history-cleanup.md` §3 E5c and specified in
`docs/spec/2026-10-21-OME-1715-e5-history-cleanup.md` §5-§6 (Q5: the purge command retires with
the vocabulary). Its precondition, the purge applied in every environment, is met. Runtime error
codes `profile_index_conflict` and `profile_conflict` stay (out of scope, R3).

## Planned changes

- Delete `apps/aigateway/src/aigateway/core/profile_index.py`, `core/profile_models.py`,
  `core/provider_access/backfill_classify.py`, `core/provider_access/backfill_apply.py`,
  `core/provider_access/history_purge.py`, `migrate_profiles.py`, `purge_profile_history.py`, and
  `core/provider_access/history_references.py`, which only the purge reads.
- `core/credential_names.py`: drop `profile_id_for`; keep `credential_name_for`.
- `core/provider_access/auth_mode.py`: `auth_type_of` takes only the Connection; its four runtime
  callers (`connection_authority.py`, `connection_backed.py`, `connection_locator.py`,
  `targets.py`) drop the `None` they pass for the Profile.
- Tests: per the approved test map and its manifest (`.claude/test-change-approvals/`): retired
  suites become retirement docstrings naming their successors (the E4b convention); surviving
  suites stop seeding or reading Profile documents; the import-boundary guard changes from "only
  the offline tools import `profile_index`" to "nothing does".
- Test vocabulary (owner decision, 2026-10-28): `ProfileState` becomes the test-local `SeedState`
  (`tests/unit/seed_state.py`); the shared harness surface goes neutral — `ProfileBackedHarness`
  to `RealAppHarness`, `seed_profile` to `seed_credential`, `profile_state` to
  `credential_state`; `seed_document` and the index-read spy go. Test names, file names and
  per-file local helpers keep their names.
- Docs that name the deleted modules as live code, where a reader would act on them.

## Test plan

- First (RED): the import guard — no module under `src/aigateway` imports `profile_index` or
  `profile_models`, and neither module exists; `aigateway.migrate_profiles` and
  `aigateway.purge_profile_history` are not importable; `credential_names` has no
  `profile_id_for`; `auth_type_of` accepts a Connection only.
- Then the full aigateway suite with the retired and edited tests listed in the manifest.

## Acceptance

- No module under `src/aigateway` imports `profile_index` or `profile_models`, and both are gone.
- The two offline commands are gone; `python -m aigateway.migrate_profiles` fails to import.
- `run_gates.py aigateway` green with only manifest-approved test transitions.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
  - src (21 entries with the six guard tests): the eight planned modules deleted;
    `core/credential_names.py` (no `profile_id_for`); `core/provider_access/auth_mode.py`
    (`auth_type_of(connection)`) and its four callers; `core/provider_access/__init__.py` (stale
    backfill comment dropped).
  - Guards: `test_profile_index_offline_only.py` (the E5c import and absence guard),
    `core/provider_access/test_provider_access_import_boundary.py`,
    `core/test_neutral_credential_vocabulary.py`, `test_profile_conflict_arms_retired.py`,
    `core/test_no_auth_mode.py`, `gemini/test_profileless_auth_provenance.py`.
  - Tests: 92 existing test paths modified plus 1 added (`tests/unit/seed_state.py`). Of the 92,
    87 carry executable transitions, all in the manifest (the six guards included), and 5 change
    only comments or docstrings. They cover the shared harnesses and probes, 16 retired suites and
    2 probe modules as retirement docstrings, and the surviving suites.
  - Docs: `apps/aigateway/DEPLOYMENT.md` (the cache section no longer describes the index); the
    OME-1208 task mirror and ledger are closed (Linear Done since 2026-09-23) with a note that the
    backfill was applied and `migrate_profiles` is gone, so no open record still reads as
    instructions for the deleted command.
  - Manifest: `.claude/test-change-approvals/OME-1759.json` (the 87 modified test files).
- **Commits:** squash-merged as `7cb093014` (#1596) from, after the rebase onto `origin/main`
  `cfb178b30`:
  - `a55d47efc` test(aigateway): stop seeding Profile documents and retire their suites
  - `67356573e` refactor(aigateway): delete the Profile model, index and offline tools
  - `15f189dc4` docs(aigateway): drop the Profile index from the runbook and record E5c
- **Gates:** `ruff check` clean; `ruff format --check` 853 files formatted; `pyright` 0 errors;
  `check_no_enterprise.py` OK; `pytest --cov=aigateway --cov-fail-under=80` 7124 passed,
  107 skipped, coverage 93.96%. The append-only check lists 87 modified test files and no
  deleted, renamed or retyped one; all 87 are approved through the manifest. The same gates ran
  again in the pre-push hook after the rebase onto `cfb178b30`, all green.
  `AIGW_TEST_PG=1 pytest -m needs_postgres`: 67 passed, including the two edited suites
  `test_pair_admin_mutations_postgres.py` and `test_provider_access_backing_postgres.py`. PR CI
  green.
- **Deviations:**
  - `test_profile_index_offline_only.py` stays a live suite, not a retirement docstring: three of
    its tests still hold, and it hosts the E5c guard.
  - Four tests the map marked R5 stay under R4, because each still pins a non-Profile claim once
    the document seed is gone: `test_connection_only_resolve.py::`
    `test_a_lone_profile_document_is_not_a_target_of_an_unmarked_pair`, the two profile-only-pair
    tests in `test_pair_admin_connection_only.py`, and `test_chat_profile_default_validation.py::`
    `test_a_caller_fault_is_reported_alone_beside_an_invalid_historical_default`.
  - The base real-app harness seeds with `seed_blob` rather than `seed_credential`: it writes only
    the blob, no state, so the neutral name says what it does. `seed_credential` is the
    Connection-backed harness's and the fake's name.
  - Review follow-up: the two `test_writer_floor_native.py` callback tests that claim the
    same-named credential stays unchanged now snapshot the blob at the `work` name address and
    assert it is identical after the callback, instead of asserting only the response.
  - Five route suites whose only seed was a document now read `/v1/model-parameters` with no
    credential; their assertions pass unchanged, which confirms the documents were inert.
  - `unit/conftest.py` still lists `test_api_key_routes.py` in `_LEGACY_API_KEY_ROUTE_MODULES`;
    harmless for a retirement docstring, left to keep the conftest out of the manifest.
  - Follow-ups, out of scope: `ORMStore.mutate` and `CredentialBlobMutationConflict` have no
    production caller left; `aigateway-ui` still maps `profile_index_conflict`, which the gateway
    stopped emitting at E5a; the forbidden literals in
    `test_provider_access_availability_route.py::`
    `test_body_carries_no_name_id_label_default_auth_method_or_locator` have been vacuous since
    E4a.
  - Not done here, though spec §6 put it in this change set: the design catalog's contract
    exporter still imports `Profile` and `ProfileIndex` from the deleted `profile_models`, its
    model projector pins them in the schema inventory, and the catalog's `Profile`,
    `ProfileState`, `ProfileIndex` and `ProfileDefaults` datamodel cards still cite the deleted
    modules. The catalog cannot be regenerated from `main` until that lands as its own leaf under
    `OME-1138`.
