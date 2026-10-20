---
ticket: OME-1682
stack: aigateway
status: done   # planned | in_progress | done | blocked
started: 2026-10-19
finished: 2026-10-20
---

# e3b-retire-dead-profile-core — delete the Profile-era core left without a producer after E3

## Intent

Stage E of `OME-1209` (epic `OME-1138`) retires the legacy Profiles. Landing E3 (`OME-1651`,
PR #1464) answered the 13 Profile routes with a static 410 and deleted their handlers. That left
a core layer with no live producer: the Profile-backed credential admin operations, the
connection facade behind the old PATCH/refresh routes, the migrated-OAuth start/complete/fail
path, and the OAuth callback branches that only a legacy pending entry could reach. The only
`PendingAuthEntry` producer is now the native start `POST /v1/oauth/connections`, and the
pending table is per-process, so no legacy entry survives a deploy. Owner decision D3 puts this
dead layer in its own landing (E3b) before E4. Nothing live changes: the native OAuth flow, the
D14 compat-document mirror on the native callback, the D18 admin PUT and its none-pair bridge,
Profile bootstrap, and the `ProfileIndexStore` reads all stay until E4/E5.

## Planned changes

Owner decisions 2026-10-19: the test map as proposed; `PendingAuthEntry.connection_id` required;
`ProfileIndex.oauth_generations` deleted now; the dead callback branches move from E4 to E3b with
a plan amendment; optional tightenings (a) `auth_type`, (b) required `expected_live`/`claim_check`,
(f) the `ConnectionBackedCredentialAdmin` package re-export. Paths below are under
`apps/aigateway/src/aigateway/`.

- Delete `core/provider_access/connection_oauth.py` and `core/provider_access/connection_facade.py`.
- `routes/auth.py`: the callback keeps only the native path (delete the migrated-facade and
  legacy-pending arms, `_publish_migrated_oauth`, `_mark_profile_error`,
  `_invalidate_profile_session`, `_credential_strategy_for_app`, `_plugin_extracts_identity`, the
  `require_pending` branch of `_mark_profile_authenticated`, the `published` / `hold_pair` /
  shadow paths of `_record_oauth_connection_completion`, the `connection_id is None` paths, the
  stale "legacy Profile listings" header); drop `auth_type` from
  `_credential_strategy_for_credential_name`.
- `core/pending_auth.py`: drop `profile_id`, `compatibility_profile_name`, `oauth_generation`,
  `pair_generation`; `connection_id: str` required; delete `pop_for_profile`.
  `routes/oauth_connections.py`: drop `profile_id=` from the producer.
- `core/profile_index.py`: delete `begin_pending`, `authenticate_pending`, `mark_pending_error`,
  `update_metadata`; `core/profile_models.py`: delete `ProfileIndex.oauth_generations`.
- `core/provider_access/profile_admin.py`: delete `summary_of`, `provider_credential_admin_for`,
  `ProfileBackedCredentialAdmin.list/set_api_key/delete/_plugin`.
- `core/provider_access/connection_admin.py`: delete `legacy_view`, `_is_effective`,
  `ConnectionBackedCredentialAdmin.list/set_api_key/delete/_effective`; `publish_api_key` takes
  `expected_live` and `claim_check` as required.
- `core/provider_access/ports.py` (`ProviderCredentialAdmin`), `types.py` (`CredentialSummary`),
  `connection_authority.py` (`LEGACY_STATE_FOR_STATUS`), `writer_floor.py` (`hold_observed`),
  `__init__.py` (dangling re-exports and the `ConnectionBackedCredentialAdmin` re-export).
- `routes/credential_persistence.py` (`SupportsCredentialSlot`), `routes/provider_access_http.py`
  (`render_legacy_delete_refusal`, `legacy_delete_refusals_as_http`),
  `routes/saved_defaults_refusal.py` (`AccountRefusingSavedDefaults`), `main.py`
  (`app.state.provider_credential_admin`).
- Comment fixes that name the retired routes or the deleted flow as live (map section 4).
- `docs/plan/2026-10-14-OME-1209-retire-legacy-profiles.md`: an E3b section (plan amendment).
- `docs/tasks/2026-10-18-OME-1651-retire-profile-routes.md`: status done.
- Tests per the approved map (`stage_e3b_dead_core_test_map.md` in the team notes) and the
  manifest `.claude/test-change-approvals/OME-1682.json`.

## Test plan

- New tests first, against the current code (they pin live behaviour whose only test retires):
  - G1 `set_pair_api_key` maps an index `ProfileTransitionConflict` to `WriteConflict("superseded")`
    and a `CredentialBlobMutationConflict` to `"retry_exhausted"`, writing nothing.
  - G2 the D18 PUT writes the index row before the credential.
  - G3 a provider without an API-key strategy is refused (`UnsupportedAuthMode`) at the core and the
    HTTP edge, writing nothing.
  - G4 `publish_api_key` turns a sibling document into an api_key mirror and keeps its `defaults`.
  - G5 `addressed_by_a_live_connection` is True for a live row at the Profile address, False for a
    revoked one.
  - G6 `stamp_refreshed` keeps a PENDING document PENDING while moving `last_refreshed_at`.
  - G7 the native D14 mirror stamps `Profile.last_refreshed_at` (one assertion on the adapted
    `test_callback_completes_auth`).
- Then the deletions; retired tests keep a module docstring naming successors where a whole file
  retires; adapted tests keep their assertions except the 11 listed in the map.
- Gates: `run_gates.py aigateway --base origin/main`; PG lane `AIGW_TEST_PG=1` for
  `test_lifecycle_postgres_races.py` and `test_provider_access_backing_postgres.py`.

## Acceptance

- Every deleted symbol has no production caller (verified by call graph plus text search).
- The native OAuth start/callback, the D14 mirror, the D18 admin PUT, and chat resolution keep
  their tests green with unchanged assertions.
- Retired tests are listed in the manifest with their successor coverage; prior-test edits are
  assertion-preserving or owner-approved.
- `run_gates.py aigateway` green; the PG lane green for the touched concurrency suites.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned. Source: the two deleted modules plus 21 edited files under
  `apps/aigateway/src/aigateway/` (the planned ones and the comment fixes in `connection_native.py`,
  `refresh_guard.py`, `core/oauth/store.py`, `routes/__init__.py`, `core/admin_schemas.py`).
  Tests: one new file `tests/unit/core/provider_access/test_pair_admin_publication.py` (G1, G2,
  G4, G5 and the core half of G3), the HTTP half of G3 in
  `test_admin_connections_mutation_routes.py`, G6 in `test_profile_index.py`, G7 in
  `test_auth_routes.py`; persisted-format coverage in
  `tests/unit/test_profile_index_legacy_payload.py`; 33 prior test files edited per the map and
  listed in the manifest.
  Docs: the plan amendment (E3b section), the `OME-1651` mirror flipped to done, this ledger.
- **Commits:** `bbac0130b` deletes the dead core; the closeout commit records OME-1682 and pins
  legacy persisted-format compatibility.
- **Gates:** full suite 5969 passed, 103 skipped; ruff, format and pyright clean on `src` and
  `tests`. PostgreSQL lane (`AIGW_TEST_PG=1 -m needs_postgres`): 58 passed; the 5 failures are all
  in `test_cache_snapshot_upload_postgres.py` (untouched): the local `pg_dump` is 15.13 and the
  test container runs Postgres 16, which `pg_dump` refuses to dump. The final AIGateway gate is
  green (append-only with 32 approved transitions, ruff, format, pyright, no-enterprise, pytest
  with coverage at or above 80%). The touched PostgreSQL suites pass 4/4.
- **Deviations:**
  - `tests/unit/oauth_flow_seed.py` keeps a retirement docstring instead of being deleted: the
    append-only check refuses any deleted file under `tests/`, and a manifest can approve only an
    edit.
  - G1–G5 live in a new `test_pair_admin_publication.py` instead of `test_pair_admin_mutations.py`,
    which is already over the file-size norm.
  - `test_connection_backed_admin.py`, revoked-between race: the intrusion revokes on the second
    Connection listing, outside the PUT transaction. On `index.get` it ran inside the PUT
    transaction and was rolled back with it. Assertions unchanged.
  - The `delete` probe in `connection_backed_admin_probes.py` takes only the harness and calls
    `delete_pair` (D18); the deleted admin `delete` took a name.
  - Adapted setups that now go through the native start assert its `201` before using the
    answer, so a failed setup fails at its cause.
  - `test_auth_routes.py` and the two PostgreSQL modules have no module docstring; each retired
    test leaves a `WHY` comment at its place naming the successor.
