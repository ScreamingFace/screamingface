---
ticket: OME-1323
stack: aigateway
status: in_progress
started: 2026-09-24
finished:
---

# OME-1323 — AIGateway: remove saved Profile defaults while preserving global cache keys

## Intent

This is the gateway part of Stage C (D2) of `OME-1138`. Request parameters are the caller's: each
request sends them or omits them, and system instructions arrive as system-role entries in
`messages`. The chat route stops reading stored Profile defaults before the cache (op 1,
`apply_defaults`, and the second merge after an index-read failure). Every writer of saved defaults
answers a body that carries a `defaults` property, including `null`, with a secret-safe `422` before
any side effect. Historical Profile documents, credential locators, the legacy routes, `X-Profile`
and every response DTO stay. The Admin UI already sends only `{ "api_key": … }` (`OME-1322`, PR
#1043).

**Owner cache condition.** `KEY_REVISION`, `PARAMETER_CONTRACT_REVISION`, provider versions,
projections and adapter revisions, the key dictionary, the canonical hash and existing rows are not
changed, and the cache is not reset. A request without stored defaults keys byte-identically before
and after the change. If parity or projection-to-dispatch correspondence fails, the unit stops for
the owner.

## Design gate and requirement sources

- The Stage C target was accepted and merged in the design catalog (`screamingface-design` PR #24,
  merge `1de95b53`). No new design branch is opened.
- Spec `docs/spec/2026-09-09-OME-1138-converge-connections.md` §3.7, §5 (row C) and §11; plan
  `docs/plan/2026-09-09-OME-1138-converge-connections.md` §2 (S11) and §3.
- **Reconciliation recorded here (owner-accepted in the design review).** Spec §3.7 lists
  `defaults_for`, `apply_defaults` and `CredentialTarget.defaults` among the cutover removals. The
  accepted target keeps op 1 (`defaults_for`), `apply_defaults`, the plugin veto
  `should_apply_profile_default` and `CredentialTarget.defaults` declared, with no production caller,
  until Stage E removes the Profile vocabulary. Their own unit tests stay as they are. Stage C removes
  their call from the chat route, the merge, the `invalid_profile_defaults` attribution and the
  request fields. Spec §3.7 and plan §1/§3 are updated to say so.

## Planned changes

Source (`apps/aigateway/src/aigateway/`):

- `routes/chat.py`: remove the Stage 1 `defaults_for` read, `apply_defaults`, the bypass-path second
  merge and the `default_paths` attribution/logging. Classification failures render
  `unsupported_parameters` with the caller's paths exactly as today.
- `routes/chat_cache_stage.py`: remove `defaults_unreadable_bypass`, which has no other caller. The
  published reason vocabulary is unchanged.
- `routes/chat_profile_defaults.py`: docstring only. The two names stay as compatibility shims with
  no production caller until Stage E.
- `routes/saved_defaults_refusal.py` (new): one check shared by the five writers. A raw JSON body
  that carries `defaults` gets `422 {"code": "defaults_not_accepted", "field": "defaults", …}`. The
  body names only the field, and nothing is logged.
- `routes/auth.py`, `routes/admin.py`, `core/admin_schemas.py`: drop `defaults` from the five request
  models (`SetApiKeyRequest`, `StartAuthRequest`, `PatchProfileRequest`, `SetAdminApiKeyRequest`,
  `PatchAdminProfileRequest`), call the refusal first in each handler, and stop forwarding defaults.
  Response DTOs are unchanged.
- `core/provider_access/ports.py`, `profile_admin.py`, `connection_admin.py`: op 8 `set_api_key` loses
  `defaults`. Stored values are kept, and a new Profile starts with empty defaults.
  `api_key_mirror` loses its always-`None` parameter, and `connection_native.py` updates its call.
- `core/provider_access/connection_oauth.py` (`begin_connection_oauth`) and `connection_facade.py`
  (`patch_facade`) lose their `defaults` argument. The index store API (`update_metadata`) is
  unchanged.
- No schema, model or migration change (S1 not triggered). No Tortoise ORM work, so the
  `tortoise-dev` companion does not apply.

Docs: this ledger; `docs/tasks/2026-09-23-OME-1323-remove-profile-defaults.md`; spec §3.7; plan §1
row C and §3.

## Test plan

Order: N2 is the first tracked change, then the RED and baseline tests below, then the
implementation. Tests are append-only apart from the owner-accepted mapping of **22 retire / 24
adapt / 33 keep**, 79 tests in 30 files (listed at the end of this ledger). The map was accepted as
22 / 23 / 33 (78 tests in 29 files); A24 was added during GREEN on the owner's decision.

1. **N2 baseline**, `tests/unit/test_chat_global_cache_key_parity.py`, never edited after it lands.
   For three exact bodies (bare, `temperature: 0.2`, `max_tokens: 64`) it pins the literal canonical
   key material and its SHA-256, the route building that material, `miss` then `hit`, one dispatch
   and one row.
2. **RED** (fail today, pass after):
   - **N1a:** two Profiles with different historical defaults and the same bare request share one
     key (the N2 bare digest), miss then hit, one dispatch, nothing saved dispatched.
   - **N1c:** streaming on a Profile with historical defaults: `stream` bypass, and nothing saved
     reaches the stream.
   - **N3:** a profile index that cannot be read before planning causes no bypass, and a hit reads no
     index. Another Profile's different request gets no wrong hit.
   - **N4:** historical invalid stored defaults (codex `temperature`, anthropic `temperature=1.5`,
     `reasoning_effort="extreme"`) no longer refuse: 200, value not dispatched.
   - **N5:** each of the five writers answers `defaults` present (a value or `null`) with `422`,
     before any key validation, index or blob write or pending entry. The body names only the
     field, and neither the body nor the log carries the key, prompt or value.
   - **N8** (added after review): the same refusal when the REST of the body is invalid — the PUTs
     and the OAuth start without their required `api_key`/`name`, the PATCHes with a non-string
     label — so body validation never answers first; an admin refusal is audited with its actor.
   - **N11** (added after review round 4): a non-JSON body nested too deeply to parse (`text/plain`
     or no content type) keeps FastAPI's ordinary 422 on every writer, never a 500.
3. **Baselines** (green before and after):
   - **N1b:** distinct explicit caller system messages key distinctly, and each dispatches exactly the
     caller's message.
   - **N5o:** the five writers accept `defaults` omitted.
   - **N6:** a label-only PATCH keeps historical defaults.
   - **N7:** key rotation keeps directly seeded historical defaults byte-identical.
   - **N9** (added after review): the same bodies without authentication get `401`, never the
     refusal.
   - **N10** (added after review): a body that is not JSON keeps FastAPI's ordinary 422, never a 500.
4. **Retire / adapt** exactly per the mapping below. Before/With labels were verified on `634f8e7e`
   before any change.

## Acceptance

- N2 green on the unchanged gateway (done, see Outcome) and unmodified afterwards (same SHA-256).
- Every RED test fails for the stated reason before the change and passes after; every baseline is
  green before and after.
- Saved defaults never influence a request; explicit parameters validate, key and dispatch as
  today; no ignored write; no wrong cache hit.
- Card gates green: `ruff check`, `ruff format --check`, `pyright`, `scripts/check_no_enterprise.py`,
  `pytest --cov=aigateway --cov-fail-under=80`, plus the `needs_postgres` lane.
- Admin UI compatibility is checked against its source payload. Before the refusal is enabled on dev,
  the **running** console is checked separately, because a source merge is not a rollout.

## Test mapping (22 retire / 24 adapt / 33 keep; accepted as 22 / 23 / 33, A24 added during GREEN)

Paths are relative to `apps/aigateway/tests/unit/`.

**Retire (22)**: each asserts the behaviour Stage C removes.

| # | Test | Replaced by |
| --- | --- | --- |
| R1 | `test_chat_global_cache_effective_request.py::test_two_profiles_with_different_system_prompts_do_not_share_a_key` | N1a |
| R2 | `…effective_request.py::test_a_bare_row_filled_without_defaults_is_not_served_to_a_profile_that_has_them` | N1a |
| R3 | `…effective_request.py::test_the_same_effective_request_shares_a_row_however_the_value_arrived` | N1a + N1b |
| R4 | `…effective_request.py::test_a_miss_dispatches_exactly_one_system_message` | N1a + N1b |
| R5 | `…effective_request.py::test_an_unreadable_profile_index_bypasses_the_cache_and_still_dispatches_defaults` | N3 |
| R6 | `test_chat_profile_default_validation.py::test_a_default_the_provider_does_not_enable_is_refused` | N4 |
| R7 | `…validation.py::test_a_default_outside_the_provider_narrowed_schema_is_refused` | N4 |
| R8 | `…validation.py::test_a_default_outside_the_schema_enum_is_refused` | N4 |
| R9 | `…validation.py::test_the_rejection_is_attributed_to_its_real_source` | none: attribution retires; caller rejection covered by A4 and route tests |
| R10 | `…validation.py::test_a_valid_default_still_merges_and_dispatches` | N1a |
| R11 | `…validation.py::test_a_valid_default_survives_the_gate_and_its_downstream_rename` | A7 + codex projection tests |
| R12 | `…validation.py::test_structural_defaults_still_need_no_rule` | N1a; A3 |
| R13 | `test_chat_x_profile.py::test_chat_merges_profile_defaults` | N1a |
| R14 | `test_chat_x_profile.py::test_chat_skips_anthropic_profile_reasoning_default` | N1a (veto hook test K8 stays) |
| R15 | `openai/test_openai_route_global_cache_key_material.py::test_a_profile_default_max_tokens_isolates_and_an_explicit_equal_value_shares` | N1a + N2 + N5 |
| R16 | `openai/…key_material.py::test_two_stored_system_prompts_isolate_through_the_effective_messages` | N1a + N1b + N5 |
| R17 | `anthropic/test_anthropic_thinking_conflict.py::test_a_conflicting_profile_default_still_refuses_and_names_the_profile` | none: attribution removed; caller-side conflict tests stay |
| R18 | `test_api_key_routes.py::test_set_api_key_accepts_defaults` | N5 |
| R19 | `test_admin_profile_routes.py::test_profile_defaults_can_be_edited` | N5 + N6 |
| R20 | `test_auth_routes.py::test_patch_updates_defaults` | N5 + N6 |
| R21 | `core/provider_access/test_connection_backed_oauth_flow.py::test_start_with_defaults_replaces_the_documents_defaults_only` | N5 (OAuth start, migrated pair) |
| R22 | `core/provider_access/test_provider_credential_admin.py::test_set_api_key_replaces_defaults_wholesale_and_keeps_them_when_omitted` | N7 |

**Adapt (24)**: keep the point, change setup or text. "Before" rows pass on today's code; "With"
rows land with the change.

| # | Test | Change | When |
| --- | --- | --- | --- |
| A1 | `…effective_request.py::test_a_profile_that_cannot_authenticate_still_gets_a_hit` | docstring + module note: no pre-cache Profile read remains | With |
| A2 | `…effective_request.py::test_a_timeout_default_changes_no_key_and_causes_no_bypass` | → `test_a_caller_timeout_…`; caller sends `timeout` | Before |
| A3 | `…effective_request.py::test_a_timeout_default_still_reaches_the_provider_on_a_miss` | → `test_a_caller_timeout_…`; caller sends `timeout` | Before |
| A4 | `…validation.py::test_a_caller_fault_outranks_a_profile_fault` | → `test_a_caller_fault_is_reported_alone_beside_an_invalid_historical_default`; comment only | Before |
| A5 | `…validation.py::test_the_refusal_precedes_provider_preparation_and_everything_after_it` | caller `temperature` at the same classifier seam | Before |
| A6 | `…validation.py::test_the_refusal_precedes_credential_access` | caller `temperature`, 400 not 401 | Before |
| A7 | `test_chat_x_profile.py::test_chat_maps_codex_reasoning_effort_to_reasoning` | `reasoning_effort` in the body | Before |
| A8 | `openai/test_openai_route_global_cache_modifier.py::test_a_profile_defaulted_ceiling_is_refused_under_an_enabled_modifier` | → `test_an_explicit_ceiling_…`; body `max_tokens` | Before |
| A9 | `test_api_key_routes.py::test_patch_profile_preserves_api_key_auth_type` | PATCH `account_label` | Before |
| A10 | `test_api_key_validation_writer_integration.py::test_profile_set_invalid_preserves_existing_profile_and_key` | no `defaults` in PUT bodies | Before |
| A11 | `test_profile_api_key_validation.py::test_profile_validation_failure_precedes_every_side_effect` | no `defaults` in PUT bodies | Before |
| A12 | `core/provider_access/test_connection_backed_facades.py::test_patch_keeps_metadata_on_the_document_and_renders_the_connection_state` | PATCH label; historical defaults kept | Before |
| A13 | `…facades.py::test_patch_is_404_when_a_migrated_pair_has_no_effective_connection` | PATCH label | Before |
| A14 | `…facades.py::test_patch_of_an_unmigrated_pair_keeps_the_legacy_body` | PATCH label | Before |
| A15 | `test_profile_admin_shells.py::test_the_tenant_put_validates_then_calls_the_boundary_and_returns_its_projection` | no `defaults` in body/kwargs | With |
| A16 | `…admin_shells.py::test_the_tenant_put_passes_omitted_defaults_through_as_none` | → `test_the_tenant_put_passes_no_defaults_to_the_boundary` | With |
| A17 | `…admin_shells.py::test_the_admin_shells_address_the_tenant_account_through_the_boundary` | admin PUT kwargs without `defaults` | With |
| A18 | `core/provider_access/test_provider_credential_admin.py::test_set_api_key_publishes_an_authenticated_legacy_profile_and_its_blob` | op without `defaults`; stored empty | Before |
| A19 | `…credential_admin.py::test_set_api_key_refuses_an_unknown_provider` | drop `defaults=None` | With |
| A20 | `…credential_admin.py::test_set_api_key_refuses_a_provider_without_an_api_key_strategy` | drop `defaults=None` | With |
| A21 | `core/provider_access/test_connection_backed_admin.py::test_set_api_key_writes_the_effective_connection_and_mirrors_the_document` | op without `defaults`; historical defaults kept | Before |
| A22 | `core/provider_access/test_provider_access_port_shape.py::test_set_api_key_is_pair_addressed_with_the_window_compatible_keywords` | drop `("defaults", KW)` | With |
| A23 | `openai/…key_material.py::test_a_hit_reads_no_openai_credential_dispatches_nothing_and_reports_no_accounting` | docstring: no Profile read supplements the request | With |
| A24 | `huggingface/test_huggingface_route_global_cache.py::test_a_hit_reads_no_huggingface_provider_credential` | not in the accepted map; found red in the first full run after the change. Its closing `assert services` pinned the retired pre-cache profile-index read. Name and miss control kept; docstring rewritten; the assertion becomes `assert not services` (a hit reads no `credential_blobs` row at all). Owner decision 2026-09-24 | With |

Non-test helpers adapted **With** the change: `openai/route_harness.py` `seed_profile(defaults=)`,
and the `setdefault("defaults", None)` lines in `core/provider_access/test_provider_credential_admin.py`
and `core/provider_access/connection_backed_admin_probes.py`. Stale module docstrings of
`test_chat_global_cache_effective_request.py` and `test_chat_profile_default_validation.py` are
rewritten.

**Keep (33)**, unchanged. They cover the `Formatter(defaults=…)` text matches in
`test_call_context.py` and `test_trace_context.py`; the `apply_defaults`, provenance, `defaults_for`,
resolve-contract and shim suites (which stay until Stage E); historical-defaults reads and
round-trips (`test_profile_index.py`, resolve contracts, backfill); no-leak listings; and the
response DTO listings.

## Outcome (fill at the end — required before COMMIT)

- **N2 baseline (first tracked change, before any gateway code):** copied byte-identical from the
  accepted file. SHA-256 `df8468374ef62c00637346713eeebc63391b550d35bb48ff7414faf8a9eaa496`. On
  `a1719014`, where `apps/aigateway` is unchanged since `634f8e7e`: 6 passed. The full unchanged
  suite with N2 is also green: 4918 passed, 89 skipped, coverage 92.90%.
- **RED / GREEN evidence (before the change, on the unchanged gateway):**
  - N1a failed (`miss`/`miss`: the two Profiles keyed apart); N1c failed (stored values reached the
    stream body); N3 failed (bypass `cache_unavailable`); N4 failed (400 `invalid_profile_defaults`);
    N5 failed ×10 (each writer accepted or processed `defaults`). All for the stated reason.
  - N1b, N5o (×5), N6 (×2) and N7 (×2) passed before the change. N2: 6 passed (above).
  - After the change: N1a ×2, N1b, N1c, N3, N4 ×3, N5 ×10, N5o ×5, N6 ×2, N7 ×2 and N2 ×6 pass.
    N2 is byte-identical afterwards (same SHA-256), so the three pinned keys did not move.
  - Review fix (the refusal ran inside the handler): N8 failed ×10 before it — FastAPI's generic
    422 (`missing` / `string_type`) answered first, and admin refusals were audited as
    `<unidentified>`. In the assembled app `_redact_validation_errors` already strips `input`, so no
    submitted value reached that response; on a bare FastAPI app it would. N9 ×5 and N10 ×5 passed
    before the fix. After it, N5–N10 all pass (39 in the file).
- **Actual files** (`apps/aigateway/`):
  - Source: `routes/chat.py`, `routes/chat_cache_stage.py`, `routes/chat_profile_defaults.py`
    (docstring only), `routes/saved_defaults_refusal.py` (new), `routes/auth.py`, `routes/admin.py`,
    `core/admin_schemas.py`, `core/provider_access/{ports,profile_admin,connection_admin,
    connection_native,connection_oauth,connection_facade}.py`, `core/provider_access/profile_defaults.py`
    and `core/request_cache/global_keys.py` (comments only); after review also
    `core/request_cache/global_plan.py` and `plugins/openai_provider/runtime_guard.py` (comments
    only). No schema, model or migration change.
  - New tests: `tests/unit/test_chat_global_cache_key_parity.py` (N2),
    `tests/unit/test_chat_saved_defaults_are_not_merged.py` (N1a, N1b, N1c, N3, N4),
    `tests/unit/test_profile_writers_refuse_saved_defaults.py` (N5, N5o, N6, N7, N8, N9, N10, N11).
  - Retired / adapted exactly per the mapping, plus A24 and the listed non-test helpers.
  - Admin UI (after review round 3): `apps/aigateway-ui/src/lib/aigateway/schema.d.ts`, regenerated
    with the pinned `openapi-typescript` 7.13.0 from this working tree's OpenAPI (over `a1719014`;
    semantically identical to the OpenAPI pinned before and after the dependency move). The five
    writer request models (`SetApiKeyRequest`, `StartAuthRequest`, `PatchProfileRequest`,
    `SetAdminApiKeyRequest`, `PatchAdminProfileRequest`) lose `defaults?`; `AdminProfileOut.defaults`
    and `ProfileDefaults` stay. The diff also carries the `GET /v1/provider-access` types
    (`ProviderAccessAvailability`, `ProviderAccessAvailabilityRow`, the operation), which A4
    (`OME-1244`, PR #1006) added to OpenAPI without regenerating the file; nothing else changed
    (+65 / −5). No UI source references the new types.
  - Docs: this ledger, the task mirror, `apps/aigateway/DEPLOYMENT.md` (response-cache sections),
    spec §3.2, §3.3 (op 8), §3.5 (HTTP window exception and admin successor), §3.7, §3.9 (chat and
    Admin UI rows), §4, §5 (row C), §8 (D8, D18, D20), §9 (S7) and §10 (index reads), plan §1 (P1,
    A2–A4, B, C), §2 (S7a/S7), §3 (B, C, D, E) and the current-source preservation checks; both
    `updated:` dates.
- **Behaviour:** chat reads no stored Profile defaults and merges nothing, before or after the cache;
  a hit reads no profile index at all. The five writers (tenant/admin API-key PUT, OAuth start,
  tenant/admin PATCH) answer a body carrying a `defaults` member, `null` included, with
  `422 {"code": "defaults_not_accepted", "field": "defaults", "message": …}` before the request
  model is validated, key validation, any index or blob write, a pending entry or the OAuth
  listener; nothing is echoed or logged. The refusal is a dependency nested under the auth
  dependency (`AccountRefusingSavedDefaults`, `AdminRefusingSavedDefaults`): FastAPI solves it after
  authentication and before body parameters, and the admin variant names the actor first, so the
  audit line records who was refused. OpenAPI is byte-identical before and after that move.
  Omitting `defaults` behaves as before, and historical stored values are kept untouched. Response
  DTOs are unchanged (`AdminProfileOut.defaults` and the tenant listing still show stored values).
  The 400 `unsupported_parameters` body for a caller fault is byte-identical to before.
- **Availability change (documented in `routes/chat.py`):** an unreadable profile index no longer
  forces a cache bypass (`cache_unavailable`), because nothing before the lookup reads it. On a miss
  the same fault can still fail credential resolution, exactly as before.
- **Cache:** `KEY_REVISION`, `PARAMETER_CONTRACT_REVISION`, provider versions, projections and adapter
  revisions, the key dictionary, the hash and existing rows are unchanged; no reset.
- **Admin UI compatibility:** in source the console calls only the admin API-key PUT among the closed
  writers, with a body of exactly `{ "api_key" }` (`OME-1322`). The **running** dev console has not
  been checked here; that check precedes enabling the refusal on dev.
- **Commit:** this ledger ships in the single authorised commit
  `feat(aigateway): remove saved profile defaults` (`Refs: OME-1323`).
- **Gates** (re-run 2026-09-24 after the review fix, on the working tree over `a1719014`):
  - `run_gates.py aigateway --skip-append-only`: ALL GATES GREEN — `ruff check`, `ruff format
    --check`, `pyright` (0 errors), `check_no_enterprise.py`, `pytest --cov=aigateway
    --cov-fail-under=80`. The same pytest command run directly: 4943 passed, 89 skipped, coverage
    92.87%. The writers' refusal file alone: 39 passed. Re-run after review round 4 (N11 and the
    `RecursionError` fix): ALL GATES GREEN again; directly 4953 passed, 89 skipped, 92.87%; the
    writers' file 49 passed; the append-only check lists the same 20 mapped files.
  - The append-only check alone: red, listing 20 modified prior test files, every one named in the
    map (the mapped files and A24) — the owner-accepted mapping, not an unreviewed change. The gate
    was not weakened.
  - CI auth-surface lane (`tests/unit/auth`, `test_auth_routes.py`, `--cov-fail-under=80`): 238
    passed, 93.27%.
  - OpenAPI document before and after moving the refusal into a dependency: byte-identical.
  - PostgreSQL lane (`AIGW_TEST_PG=1 pytest -m needs_postgres`): 52 passed with a `pg_dump` 16
    client. With the machine's default `pg_dump` 15 the five `test_cache_snapshot_upload_postgres.py`
    tests fail against the `postgres:16-alpine` container; the same five fail on a clean `a1719014`,
    so that is a local client-version mismatch, not this change.
  - Mapping reconciled mechanically against the map (with A24): all 22 retired tests are gone, all 24
    adapted tests exist under their target names, and all 33 kept tests are byte-identical to the
    base commit (function source compared by AST). The three N2 digests recompute with `shasum` from
    the canonical strings.
  - N2 SHA-256 after the change: `df8468374ef62c00637346713eeebc63391b550d35bb48ff7414faf8a9eaa496`
    (unchanged).
  - Admin UI, after the `schema.d.ts` regeneration: `run_gates.py aigateway-ui` ALL GATES GREEN —
    the append-only check, `npm ci`, `npm run lint`, `npm run lint:css`, `npm run typecheck`,
    `npm run build`, `npm run test:ci` (238 tests, 0 failures). Run on Node 24.15.0 and again on
    23.6.0; CI pins Node 22 through `.nvmrc`, which is not installed locally. A second generation
    from the same OpenAPI is byte-identical to the working-tree file.
- **Deviations:**
  - The ledger was opened right after the N2 transplant, not before it, following the owner's
    explicit order ("first transplant and run N2, then open the ledger").
  - A24 (the HuggingFace hit test) was not in the accepted map. It was found red in the first full
    run after the change and adapted on the owner's decision (see the mapping).
  - R21 was replaced in place by the migrated-pair N5 test
    (`test_start_with_defaults_on_a_migrated_pair_is_refused_and_changes_nothing`) instead of being
    deleted outright; it asserts the 422 for a value and for `null` and that nothing changed.
  - The module docstring of `openai/test_openai_route_global_cache_key_material.py` was rewritten
    alongside the A23 test docstring (the map named only the latter). Imports, constants and
    section headers left unused by the retirements were removed.
  - The `unsupported_parameters` message string now also lives in the retained
    `chat_profile_defaults` shim until stage E removes it.
  - The append-only check is red by design: it lists exactly the mapped files and A24.
  - Review round 1, 2026-09-24: the first implementation refused `defaults` inside each handler, so
    an incomplete body got FastAPI's generic validation 422 (the gateway already redacts its
    `input`) and the admin audit lost its actor. The refusal moved into a dependency nested under
    authentication (N8–N10 added). The round also corrected the stale source comments, spec
    §3.2/§3.3/§3.9/§4/§5, the plan's row C and preservation checks, and the map's totals after A24.
  - Review round 2, 2026-09-24 (docs only; the code was accepted): statements the first pass had
    missed were corrected — the plan's A2–B rows still said "local" or "not started" although
    they merged as PRs #981, #992, #1006/#1007 and #1029; the spec still said the Admin UI sends
    defaults, still framed its attach/replace move as a Stage C step, and D20 still called D11
    open; the plan's S7 row joined the C fieldset drop with the D18 call move (now S7a and S7);
    §10 still described two index reads per chat request; both `updated:` dates were 2026-09-16.
    Whether spec and plan are now fully consistent is the owner's review to settle.
  - Review round 3, 2026-09-24: `schema.d.ts` was still the pre-change generation although spec §4
    and §10 require regenerating it with each OpenAPI change; it was regenerated (see Actual files).
    Folding in A4's missed `provider-access` types was the owner's choice over a hand edit of only
    the five `defaults` lines, so the file stays exact generator output. Spec §3.5 no longer says
    every Profile route is unchanged in the window: the five writers' `defaults` refusal from stage
    C is named as the one deliberate exception.
  - Review round 4, 2026-09-24 (a four-lane review of the implementation against the task prompt,
    each lane's findings independently re-checked): (a) the refusal caught only `ValueError`, so a
    non-JSON body nested too deeply for `json.loads` raised `RecursionError` and every writer
    answered 500 where the base answered 422 — it now also catches `RecursionError` (N11, RED ×10
    before the fix); (b) `apps/aigateway/DEPLOYMENT.md` still told operators that the key covers
    merged profile defaults, that a hit reads the profile index and that an unreadable index
    bypasses the cache — its four passages now describe the Stage C behaviour; (c) the new
    availability comment in `routes/chat.py` used an invented anchor and now uses `AIDEV-NOTE:`;
    (d) spec §3.9's chat row now also gives the path from C. Accounting note, not a change: the
    byte-identical `core/provider_access/test_connection_backed_admin_contract.py` imports
    `test_provider_credential_admin` and re-runs its tests against the Connection backing, so the
    retired R22 and the adapted A18–A20 are also collected there; at the map's function level the
    counts stay 22 / 24 / 33.
  - Final review tightened the deployment wording: the global key combines the caller body with the
    provider's declared projection of later output-affecting normalization. It is not a claim that
    the pre-cache body is literally the upstream request. No runtime behavior changed.
