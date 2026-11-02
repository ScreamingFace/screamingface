---
ticket: OME-1651
stack: aigateway
status: done   # planned | in_progress | done | blocked
started: 2026-10-18
finished: 2026-10-18
---

# e3-retire-profile-routes — the 13 legacy Profile routes answer 410 with their successor

## Intent

Landing E3 of Stage E (`OME-1209`; spec `docs/spec/2026-10-14-OME-1209-retire-legacy-profiles.md`
R1 and §2.1; plan §3 E3).

- E1 already points every `reauth_url` at the Connection API, and E1b makes the native OAuth flow
  repair a migrated pair. No runtime response, and no credential repair, needs a Profile route any
  more.
- This unit retires the 13 Profile routes. Each answers `410 Gone` with
  `legacy_profile_api_retired` and its successor. It does this before authentication, before any
  I/O and before reading the body, and the routes leave the OpenAPI schema.
- Storage, chat resolution, the callbacks, the writer floor and bootstrap stay until E4.
- The core operations that only the retired handlers called are deleted in a separate landing,
  E3b (owner decision D3).

## Planned changes

Under `apps/aigateway/src/aigateway/`:

- New `routes/legacy_profiles_retired.py`. One plain router (no admin audit route class) registers
  the 13 path × method pairs of spec §2.1 with `include_in_schema=False`. It answers R1 from a static
  table and never reads the body or touches storage.
- `routes/auth.py` and `routes/admin.py`: delete the following.
  - The 13 handlers.
  - Their request and response schemas: `AdminProfileOut`, `AdminProfileList`,
    `PatchAdminProfileRequest`, `SetAdminApiKeyRequest`, `PatchProfileRequest`, `SetApiKeyRequest`,
    `StartAuthRequest`.
  - `_begin_legacy_pending`, and the route-module helpers only those handlers used.
  - The OAuth callbacks and `exchange-code` stay.
- `main.py`: mount the retired router.
- `apps/aigateway-ui/src/lib/aigateway/schema.d.ts`: regenerate it with the pinned
  `openapi-typescript`.

Tests follow the owner-approved test map, which lives in the team notes as
`stage_e3_route_retirement_test_map.md`. Owner decisions, 2026-10-18:

- **D1:** retire a race whose only legacy actor is a retired route.
- **D2:** adapt facade-pending and legacy-pending callback tests with test seeders.
- **D3:** move the dead core layer to E3b.
- **D4:** add tests for the gaps the retirements open.

The manifest `.claude/test-change-approvals/OME-1651.json` is built at PR-open.

## Test plan

RED first, in the new `tests/unit/test_legacy_profile_routes_retired.py`:

- Each of the 13 path × method pairs answers 410 with the R1 refusal in the gateway's error
  envelope: `{"detail": {"code", "message", "successor"}}`. The response carries
  `Cache-Control: private, no-store`.
  - This holds with no body, with a body, with a malformed body (410, not 422), and with no JWT.
- A retired route issues no SQL statement and writes no admin audit record.
- Every named successor is a live route in OpenAPI.
- OpenAPI has no `/profiles` path and none of the retired schemas. The callbacks are not retired.
  `POST …/profiles/import` stays 405.
- The successor routes' OpenAPI fragments are byte-identical to `origin/main`. This is checked by
  diffing the dumped schema.
- D4 additions:
  - A native OAuth start gives 404 for an unknown provider and 400 for a non-OAuth provider.
  - A key the admin writes through D18 is visible to the tenant.
  - A D18 delete removes the tenant blob.
  - A native Gemini API key works.
  - The tenant successor writers' handling of `defaults` is pinned as it is on `origin/main`:
    accepted and ignored (only the D18 admin PUT refuses it with 422).

## Acceptance

- `uv run .claude/scripts/run_gates.py aigateway --base origin/main` is green, with the E3 manifest.
- `npm run typecheck` in `apps/aigateway-ui` is green against the regenerated `schema.d.ts`.
- `git grep -n 'profiles' -- apps/aigateway/src/aigateway/routes` names only the retired table and
  comments.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned. New: `routes/legacy_profiles_retired.py`,
  `tests/unit/oauth_flow_seed.py` (the D2 seeder that reproduces the retired start's storage
  effects), `tests/unit/test_legacy_profile_routes_retired.py`,
  `tests/unit/test_profile_retirement_successor_coverage.py`. 55 prior test files migrated per the
  map (unit, integration, live). Six are docstring-only now: `test_profile_admin_shells`,
  `test_profile_writers_refuse_saved_defaults`, `test_profile_api_key_cancellation_ordering`,
  `test_profile_api_key_validation`, `test_profile_api_key_races`,
  `core/provider_access/test_connection_backed_refresh`; plus the PG files
  `test_writer_floor_postgres` and `test_writer_floor_refresh_postgres`.
- **Commits:** one commit on `OME-1651-retire-profile-routes`, `refactor(aigateway)!: retire the legacy Profile HTTP routes with a 410 (Stage E, E3)`.
- **Gates:** ruff, ruff format, pyright, no-enterprise and pytest with coverage ≥ 80 are green
  (unit suite 6045 passed, 2 skipped). PostgreSQL integration with `AIGW_TEST_PG=1`: 11 passed.
  Live tests collect and skip without `AIGW_LIVE`. `npm run typecheck` in `apps/aigateway-ui` is
  green. The append-only check is green with the manifest `.claude/test-change-approvals/OME-1651.json` (50 files).
- **OpenAPI:** against `origin/main`, exactly the 9 Profile path templates (13 operations) are gone
  and no path is new or changed. Gone schemas: the 7 R1 schemas, plus `ProfileDefaults` and
  `ProfileState`, which only `AdminProfileOut` referenced.
- **Decisions during the work (owner, 2026-10-18):**
  - The native tenant writers keep accepting and ignoring unknown fields, `defaults` included.
    They declare no such field and Pydantic drops extras by default, so refusing it would change
    the contract of live routes; no in-repo client sends it.
  - The manifest also approves assertion edits the map did not list one by one. Each checked the
    HTTP answer of a retired route during setup, or its projection: `start.status_code == 201`
    (PG races 186 and 379), the full `/status` body reduced to the document state, and the
    `profile_id` of the start answer. No storage-state assertion was weakened.
  - Three tests keep a legacy core operation (`set_api_key` through the Profile credential admin)
    as their intruder: `test_writer_floor_legacy_oauth` 80 and
    `test_connection_backed_shared_addresses` 178 and 211. The operation is core, not a retired
    route, so D1 does not retire them; they are removed with that operation in E3b (D3).
- **Deviations:** R1 shows the refusal as a top-level object. The owner chose the gateway's
  standard `{"detail": {...}}` envelope on 2026-10-18, because the SDK
  (`_engine/catalog.py:284`) and the Admin UI (`errors.ts`) decode `detail.code`.
