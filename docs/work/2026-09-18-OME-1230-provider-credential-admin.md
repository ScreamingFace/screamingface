---
ticket: OME-1230
stack: aigateway
status: in_progress   # planned | in_progress | done | blocked
started: 2026-09-18
finished:
---

# OME-1230 — Add the provider-credential admin interface and reduce the Profile management routes to shells

## Intent

Stage A3 of `OME-1138` (adapter-first convergence). A1 (`OME-1200`/`OME-1204`) declared
`ProviderCredentialAdmin` (ops 7 `list`, 8 `set_api_key`, 9 `delete`) and
`ProviderAccess.availability` (op 6) in `core/provider_access/ports.py`; A2 (`OME-1207`) moved
the runtime consumers onto `provider_access`. The credential write bodies still live in
`routes/auth.py` as two module-level facades (`upsert_api_key_profile`,
`delete_profile_for_account`) that the tenant `PUT`/`DELETE` routes and `routes/admin.py` call
directly; the admin listing reads `ProfileIndexStore` directly; `availability` raises
`NotImplementedError`. This unit moves the bodies behind the declared interface, turns the
management routes into thin compatibility shells over it, and implements `availability`
gateway-side, so Stage B (`OME-1208`) can swap the backing behind both interfaces without
touching a route. Every client-visible contract stays byte-identical; backing stays the legacy
Profile.

Prerequisite (process gate): the catalog card
`product/aigateway/protocol/provider-credential-admin` describing this boundary is accepted and
committed in the design repository before any code below is written.

## Planned changes

Production (every file ≤450 lines; no leading underscore in `core/provider_access/` module names):

- NEW `apps/aigateway/src/aigateway/core/provider_access/profile_admin.py` — the Profile-backed
  `ProviderCredentialAdmin` (`ProfileBackedCredentialAdmin(app)`, accessor
  `provider_credential_admin_for(app)`): the store half of `upsert_api_key_profile` (normalised
  key in; strategy via `plugin_base.credential_strategy_from`; index CAS first, blob second,
  one transaction; delete-wins → `WriteConflict("superseded")`; CAS exhaustion →
  `WriteConflict("retry_exhausted")`; persistence failure → `CredentialStoreUnavailable`;
  wholesale defaults replacement; `legacy_name or "default"`), the store half of
  `delete_profile_for_account`, and `list` projecting the account's `Profile` rows.
- `apps/aigateway/src/aigateway/core/provider_access/types.py` — `CredentialSummary` gains the
  window-only legacy projection (fork F1 below; removal point Stage E, `OME-1209`); new refusals
  `ProviderUnknown(provider)` and `CredentialStoreUnavailable(description)`.
- `apps/aigateway/src/aigateway/core/provider_access/profile_backed.py` — `availability` body:
  per-provider aggregation of the account's Profile states (authenticated > pending > error;
  none → `not_connected`; `needs_reauth` never emitted), no strategy build, no refresh.
- `apps/aigateway/src/aigateway/core/provider_access/__init__.py` — exports.
- `apps/aigateway/src/aigateway/routes/provider_access_http.py` — rows for the new refusals with
  today's bodies verbatim (`unknown_provider`, `profile_not_found`, `credential_store_unavailable`);
  see fork F3 for the two provider-less DELETE shapes.
- `apps/aigateway/src/aigateway/routes/auth.py` — `upsert_api_key_profile` becomes the ONE shared
  shell both PUT routes keep calling: normalise + validate the key (edge half, unchanged HTTP
  shapes from `routes/api_key_validation.py`), call the boundary inside `refusals_as_http()`,
  then the post-commit edge half (pop stale pending OAuth flows, close loopback listeners),
  return the projection. `delete_profile_for_account` becomes a shell the same way. The listing
  routes render the projection from `list()`. The file shrinks and gains no logic.
- `apps/aigateway/src/aigateway/routes/admin.py` — `PUT`, `DELETE` and the listing become shells
  over the interface (imports of the two shell names from `.auth` may stay: no test patches
  them); authorization, audit and the `AdminProfileOut`/`AdminProfileList` DTOs unchanged.
- `apps/aigateway/src/aigateway/main.py` — `app.state.provider_credential_admin` beside
  `provider_access`; the `CredentialBlobMutationConflict` handler stays (window).

Tests (new files; prior suites untouched unless fork F2 is decided otherwise):

- NEW `tests/unit/core/provider_access/test_provider_credential_admin.py` — ops 7–9 contract at
  the adapter seam, including the OME-307 ordering, wholesale defaults, both conflicts, the
  no-compensation rollback and no secret in any summary.
- NEW `tests/unit/core/provider_access/test_provider_access_availability.py` — op 6 golden
  equivalence with the Engine rule and the no-side-effect pins.
- NEW listing-parity and shell pins at the route seam (tenant and admin), asserting today's
  JSON byte for byte and the legacy error bodies.

Docs: this ledger, `docs/tasks/2026-09-18-OME-1230-provider-credential-admin.md`, the A3 status
row in the OME-1138 plan.

### Design notes (2026-09-18, recorded at the gate, before approval)

Evidence: `routes/auth.py:1228-1402`, `routes/admin.py:243-337`, `routes/api_key_validation.py`,
`routes/credential_persistence.py`, `core/provider_access/{ports,types,profile_authorize}.py`,
`routes/provider_access_http.py`, spec §3.2–3.4 and the blast-radius rows for the tenant and
admin Profile routes, all at `248b0b6d` (gateway source unchanged on `main` since).

- **Response shapes.** The Protocol's `set_api_key` returns `CredentialSummary` (provider,
  selector, auth_type, state); both PUT routes return the full `Profile` JSON and both listings
  dump whole Profiles (`AdminProfileOut` needs id, account_id, name, account_label, defaults,
  last_refreshed_at). Spec §3.2 already says the summary carries "window-only projection fields"
  that keep the admin JSON byte-identical. Parity is proven by the listing/shell tests.
- **Edge halves.** `require_valid_api_key` and `normalize_api_key` raise HTTP shapes directly and
  live in `routes/`; core must not import routes, so validation stays in the shell before the
  boundary call. `persist_credentials_or_503` also lives in `routes/` but runs INSIDE the
  publication transaction, so the core body gets its own persistence step raising a typed
  refusal rendered 503 `credential_store_unavailable` by the table. The post-commit OAuth
  cleanup (`_pending(...).pop_for_profile`, `_close_loopback_callback`) is OAuth write authority
  (on no port, D14) and stays in the shell after the boundary returns; session invalidation and
  strategy-cache eviction already have core twins in `profile_authorize.py`.
- **Refusals.** Today's bodies: PUT 404 `{"code":"unknown_provider","provider":p}`, 400
  `{"code":"api_key_not_supported","provider":p}` (= `UnsupportedAuthMode` row), 409
  `profile_conflict` (= `WriteConflict` row), 503 `profile_index_conflict` (app handler or
  `WriteConflict("retry_exhausted")` row, same body); DELETE 404 `{"code":"unknown_provider"}`
  and `{"code":"profile_not_found"}` WITHOUT provider/name fields — the existing `TargetMissing`
  row adds them, so DELETE needs its own rows (fork F3).

### Risk register (prior tests that reach into the bodies)

- **R1** `tests/unit/test_api_key_routes.py:286` patches `routes.auth.persist_credentials_or_503`
  to fail the first API-key publication after its transactional write (OME-307 no-compensation
  race). Once the persistence step is in core the patch no longer intercepts → that prior test
  goes RED unless re-expressed at the new seam. Spec §3.4 ("bodies move … with their OME-307
  tests") and plan A3 ("suites green unmodified") disagree here → fork F2.
- **R2** `tests/integration/test_lifecycle_postgres_races.py:551` patches
  `routes.auth.credential_strategy_from` with a no-op strategy around a refresh-vs-delete race.
  After relocation the delete half builds a real strategy and calls `delete_credentials()` on a
  pending profile with no blob; expected green (missing-row delete), to be confirmed in the
  PostgreSQL lane, not assumed.
- **R3** `tests/unit/test_profile_publication_locking.py:197` patches the same persistence name
  for the OAuth completion path only — unaffected (the callback stays in `routes/auth.py`).
- No test patches `upsert_api_key_profile` / `delete_profile_for_account` / `_index_store` on
  either route module (checked).

### Forks for the owner (raised on the issue) — all four DECIDED by the owner on 2026-09-18

Decisions: F1 (b) one opaque window-only projection field, marked for removal at Stage E; F2
re-express the prior OME-307 API-key race test at the admin seam, do not keep the route-module
patch point alive; F3 dedicated rendering rows keep the provider-less DELETE 404 bodies
byte-identical, no provider/name fields added; F4 key validation stays in the shell, moving it
into core is out of scope. Sequence set by the owner: card first (commit, push, design PR), no
application code until the PR is merged AND explicit authorization is given.


- **F1 parity mechanism:** (a) enumerate window-only fields on `CredentialSummary`, or (b) one
  opaque window-only projection attribute holding today's `Profile.model_dump(mode="json")`.
  Recommendation: (b) — one field to retire at E, no per-field drift, parity tests prove it.
- **F2 prior OME-307 API-key race test (R1):** allow re-expression at the new seam (spec) or
  preserve the route-module patch point (plan). Recommendation: re-expression, decided up front,
  mirroring the deviation the owner accepted for A2 — not discovered mid-unit again.
- **F3 provider-less DELETE 404 bodies:** keep byte-identical with dedicated rendering rows for
  the delete refusals (recommendation) or accept additive `provider`/`name` fields (client-visible
  → needs explicit approval; the prompt forbids it by default).
- **F4 key validation placement:** stays in the shell (recommendation); moving
  `api_key_validation` into core is a separate relocation, not A3.

## Test plan

RED first, in this order (each fails against `main` for the right reason before any code):

1. `OME-307` ordering re-asserted at the adapter seam: index CAS first, blob second, one
   transaction, delete-wins.
2. Wholesale defaults replacement on `set_api_key` (a stored default absent from the new
   `defaults` is gone, not merged).
3. Tenant listing JSON parity: `GET /v1/auth/profiles` body byte-identical before and after the
   shells.
4. `availability` builds no credential strategy and triggers no refresh (spy on the strategy
   factory and the refresh path; both untouched).
5. Both conflict contracts through the shells: CAS-retry exhaustion → 503
   `profile_index_conflict`; superseded publish → 409 `profile_conflict`.
6. `availability` golden-equivalent to the Engine `decode_profile_statuses` rule over recorded
   `/v1/auth/profiles` bodies, including the none → `not_connected` row and the rule that
   `needs_reauth` is never emitted.
7. No secret in any `CredentialSummary` or `AvailabilityRow` (masked fields only).
8. Every existing admin, API-key and race pin stays green and unmodified; PostgreSQL lane
   included.

### Baseline (2026-09-18, worktree at `73c5e1e3`, before any code)

- Focused suites the acceptance names — `test_api_key_routes`, `test_admin_profile_routes`,
  `test_profile_api_key_races`, `test_profile_delete_set_race`, `test_api_key_connection_races`,
  `test_profile_publication_locking`, `test_profile_api_key_cancellation_ordering`,
  `test_admin_malformed_json`, `tests/unit/core/provider_access` — **224 passed** (`uv run pytest`).
- PostgreSQL lane: opt-in via `AIGW_TEST_PG=1`, provisioned by testcontainers (Docker); the
  refresh-vs-delete race test named in R2 **1 passed** locally. Command:
  `AIGW_TEST_PG=1 uv run pytest -m needs_postgres tests/integration/test_lifecycle_postgres_races.py -q`.

## Acceptance

- Admin write/delete/listing bodies sit behind `ProviderCredentialAdmin`; the tenant and admin
  management routes are thin shells; `routes/auth.py` shrinks and gains no logic; no oversized
  route file gains independent logic.
- HTTP response bodies, status codes, authorization, audit, sanitization and both conflict
  contracts unchanged; OpenAPI export byte-identical to the branch base.
- `availability` implemented in-process only; no new HTTP route (A4).
- PATCH metadata, OAuth start/callback/refresh, bootstrap, `/v1/oauth/connections*` and token
  delegation stay direct store owners.
- Full aigateway gate green (`run_gates.py aigateway`), PostgreSQL lane green,
  `git diff --check` clean; compatibility exceptions carry explicit removal points.
- Stops for owner review if any step needs a client-visible change, resembles backing
  migration, or deletes rather than shells legacy Profile compatibility.

## Outcome (fill at the end — required before COMMIT)

- **Actual files** (source worktree, branch `OME-1230-provider-credential-admin` off `origin/main`
  `479c1b07`; all uncommitted, nothing staged):
  - Production — NEW `apps/aigateway/src/aigateway/core/provider_access/profile_admin.py`
    (`ProfileBackedCredentialAdmin`, `provider_credential_admin_for`, `summary_of`,
    `persist_credentials_or_refuse`, `DEFAULT_LEGACY_NAME`; 256 lines; the OME-307 INVARIANT
    comments relocated intact); `core/provider_access/types.py` (`CredentialSummary.legacy_projection`,
    `ProviderUnknown`, `CredentialStoreUnavailable`); `core/provider_access/ports.py`
    (`set_api_key` `defaults: RequestDefaults | None`, docstrings); `core/provider_access/profile_backed.py`
    (`availability` + module-level `availability_status`); `core/provider_access/__init__.py` (exports);
    `routes/provider_access_http.py` (`_management_refusal`, `render_legacy_delete_refusal`,
    `legacy_delete_refusals_as_http`); `routes/auth.py` (1424 → 1360 lines: three listings, the
    `upsert_api_key_profile` and `delete_profile_for_account` shells, helpers `_credential_admin`,
    `_projections`); `routes/admin.py` (listing over the boundary; docstring byte-identical);
    `main.py` (`app.state.provider_credential_admin`).
  - Tests — NEW `tests/unit/core/provider_access/test_provider_credential_admin.py` (ops 7–9, OME-307
    ordering, delete-wins, rollback without compensation, both conflicts, no secret in any summary),
    `tests/unit/core/provider_access/test_provider_access_availability.py` (op 6 golden vs the Engine
    rule, no strategy / no write, sorted rows, `needs_reauth` never emitted),
    `tests/unit/core/provider_access/test_provider_access_http_admin_rows.py` (new refusal rows, F3
    delete rows), `tests/unit/test_profile_admin_shells.py` (shell order, refusal rendering, tenant and
    admin listing parity against the real boundary). MODIFIED (F2 only)
    `tests/unit/test_api_key_routes.py` — the OME-307 rollback race test patches
    `profile_admin.persist_credentials_or_refuse` instead of `routes.auth.persist_credentials_or_503`
    (+7/−3 inside the existing test; assertions unchanged).
  - Docs — this ledger; `docs/tasks/2026-09-18-OME-1230-provider-credential-admin.md`. The A3 status
    row in the OME-1138 plan is deferred to the close step (it names the PR).
- **Commits:** design repository `216acd0` — `docs(catalog): describe the provider-credential admin
  boundary` (`Refs: OME-1230`), merged to `main` via PR #21 (merge commit `65ab0b6f`, 2026-09-18);
  design worktree removed. Source repository: one commit on `OME-1230-provider-credential-admin` —
  `feat(aigateway): put the Profile management routes behind the provider-credential admin boundary`
  (`Refs: OME-1230`), authorized by the owner on 2026-09-18 as commit-only after the code stage
  authorization; push and PR await separate authorization; sha recorded in the close comment.
- **Gates** (worktree base `479c1b07`, 2026-09-18):
  - RED first: the four new suites failed on `ImportError: CredentialStoreUnavailable` before any code.
  - `uv run .claude/scripts/run_gates.py aigateway --base 479c1b07` — append-only check **RED** on
    `tests/unit/test_api_key_routes.py` (the owner-approved F2 re-expression; recorded, not hidden);
    with `--skip-append-only`: ruff check ✓ · ruff format --check ✓ · pyright ✓ (0 errors) ·
    check_no_enterprise ✓ · `pytest --cov=aigateway --cov-fail-under=80` ✓ — **4654 passed, 79 skipped**,
    coverage **92.52 %**.
  - PostgreSQL lane `AIGW_TEST_PG=1 … test_lifecycle_postgres_races.py` — **6 passed** (R2 confirmed:
    the relocated delete builds a real strategy and a missing-blob delete is a no-op).
  - Focused suites (`test_api_key_routes`, `test_admin_profile_routes`, `test_auth_routes`,
    `test_profile_publication_locking`, `tests/unit/core/provider_access`) — 319 passed; the four new
    suites — 52 passed.
  - OpenAPI export (`create_app().openapi()`, sorted, indent 1) **byte-identical** to the branch base
    (78181 bytes, sha256 `d513b29c…ddc0`). One difference surfaced during the run and was reverted: the
    admin listing docstring is the operation description; it is back verbatim (see deviation 6).
  - `git diff --check` clean; no `# type: ignore`; largest new file 400 lines; hygiene grep over every
    changed file clean.
- **Deviations:**
  1. **F2 (owner-approved 2026-09-18):** one prior test changed — the patch point of the OME-307
     rollback race test moved to the admin seam; the route-module patch point is gone. This is why the
     append-only gate is RED for this unit.
  2. **Port annotation widened:** `ProviderCredentialAdmin.set_api_key` takes
     `defaults: RequestDefaults | None`; `None` keeps the stored defaults (the PUT body may omit them —
     today's behaviour), a supplied value replaces them wholesale (spec op 8). A1 declared the stricter
     annotation; the interface, not the HTTP contract, changed.
  3. **Retry exhaustion typed in core:** `CredentialBlobMutationConflict` raised by the index CAS is
     converted to `WriteConflict("retry_exhausted", subject="profile")` and rendered 503
     `profile_index_conflict` by the refusal table (same body); the `main.py` handler stays for the
     OAuth and PATCH paths.
  4. **Availability row set:** one row per `sorted(registered providers ∪ providers with rows)`; a
     registered provider without rows is `not_connected` (the Engine "none" case), so the row set is
     stable per deployment.
  5. **Admin PUT/DELETE** keep delegating to the two shells in `routes/auth.py` rather than calling the
     boundary themselves: one shell per operation carries the edge halves (key validation per F4, the
     post-commit OAuth cleanup, the F3 delete rows); the admin listing calls the boundary directly.
  6. **OpenAPI:** the admin listing docstring had been rewritten for A3 and changed the published
     operation description; restored byte-for-byte, the A3 note moved to comments.
  7. **Anchor:** the `COMPATIBILITY` marker (precedent `profile_backed.py`, A2) tags every window-only
     exception with its removal point (Stage E / `OME-1209`); the card's `extra_anchors` is empty.
  8. Nothing from OME-1208 / OME-1209 started; no client-visible change; no compatibility deleted.
