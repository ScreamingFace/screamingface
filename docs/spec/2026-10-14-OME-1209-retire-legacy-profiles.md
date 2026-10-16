---
status: accepted   # owner approval 2026-10-14; E1b and the E3 catalog delta amended 2026-10-15
issue: OME-1209
parent: OME-1138
date: 2026-10-14
base: origin/main 9be66ecb0
---

# OME-1209 — Stage E: retire the legacy Profile surface

## 1. Purpose

Stage E of `docs/spec/2026-09-09-OME-1138-converge-connections.md` (§5 row E, §6.2, D6). Every
consumer named in that spec's §4 has moved: runtime reads go through provider access (A2), the
management routes are shells (A3), the Connection authority sits behind the pair marker (B), saved
defaults and selectors are gone (C, D), and the Admin UI uses the D18 pair-addressed API (#1411).
This stage removes what is left so the gateway keeps one credential concept: `Connection` (D20).

The legacy surface is not one thing. Its routes have successors today; its storage is still the
authority for every pair that has not been migrated. The stage is therefore split into landings
whose preconditions differ (§6), and only the first three need nothing outside this repository.

## 2. Verified as-is at 9be66ecb0

### 2.1 Routes (13)

| Route | Handler | Today | Successor |
|---|---|---|---|
| GET `/v1/auth/profiles` | `routes/auth.py` `list_profiles` | shell over admin `list` | `GET /v1/provider-access`, `GET /v1/oauth/connections` |
| GET `/v1/auth/{provider}/profiles` | `list_provider_profiles` | shell | same |
| GET `/v1/auth/{provider}/profiles/{name}` | `get_profile` | shell | `GET /v1/oauth/connections/{connection_id}` |
| POST `/v1/auth/{provider}/profiles` | `start_oauth` | direct; legacy pending on unmigrated pairs | `POST /v1/oauth/connections` |
| GET `…/profiles/{name}/status` | `profile_status` | facade | `GET /v1/oauth/connections/{connection_id}` |
| PATCH `…/profiles/{name}` | `patch_profile` | facade; writes the label into the index | `PATCH /v1/oauth/connections/{connection_id}` |
| PUT `…/profiles/{name}/api-key` | `set_profile_api_key` | shell | `POST /v1/oauth/connections/api-key`, `PUT …/{connection_id}/api-key` |
| DELETE `…/profiles/{name}` | `delete_profile` | shell | `DELETE /v1/oauth/connections/{connection_id}` |
| POST `…/profiles/{name}/refresh` | `refresh_profile` | hybrid; direct index access on unmigrated pairs | `POST /v1/oauth/connections/{connection_id}/refresh` |
| GET `/v1/admin/accounts/{id}/profiles` | `routes/admin.py` `list_account_profiles` | shell | D18 `GET …/connections` |
| PATCH `/v1/admin/accounts/{id}/profiles/{provider}/{name}` | `patch_account_profile` | facade | none: D18 has no name or label to edit |
| PUT `…/profiles/{provider}/{name}/api-key` | `set_account_api_key` | shell | D18 `PUT …/connections/{provider}/api-key` |
| DELETE `…/profiles/{provider}/{name}` | `delete_account_profile` | shell | D18 `DELETE …/connections/{provider}` |

The OAuth callbacks (`/callback`, `/auth/callback`) are shared with the native Connection flow and
are not Profile routes; only their legacy-pending branch retires, at E4.

### 2.2 Consumers

- No first-party runtime caller of a Profile route remains: Engine, SDK, URL4, scoreboard, studio,
  charts, e2e and CI were checked. `apps/desktop/out/main/index.js` is a tracked, source-less build
  artifact that calls `/auth/profiles`; it is not a component (routing map, `OME-1266`) and is out
  of scope.
- Wire dependencies on Profile-named error codes, not routes: the SDK
  (`packages/screamingface/src/screamingface/_engine/catalog.py:268-317`, `profile_not_found`,
  `profile_pending_auth`), the Admin UI (`errors.ts` maps `profile_index_conflict`; `detail.tsx`
  cites `404 profile_not_found`), chat and model admission. These codes are emitted by chat for the
  runtime credential, not only by Profile routes.
- Refusals on the runtime path, migrated pairs included, carry
  `reauth_url=/v1/auth/{provider}/profiles/{name}` (`profile_backed.py:173`,
  `connection_authority.py:103,240`, `connection_facade.py:108`, `profile_authorize.py:52`,
  `routes/auth.py:213`). Retiring the routes without changing this would point every re-auth at a
  retired endpoint.

### 2.3 Storage

- There is no Profile table. `Profile`/`ProfileIndex` are Pydantic documents stored as JSON in
  `credential_blobs` (service `aigateway:index`, account `account:{id}`), managed by
  `ProfileIndexStore` (`core/profile_index.py`). The pair marker is `provider_credential_slots`
  (migration `0012`): absent, `none` or `quarantined` means the legacy Profile still owns the pair.
- The legacy index is still an authority, not residue:
  - every chat on an unmigrated pair resolves through it (`ConnectionBackedProviderAccess` subclasses
    `ProfileBackedProviderAccess`, `connection_backed.py:84,107`);
  - the D18 successor reads Profile documents to classify pairs and retires them on mutation
    (`pair_admin.py:251`, `pair_admin_writes.py:253,265`);
  - the native OAuth callback still marks the Profile document (`routes/auth.py:1105`, D14);
  - bootstrap writes Profiles (`writer_floor.py:158`, `plugins/anthropic_provider/bootstrap.py`);
  - backfill tooling exists (`migrate_profiles.py`, `backfill_classify.py`, `backfill_apply.py`).

### 2.4 Code coupling

- `AuthType` and `AuthMode` live in `core/profile_models.py` and are imported by about 30 modules,
  every provider plugin included; `credential_name_for` and `profile_id_for` are used by Connection
  code.
- Dead in production: `routes/chat_credentials.py`, `routes/chat_profile_defaults.py`,
  `apply_defaults`/`should_apply_profile_default`, `ProviderAccess.defaults_for`,
  `CredentialTarget.defaults`, `RequestDefaults` (spec §3.7 kept them declared "until stage E").
- Plugin hooks still named for Profiles: `should_apply_profile_default`, `allows_chatless_profile`,
  `profileless_auth_mode`, `invalidate_profile_session`,
  `should_mark_profile_error_on_dispatch_status`, `bootstrap_profiles`, and the `profile_name`
  parameters of `*_strategy_for`.
- Tests: of 402 gateway test files, 137 reference Profile machinery, 54 hit Profile HTTP paths,
  8 run on the PostgreSQL lane. No executable retirement machinery exists yet (no 410 helper, no
  `Deprecation`/`Sunset` header); removal points are comments and the import-boundary allow-list.

## 3. Retirement contract

- **R1 — a coded refusal, never a silent change.** A retired route answers `410 Gone` with
  `{"code": "legacy_profile_api_retired", "message": …, "successor": "<method> <path template>"}`,
  `Cache-Control: private, no-store`, before any I/O and before reading the body. It never answers
  an empty list and never performs the old operation (§6.2: "retirement returns a code, never an
  empty list"). The retired operations leave the OpenAPI schema (`include_in_schema=False`); their
  schemas (`AdminProfileOut`, `AdminProfileList`, `PatchAdminProfileRequest`,
  `SetAdminApiKeyRequest`, `PatchProfileRequest`, `SetApiKeyRequest`, `StartAuthRequest`) go with
  them.
- **R2 — no runtime response names a retired route.** Every `reauth_url` points at a live
  successor before any route retires.
- **R3 — runtime error codes are not part of this stage.** `profile_not_found`,
  `profile_pending_auth`, `profile_index_conflict`, `profile_conflict` and `x_profile_unsupported`
  are emitted by chat, model admission and the successor routes for the runtime credential; the SDK
  and the UI decode them. Renaming them is a cross-package wire change with its own release train
  and is not needed to retire the Profile surface. They stay; copy that cites them as a Profile
  route changes.
- **R4 — storage authority ends only when no pair depends on it.** The legacy index stops being
  read on any runtime or admin path only after every pair in every environment is `migrated`
  (no absent, `none` or `quarantined` marker) and the named rollback build no longer needs it.
- **R5 — retention is separate (D6).** Retiring routes and authority deletes no stored document
  or blob. Deleting index documents and unreferenced blobs is a separately authorised history
  cleanup whose reference check and deletion share one atomic boundary that also fences concurrent
  reference creation (§6.2 "History").
- **R6 — every credential a retired route could repair stays repairable.** Before E3, a migrated
  pair's OAuth credential is re-authorised only through the Profile facade
  (`POST /v1/auth/{provider}/profiles` → `begin_connection_oauth`); the native
  `POST /v1/oauth/connections` opens a row that never becomes the pair's effective Connection
  (`claim_native_write` is a no-op on a `migrated` pair), so chat keeps reading the errored row.
  The native flow therefore takes over the effective row in three cases, as the Profile facade
  did: when that row is unusable (`error` or `revoked`, OAuth or API key); when the flow names no
  label — "no label = the pair's main connection", as the Profile API's default name did — and
  then the new row keeps the replaced row's label unless that is a placeholder (`error:`,
  `revoked:`, `pending-`); and when the flow asks for that row's own label — the native flow's only way to address a connection, i.e.
  "re-authorise that one", which is also how a working API key switches to OAuth with no window
  without a credential. The callback of that flow makes the new row effective and revokes the
  old one in one transaction, fenced by the marker generation observed at start — never two
  effective rows. When the sign-in matches the provider identity of another active row of the
  pair, that row becomes effective with the fresh tokens instead, and the new row retires as its
  duplicate. With any other label a working (`active` or `pending`) effective row stays, and
  the flow adds a plain row beside it. The same rule applies to a native API-key create
  (`POST /v1/oauth/connections/api-key`, the successor of the Profile key write): the new key
  becomes effective when the effective row is unusable, when it names no label, or when it asks
  for that row's label, in
  the create's own transaction, fenced by the pair captured before the key validation. This uses only the Connection side (rows
  and the pair marker), which outlives E4; it reads and writes no Profile document. No route and
  no `reauth_url` changes: the E1 pointer `/v1/oauth/connections` is the repair. API-key pairs
  already re-key in place (`PUT /v1/oauth/connections/{connection_id}/api-key`).

## 4. Landings

| # | Landing | Wire change | Precondition |
|---|---|---|---|
| E1 | Successor pointers: `reauth_url` → live successor; UI/README/docs copy stops citing Profile routes | refusal bodies change one field | none |
| E1b | Native repair (R6): a native OAuth connection replaces a migrated pair's unusable effective Connection | none (behaviour of `POST /v1/oauth/connections` on that pair) | E1 merged |
| E2a | Neutral core: move `AuthType`, `AuthMode`, `credential_name_for`, `profile_id_for` out of `profile_models.py` | none | none |
| E2b | Delete the dead shims and the saved-defaults pipeline | none | none |
| E3 | Route retirement: the 13 rows of §2.1 answer R1; schemas leave OpenAPI; Admin UI `schema.d.ts` regenerated; tests pinning the retired routes retire with an approval manifest | yes (R1) | E1 and E1b merged (sunset: retire on merge, §7 Q1); catalog delta (§7 Q6) |
| E4 | Authority end: Connection-only resolution and admin; D14 dual write, legacy pending, Profile bootstrap and the D18 none-pair bridge removed; plugin hooks renamed or deleted; `ProfileIndexStore` reachable only from offline tooling until E5 | none for migrated pairs | R4 proven in every environment (§7 Q3) |
| E5 | History cleanup (R5) | none | separately authorised |

E1, E2a and E2b are independent and can land in parallel. E3 follows E1 and E1b. E4 needs evidence from outside
this repository. E5 is not part of closing this issue (§7 Q4).

## 5. Tests (per landing, written first)

- E1: every refusal that carried a Profile `reauth_url` now carries a successor that the router
  resolves; no response body, header or OpenAPI document references `/profiles`.
- E1b: on a migrated OAuth pair whose effective row is `error` (and `revoked`), a native
  connection's callback makes the new row effective and revokes the old one; chat then resolves
  the new row (errored → new connection → chat 200, end to end), including a re-login of the same
  provider identity. A usable effective row is not displaced. A newer start, a delete or a key
  write between start and callback supersedes it (marker generation); nothing is half-published.
- E2: rename-only and move-only; the full suite stays green with no assertion changed; the import
  boundary forbids `profile_models` outside the Profile-backed modules.
- E3: each retired route answers 410 with the R1 body for every method, with and without a body,
  with no storage read (spy) and no audit of a write; OpenAPI contains no `/profiles` path and no
  Profile schema; the successor routes are byte-identical before and after.
- E4: with every pair `migrated`, chat, D18 and native OAuth never construct or read
  `ProfileIndexStore`; an absent, `none` or `quarantined` marker fails closed with a coded refusal
  instead of reading the index; PostgreSQL lane green.

## 6. Out of scope

Runtime error-code renames (R3), storage deletion (R5, unless authorised), production access or
backfill runs by an agent, `apps/desktop` build artifacts, Engine/URL4 changes (Stage D retired
their carriers), a multi-credential policy.

## 7. Owner decisions (2026-10-14)

- **Q1 — sunset of the Profile routes (E3): retire on merge.** No first-party runtime caller
  remains (§2.2), so E3 answers R1 from its first deploy; no `Deprecation`/`Sunset` window.
- **Q2 — runtime error codes: kept** (R3). A rename, if ever wanted, is a separate
  cross-package unit.
- **Q3 — E4 evidence: every pair migrated.** E4 starts only after a census shows every pair in
  every environment `migrated`; any pair that is not is backfilled with the existing tooling
  first. The census and backfill are owner actions (no agent production access); E4 is part of
  closing `OME-1209`.
  - **dev, 2026-10-15:** 26 pairs `migrated`, 0 `quarantined`, 0 conflicts. One pair had two
    Profiles on one provider (`several_documents`, which the backfill never guesses); with the
    tenant's consent the unreachable second Profile was deleted through the legacy admin route
    and the pair was backfilled. The one remaining `none` pair has no Profile document, only an
    abandoned pending OAuth Connection, so nothing shadows a Connection.
  - **stage, 2026-10-15:** no credential of any kind (0 credential blobs, 0 Connections, 0 pair
    markers, 0 Profile indexes); nothing to migrate.
  - **prod, 2026-10-15:** 6 pairs, each one Profile on openrouter (`profile_only`), no Connection,
    no marker. The owner ran the backfill (`--apply --all`): 6 applied, 0 conflicts. After it:
    6 pairs `migrated`, each with an active effective api-key Connection reading the existing blob;
    blob count unchanged (12), so no key was re-entered or copied.
  - **R4 holds in every environment (dev, stage, prod) as of 2026-10-15.** The legacy Profile
    routes still accept writes until E3 is deployed, so the census is re-run (read-only) right
    before E3 and E4 are deployed to each environment; a new Profile-owned pair is backfilled
    first.
- **E4 constraint found by the census.** A pair with no marker and no Profile document is not
  legacy-owned; it must keep resolving through its Connections. E4 refuses only a pair that still
  has a Profile document and is not `migrated`.
- **Q4 — E5: separate and later.** History cleanup (R5) is not part of `OME-1209`; it gets its own
  issue and its own authorisation, with the reference check and deletion behind one fence and a
  fixture where a migrated Connection still uses a legacy-addressed blob.

## 8. Owner decisions (2026-10-15)

- **Q5 — repair before retirement: E1b before E3 (R6).** Mapping the tests E3 retires showed that
  the Profile facade is the only path that re-authorises a migrated pair's OAuth credential in
  place. Retiring it first would leave such a pair recoverable only by deleting its effective
  Connection and starting a new one, a window with no credential. E1b lets the native flow
  replace an unusable effective row (no new route, chosen over a `/reauthorize` route that would
  have reused the Profile-mirroring facade core); E3 waits for it. (prod holds only api-key pairs as of 2026-10-15; the dev census recorded no
  breakdown by auth type, so the re-run before E3 counts migrated OAuth pairs per environment.)
- **Q6 — E3 carries a catalog delta.** The aigateway catalog in the design repository describes
  the retired operations and schemas (the HTTP API snapshot, the provider-access protocol and its
  OAuth workflow, the `patch-profile-request` data model, coverage). E3 records them as retired
  with their historical provenance; it does not delete them or regenerate a snapshot to hide the
  loss. The catalog write follows a semantic review, and the catalog checks are green before E3
  merges.
- **Q7 — a native repair is not R1-rollbackable.** The repaired pair's effective row lives at its
  own Connection address and its compat document is not mirrored (R6 writes no Profile
  document), so the R1 rollback tool refuses that pair (`rollback_refused_alias_documents`) —
  loudly, with nothing changed. Accepted: keeping rollback would need the Profile mirror that E4
  removes; a Profile-facade repair before E3 stays rollbackable.
- **Order relative to the OME-1138 rollout.** The rollout ends Profile authority before it cleans
  up the legacy surface; this stage retires the routes (E3) before authority ends (E4). Accepted:
  every pair with a Profile document is `migrated` (§7 Q3), so on every pair the routes are
  already facades over the effective Connection, and the census re-run before each E3 deploy keeps
  it so.
