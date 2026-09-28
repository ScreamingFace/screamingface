---
ticket: OME-1244
stack: aigateway
status: in_progress   # planned | in_progress | done | blocked
started: 2026-09-21
finished:
---

# OME-1244 — Publish the backing-neutral availability listing

## Intent

Stage A4 of `OME-1138` (adapter-first convergence), gateway half (plan unit U4). Stage A3
(`OME-1230`, PR #992, `a78d58da`) implemented `ProviderAccess.availability` in-process over the
legacy Profile index, golden-equivalent to the Engine's `decode_profile_statuses` rule. The Hosted
Engine still aggregates the legacy `GET /v1/auth/profiles` body locally, so it carries Profile
vocabulary that the later backing switch removes. This unit publishes the caller-scoped, read-only
successor decided in D17, `GET /v1/provider-access`, returning rows of `provider` and `status`
only, so the Engine switch (`OME-1245`, plan unit U4e) can read one backing-neutral listing. Every
other client-visible contract stays byte-identical; the backing stays the legacy Profile.

**Endpoint naming decision (recorded per the A4 acceptance).** D17 was decided on 2026-09-14 as
option (a), the neutral `GET /v1/provider-access` with rows of `provider` and `status` only. The
alternative `GET /v1/oauth/connections?effective=true` is rejected because it presupposes the
Connection backing and exposes labels, ids and locators. The name is not reopened in this unit.

**Prerequisite (process gate).** The design repository describes `GET /v1/provider-access` as the
accepted successor contract before any code below is written. At design `main` `65ab0b6f` it does
not: the provider-access component card describes `availability` as declared-only and states that
no `/v1/provider-access` router exists; the provider-access protocol card lists no such operation.

## Planned changes

Design repository first (branch `OME-1244-provider-access-availability`, PR, owner merge):

- NEW `solutions/screamingface/protocol/provider-access-availability/index.md` and
  `transport.yaml` (solution level, beside `model-catalog`, because its participants span the
  gateway and the Engine; the catalog check files it there) — the successor as an accepted target: `GET /v1/provider-access`;
  caller-scoped through the gateway's account identity; rows `provider` + `status` with `status`
  in `not_connected`, `pending`, `connected`, `needs_reauth`, `error`; the Profile-backed window
  never emits `needs_reauth`; `Cache-Control: private, no-store`; inbound `X-Profile` non-selecting;
  no names, ids, labels, defaults, auth method, account label, locators, reauth URL, credential
  names or secret-derived fields; no secret read, refresh, mutation or strategy construction; the
  Hosted Engine as the consumer; Hosted mutations refused before upstream I/O (D15); later-stage
  boundaries (no backing migration, no Profile retirement, no selector sunset).
- `component/provider-access/index.md` — refresh to the A3 as-built state at `a78d58da`
  (`availability` implemented, `ProviderCredentialAdmin` implemented by `profile_admin.py`,
  management routes as shells) and add the `exposes` edge to the new protocol; version +1.
- `protocol/provider-credential-admin/index.md` — A3 as-built refresh (the Today section
  rewritten against `a78d58da`, the target section becomes the description); version +1; the
  review state is left for the owner.
- `product/aigateway/index.md` (contract-map rows, version +1); `product/engine/index.md`
  (`uses` edge and a Hosted listing section, version +1); `component/credential-store/index.md`
  (`exposes` edge as the backing participant, version +1); `solutions/README.md` import-boundary
  note.

  Progress 2026-09-21: authored on the design worktree branch
  `OME-1244-provider-access-availability` (from design `origin/main` `65ab0b6f`); catalog
  check 0 errors, 3 warnings (all pre-existing baseline); evolution check against
  `origin/main`: 5 changed entities, each with a valid version transition, plus the new entity
  at v1. Committed locally as design `defd3f7b` (`docs(catalog): describe the provider-access
  availability listing and refresh the A3 cards`, `Refs: OME-1244`) under the owner's
  commit-only authorization of 2026-09-21; push, PR and merge remain owner steps. The same day
  the owner confirmed the issue scope (gate 2) and decided F-A4-1 for the Engine unit
  (re-express the profile-availability suite at the successor seam); the refreshed
  provider-credential-admin card stays `draft` for the owner to set at merge.

  Gate 1 cleared 2026-09-21: design PR #22 merged as `a2468eee`. The owner authorized the
  OME-1244 application-code stage in plain words the same day (route only; no Engine switch;
  nothing from Stages B–E). The unit branch was fast-forwarded to `origin/main` `39cea39f`
  (no aigateway changes since `a78d58da`) before the first code edit.

Production (source repository, only after the design PR is merged and the code stage is
authorized in plain words; every file ≤450 lines):

- NEW `apps/aigateway/src/aigateway/routes/provider_access_availability.py` — one router with
  `GET /v1/provider-access`: `CurrentAccount` scoping; body
  `{"providers": [{"provider": ..., "status": ...}, ...]}` built from
  `provider_access_for(request.app).availability(str(current.id))`; response header
  `Cache-Control: private, no-store`; the route never reads `X-Profile`. Registered in `main.py`
  beside the existing routers. No other route changes.
- `core/provider_access/*` unchanged unless a RED test demands a fail-closed conversion at the
  edge (the status vocabulary is already a closed `Literal`).

Tests (new files only; no prior test edited):

- NEW `apps/aigateway/tests/unit/test_provider_access_availability_route.py` — exact key set per
  row; `Cache-Control: private, no-store`; caller scoping (two accounts, different rows);
  inbound `X-Profile` ignored (same body with none, `default`, and a name matching nothing);
  no forbidden field over a fixture holding OAuth and API-key Profiles with labels and defaults;
  delegation to `app.state.provider_access.availability` with no `credential_strategy_from`
  call and no store write; unknown internal status fails closed without echoing the value;
  unauthenticated caller gets the existing auth refusal; OpenAPI export with the new operation
  removed is byte-identical to the branch base.

Docs: this ledger; mirrors `docs/tasks/2026-09-21-OME-1244-provider-access-availability.md` and
`docs/tasks/2026-09-21-OME-1245-hosted-engine-availability-successor.md`; the A4 row of the
OME-1138 plan's stage table at close.

## Test plan

RED first, in this order (each fails against `main` for the right reason before any code):

1. `GET /v1/provider-access` answers 404 today (the route does not exist).
2. Rows carry exactly `provider` and `status`; status values are members of the closed family.
3. `Cache-Control: private, no-store` on every 200.
4. Two accounts with different Profile rows receive different bodies; an account with no rows
   receives `not_connected` for every registered provider.
5. Inbound `X-Profile` (absent, `default`, or a name matching nothing) never changes the body.
6. No credential strategy is built, no blob is read and nothing is written while serving the
   route (spies on `credential_strategy_from`, the store's read/write/mutate and the index
   mutators).
7. No name, id, label, defaults, auth method, account label, locator, reauth URL or credential
   name appears in the body for a fixture that has all of them.
8. An implementation returning an unknown status makes the route fail closed (500 without the
   value in the body) if any conversion exists at the edge; otherwise the pin documents that the
   `Literal` is passed through unchanged.
9. OpenAPI: the export minus the new path is byte-identical to the branch base export.

Baselines to record before code: full aigateway gate and PostgreSQL lane on the branch base;
the base OpenAPI export.

## Acceptance

- `GET /v1/provider-access` implemented as specified; the OpenAPI diff against the branch base
  contains only the new operation; every existing operation stays byte-identical.
- No secret or legacy selector data in any response; no strategy construction, refresh or
  mutation on the read path.
- Full aigateway gate green; PostgreSQL lane green; `screamingface-e2e-replay` green.
- The ledger records the endpoint decision (above) and every check actually run.
- Nothing from Stage B, C, D or E started; legacy Profile routes untouched.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
  - NEW `apps/aigateway/src/aigateway/routes/provider_access_availability.py` (67 lines): one
    `APIRouter` with `GET /v1/provider-access`; route-local Pydantic response models
    `ProviderAccessAvailabilityRow` (`provider`, `status: AvailabilityStatus`, extra forbidden) and
    `ProviderAccessAvailability` (`providers`); `Cache-Control: private, no-store` on the injected
    `Response`; delegates to `provider_access_for(request.app).availability(str(current.id))`;
    never reads `X-Profile`; `__all__ = ["router"]`.
  - `apps/aigateway/src/aigateway/main.py` (+3 lines): the import and
    `app.include_router(provider_access_availability.router)`; no other route touched.
  - NEW `apps/aigateway/tests/unit/test_provider_access_availability_route.py` (337 lines,
    13 tests): anonymous caller → 401; rows carry `provider` + `status` only from the closed
    family, sorted, `needs_reauth` never emitted by the Profile-backed port; caller scope with a
    second provisioned account (empty account → every registered provider `not_connected`);
    `X-Profile` non-selecting for `default`, a seeded error-Profile name, an unknown name and the
    empty string; local auth disabled serves the anonymous principal; delegation to the wired port
    verbatim (recording stand-in: one call with the caller id, rows neither re-sorted nor
    filtered); index-only reads, no credential strategy, no store or index write (spies); no
    name / id / label / default / auth method / account label / locator (structural leaf scan plus
    seeded-value scan); an out-of-family internal status fails closed (500, value absent from the
    body); OpenAPI publishes exactly one new operation plus the two schemas only it references,
    and the factory with that router emptied publishes the identical remainder.
  - This ledger and the mirror `docs/tasks/2026-09-21-OME-1244-provider-access-availability.md`.
- **Commits:** none yet — staging, commit, push and PR await the owner's authorization for the
  exact paths above (including these two Markdown files).
- **Gates:** `uv run .claude/scripts/run_gates.py aigateway --base 39cea39f` → all six green:
  append-only test check vs `39cea39f` ✓ (no prior test touched), `ruff check` ✓,
  `ruff format --check` ✓, `pyright` ✓ (0 errors, tests included), `check_no_enterprise.py` ✓,
  `pytest --cov=aigateway --cov-fail-under=80` ✓. Standalone re-run for the counts:
  4667 passed / 79 skipped, total coverage 92.53% (A3 baseline at `a78d58da`: 4654 passed / 79 skipped / 92.52%; the +13 are this unit's tests). RED first: the 13 new tests failed on the absent route (404 / `KeyError` on the
  OpenAPI path) before the module existed. OpenAPI: the base export at `39cea39f` (38 paths,
  40 schemas) vs the new app — added path `/v1/provider-access` only, added schemas
  `ProviderAccessAvailability` and `ProviderAccessAvailabilityRow` only (referenced nowhere in
  the base document), nothing removed; the new document minus those three keys is byte-identical
  to the base after key sort. PostgreSQL lane: `AIGW_TEST_PG=1 … -m needs_postgres
  tests/integration/test_lifecycle_postgres_races.py` → 6 passed; the whole `-m needs_postgres`
  set (the CI migration-smoke step) → 37 passed / 5 failed, all five in
  `test_cache_snapshot_upload_postgres.py` because the `pg_dump` on PATH is 15.13 while the
  testcontainer runs PostgreSQL 16 (server version mismatch); the same five pass with the
  PostgreSQL 16 client tools on PATH (5 passed) — environmental, unrelated to this unit. Python
  3.12 leg (separate environment, 3.12.9): the new suite plus the A3 availability suite →
  25 passed; the main run is 3.13. Not run locally: `screamingface-e2e-replay` (fires on
  `apps/aigateway/**` in CI) and the CI auth-surface coverage step (its modules are untouched).
- **Deviations:**
  1. Typed response models instead of a plain dict (house style `response_model=`): the OpenAPI
     diff is therefore the new operation plus its two exclusively-referenced component schemas,
     which publish the status enum and `additionalProperties: false`. The fail-closed edge is the
     model's `AvailabilityStatus` literal (a pydantic validation error becomes a bodiless 500),
     not a hand-written guard.
  2. No `Vary` header (`model_parameters` sends `Vary: Authorization, X-Profile`): `no-store`
     already forbids storage, and `X-Profile` must not be named because it selects nothing here.
     A test pins that `Vary`, if ever added, never names `X-Profile`.
  3. `refusals_as_http` not applied: `availability()` raises no `ProviderAccessRefusal` (no read
     path raises `CredentialStoreUnavailable`); wrapping would be speculative generality.
  4. Branch fast-forwarded from `a78d58da` to `origin/main` `39cea39f` before the first code edit
     (no AIGateway change in between); baselines re-exported at `39cea39f`.
  5. No AIGateway README change: it keeps no route inventory; the contract lives in OpenAPI and
     the merged design card `protocol/provider-access-availability`.
  6. Endpoint naming: D17 `GET /v1/provider-access` (settled 2026-09-14) implemented as-is, not
     reopened. OME-1245 (Engine switch) and Stages B–E untouched.
