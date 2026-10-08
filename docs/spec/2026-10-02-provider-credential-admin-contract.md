---
ticket: OME-1375
parent: OME-1138
status: accepted   # D18 approved by the owner 2026-10-05; runtime execution is a separate landing
created: 2026-10-02
updated: 2026-10-06
base: 40214a746d741aace7ff80b5a48038e4c0d626de
decides: D18 in docs/spec/2026-09-09-OME-1138-converge-connections.md
---

# Provider credential admin successor (D18) — pair-addressed Connection contract

This document is the normative D18 contract. The umbrella spec (§3.5, §8 D18) points here and
does not repeat the HTTP shape. Implementation lands in separate Gateway and Admin UI issues under
`OME-1138` (§10); this document changes no runtime.

## 1. Target and production context

An admin manages the one effective credential of an `(account, provider)` pair through the
`Connection` resource. A Profile name, a selectable credential and saved defaults are not part of
the new API. The target model after D18 is Connection-only: Profile documents and OAuth shadow
Connections remain legacy/compatibility artifacts of the transition window. They are neither an
authority nor a new credential-selection mechanism.

The OME-1208 backing transition is complete. The owner confirmed on 2026-10-05 that the
post-migration dev database was copied to production, so no further production assessment or
backfill is a D18 prerequisite (OME-1333 is not an execution step). This is an owner disposition,
not a newly measured census, and it does not authorize deleting legacy data. The historical figure
of 25 pairs (23 Profile-backed, 2 Connection-only) comes from the OME-1208 closing comment of
2026-09-23.

The copy is a snapshot. Later legacy API-key or legacy OAuth writes can still leave a new pair in
`none` or create a Profile plus a shadow Connection. This contract serves those states as
transitional legacy state without another migration. Their number in production is not measured.

D18 replaces the admin surface over the existing Connection authority. It creates no new storage
and no independent credential writer. Legacy retirement stays `OME-1209`.

## 2. HTTP surface

| Operation | Method and path | Success |
| --- | --- | --- |
| List the account's connections | `GET /v1/admin/accounts/{account_id}/connections` | 200 |
| Add or replace an API key | `PUT /v1/admin/accounts/{account_id}/connections/{provider}/api-key` | 200 |
| Disconnect a provider | `DELETE /v1/admin/accounts/{account_id}/connections/{provider}` | 204 |

No single-pair GET, no PATCH, no Profile name and no public Connection id. Every operation uses the
existing Gateway admin authorization; the actor and the target account are distinct. The Admin UI
calls through its server-side BFF; the admin allowlist and trusted identity stay in the Gateway.

OpenAPI: schemas `AdminConnectionOut`, `AdminConnectionConflictOut`, `AdminConnectionList`,
`SetAdminConnectionApiKeyRequest`; operationIds `list_admin_account_connections`,
`set_admin_account_connection_api_key`, `delete_admin_account_connection`. The existing admin
security scheme and the `Admin` tag are kept; legacy schema and operation names do not change.

## 3. Connection DTO

```json
{
  "provider": "openai",
  "auth_type": "api_key",
  "credential_state": "active",
  "masked_key_hint": null,
  "last_refreshed_at": null
}
```

- `provider`: provider identifier. `auth_type`: `api_key | oauth`.
- `credential_state`: `active | pending | error` — credential lifecycle, not operational
  availability and not a promise that the provider key works. OME-1250's `unavailable` is not
  carried here and its status contract is unchanged. Legacy `authenticated` renders as `active`;
  a revoked or absent connection is not listed. Unknown or inconsistent states are never rendered
  as `active` or as absence.
- `masked_key_hint`: always `null` in the first landing; the field stays nullable. There is no
  trusted hint source: `Profile.account_label` is PATCH-editable, and the hint must not be derived
  from it, from a label or from ciphertext, nor by decrypting the credential for LIST. A hint
  column or migration is not part of D18.
- `last_refreshed_at`: the timestamp actually stored on the current owner, else `null`.
  `create_api_key` does not set it; a replacement or a real OAuth refresh may. Never substitute
  `created_at` or the LIST time.

The DTO never reads the opaque `legacy_projection`; an adapter provides a neutral summary. No
name, id, selector, defaults, locator, slot, generation or raw key appears on the wire.

## 4. LIST and per-provider conflicts

```json
{
  "connections": [
    {"provider": "openai", "auth_type": "api_key", "credential_state": "active",
     "masked_key_hint": null, "last_refreshed_at": null}
  ],
  "conflicts": [
    {"provider": "anthropic", "code": "credential_pair_ambiguous",
     "message": "The provider credential cannot be addressed unambiguously."}
  ]
}
```

- `connections` holds unambiguous existing connections, including migrated Connection-only pairs
  and safe single-candidate `none` pairs (§5). A missing marker is not a refusal.
- `conflicts` holds only ambiguous or unresolved pairs per the ordered table in §5.
- LIST never advances a marker, never runs the classifier CLI and never refreshes credentials. It
  may read legacy index metadata through the existing port; it never reads or decrypts a provider
  credential.
- The inventory is the union of marker providers, Profile providers and non-revoked Connection
  providers. Exactly one result per provider.
- For a `none` pair, state and auth type come from the current legacy owner (Profile-only and
  same-locator pairs) or from the single Connection (Connection-only). Metadata state does not
  guarantee a usable key.
- A pair is never hidden as an empty list and never shown as several selectable credentials.
- Both arrays are sorted by `provider`; a provider without a connection is not added. The catalog
  of available providers stays separate.
- A store or authority read failure answers 503 for the whole request, never a partial or empty
  inventory.

`conflicts` are explicit per-provider domain outcomes of a successful read; LIST still answers 200.
A mutation on such a pair answers 409. A structural conflict and a store outage stay distinct.

## 5. Ordered pair disposition

Read top to bottom; the first matching row decides. A missing marker is a valid `none` at
generation 0. A live Connection is a non-revoked one; `pending` and `error` rows are candidates, not
absence. Revoked rows are never resurrected. A locator must belong to the account/provider
credential namespace; a malformed locator is never re-addressed by a fallback for the bridge.

| # | State | LIST / mutation |
| --- | --- | --- |
| 1 | Store read failure | 503 `credential_store_read_unavailable`; the whole LIST refuses |
| 2 | Unknown marker/state/auth type; inconsistent reference; malformed or out-of-scope locator | 503 `credential_authority_unavailable`; nothing is guessed |
| 3 | More than one Profile document or more than one live Connection | conflict / 409 `credential_pair_ambiguous`, whatever the marker |
| 4 | Valid `quarantined` | conflict / 409 `credential_pair_unresolved`; quarantine is never lifted automatically |
| 5 | `migrated` with a valid non-null effective reference | that row, including `pending`/`error` and Connection-only; a referenced missing or revoked row → 503 `credential_authority_unavailable` |
| 6 | `migrated` with a null reference and no live Connection, compat documents remaining or not | disconnected pair: no LIST result; PUT creates (§5.2); DELETE 204. Leftover documents are not resurrected by a read |
| 7 | Empty pair: no documents, no live Connections; marker absent or `none` | no LIST result; PUT creates; DELETE 204 |
| 8 | `none`: one Profile, no live Connection | LIST the neutral legacy owner; PUT/DELETE through the bridge (§5.1) |
| 9 | `none`: no Profile, one Connection (`active`/`pending`/`error`) | LIST a neutral row; PUT/DELETE through the bridge |
| 10 | `none`: one Profile and one Connection at the same valid locator | LIST the current legacy owner; PUT/DELETE through the bridge |
| 11 | `none`: one Profile and one Connection at different locators, or any other unresolved combination | LIST conflict / 409 `credential_pair_unresolved`; PUT/DELETE only through the shadow identity proof (§5.1), otherwise the operator path |

Known `active/pending/error` states and `api_key/oauth` modes are supported; an authenticated
Profile renders as `active`. A referenced revoked or missing effective row is an inconsistency,
not a normal post-delete state (a normal delete clears the reference). Unknown values fall to
row 2. An unsupported provider or auth mode keeps its existing typed refusal. In LIST an unknown
provider is an explicit unresolved result; a mutation on it keeps the existing 404.

Alias refusal is preserved. Row 3 is deliberately stricter than the legacy and native code: an
extra live Connection on a migrated provider is never picked automatically, even where the native
routes would leave the marker as it is. Operator path before the legacy UI is retired: confirm the
owner by hand, then remove or revoke the extra live candidate, or run a separately authorized
repair/backfill for a quarantine. A legacy DELETE of one alias can remove the whole credential, so
it is not a safe way to drop only an extra name. The new UI never falls back silently.

### 5.1 Mutation bridge — no bulk backfill

A single-candidate `none` pair is a normal supported state, post-copy provisioning included. A GET
never promotes it. PUT validates the new key the usual way and then writes atomically: the chosen
target → marker `migrated` → compatibility metadata → active API-key Connection and blob. DELETE
atomically ends the pair as `migrated` with a null reference, retires or removes the chosen owner
and its compatibility metadata. When no Connection exists, DELETE does not create a dummy row to
delete it.

This is an association at operation time, not a migration engine: no other accounts or pairs are
enumerated, `migrate_profiles --apply` is not called, no ciphertext moves between addresses and no
cache is reset. Old `pending`/`error` metadata is not declared `active` before a successful PUT. A
failed validation changes no marker, metadata or credential.

The bridge does not promise that the old secret is usable: PUT replaces it with the validated key,
DELETE disconnects the single target. A same-locator proof only shows ownership of the address.
`backfill_classify._with_profile` decrypts the blob and therefore is neither callable from LIST nor
a no-decrypt bridge.

**Legacy OAuth shadow — identity proof (owner decision 2026-10-05).** A legacy OAuth flow on a
`none` pair writes the Profile blob and a shadow Connection at a different (UUID) locator. The two
blobs diverge at the first refresh: the Profile path refreshes and rotates only its own address, so
a byte-equality check is almost always false in steady state. For row 11 with exactly one Profile
and exactly one live Connection, PUT and DELETE therefore prove the shadow by identity, never by
comparing blobs:

1. Before the short transaction, decrypt the Profile credential in process and extract its stable
   OAuth identity with the same provider-specific mechanism the callback uses for
   `OAuthConnection.identity_sub` (`plugin.extract_identity(...).sub`). Any network or token
   introspection that a plugin needs happens here, never under an SQL lock. Nothing decrypted
   leaves the operation or reaches a log, an error or the wire.
2. The pair is a legacy OAuth shadow of one credential only when both identities exist and are
   equal. A missing identity, a failed extraction (an expired token included), an undecodable blob
   or a different identity answers 409 `credential_pair_unresolved` and the operator path. No
   refresh is performed to obtain an identity.
3. The transaction re-reads the candidates (including the Connection's `identity_sub`) and the
   pair generation, then publishes through the Connection exactly as for row 9 and retires the
   Profile. Any change since step 1 answers `credential_publication_superseded`.

LIST and every display path never decrypt and never use this proof to choose a target. This is the
only scoped secret read of the successor.

### 5.2 Addresses, compatibility mirror and deletion

- Existing Connection: keep its id and authoritative locator; never re-key between addresses.
- Sole Profile-only pair: the private mirror name is the existing name; the new row sits on its
  existing locator.
- Entirely new empty pair (row 7): a fresh Connection UUID; private mirror name `default`; locator
  `credential_locator_for(credential_service_provider_for(plugin, provider), account_id, "default")`.
  This is a compatibility-window rule of admin provisioning, not a change of native UUID locators.
  Verify that no other live owner holds that address before writing; otherwise refuse as unresolved.
- Row 6 with exactly one leftover compatibility document (clarified at formalization): that
  document becomes the private mirror under its own name and address, exactly like the sole
  Profile-only rule; no second `default` mirror is created, because the legacy list renders every
  document of a migrated pair from its effective Connection and two documents would push the pair
  into row 3. The no-other-live-owner check applies to its address. With no leftover document the
  row-7 rule applies.
- Existing Connection-only pair: keep id and locator; create one private `default` mirror after a
  successful PUT when none exists. Credentials are never copied to the default address for a mirror.
- Mirrors keep the historical defaults of an existing document; a new document has empty defaults.
  They serve the old LIST/PUT/DELETE and never become an authority or part of the successor DTO.
- When a mirror's address differs from the locator (for example a UUID-native Connection), the
  existing R1 alias-address guard refuses a marker reset honestly; no rollback that would restore an
  empty key is promised. A legacy facade on a writer-floor build keeps reading the migrated
  authority; an R0 rollback is not promised.
- DELETE does not use the document-required `ConnectionBackedCredentialAdmin.delete` as a general
  implementation. In one transaction: selected row → `retire_effective` → `lock_lower_addressers`
  → revoke → `credential_has_other_owner` → delete the blob only for its last owner. A Profile-only
  pair removes the sole document and checks live address ownership under the same pair/index fence,
  without a dummy Connection. Safety primitives are shared; route bodies and ORMStore are not copied.
- Post-commit `PendingAuthTable` cleanup is scoped to account/provider plus the captured affected
  target. A sole Profile name is used internally only; Connection-only cleanup does not depend on
  it. A minimal pair/connection-scoped helper keeps the existing `pop_for_profile`.

### 5.3 Writer floor (G0) — no bridge above an unfenced legacy branch

Before the successor is published, every authority-changing Gateway writer uses the existing pair
generation compare-and-set in `none` too: legacy admin/tenant key set and delete, OAuth
begin/callback/fail/refresh publication, native create/key-replace/delete and credential state
transitions. A metadata PATCH changes no ownership; the existing index CAS and mirror coherence
stay.

A branch read is not a permission to commit later. An operation captures the observed owner,
generation and target before network I/O; legacy PUT and native key replacement capture after
provider key validation (owner decision 2026-10-06, below). In a short transaction it first claims the
same generation through `PairAuthorityStore.advance`, then checks the current candidates and
owner, then writes index → row → blob. The guard sits at the existing publication point: migrated
paths already advance the marker and are not wrapped in a second advance; the guard is added where
`none`/native publication bypassed the fence. On `none` a legacy operation keeps legacy authority
(`none`, null reference) and its `migration_note`, which never reaches the wire. The G1 bridge and
the G1 successor create publish `migrated`. The first marker is also a CAS: the INSERT uniqueness loser rolls
back and answers superseded 409. A stale mutation is never retried on a freshly read generation.

An OAuth entry records its captured owner and generation separately from the earlier migrated-only
token semantics; a stale callback after a bridge loses. A legacy or native writer that started on
`none` before an adoption loses the CAS after the bridge, even when it had already chosen a
Profile-backed body. A process-local lock is not enough. Writers that change a live reference or
locator respect this boundary; addresses with shared owners keep the existing row/index lock
ordering. A fresh UUID row before the marker is allowed only inside the same transaction for the
foreign key; it is uncontended and rolls back with a lost marker. Owner checks address the actual
service/account address, not only the provider label. Check and publication are atomic; creating a
legacy address uses the existing account-index serialization, not a new lock store.

The guard precedes the FIRST credential persistence, not only the metadata update after a refresh.
Four OAuth plugins (anthropic, codex, gemini, antigravity) currently persist the new token inside
`_refresh_credential`; G0 splits network fetch from guarded publish.

**Refresh is not an ownership change.** It never advances the ownership generation. Only explicit
PUT/DELETE, OAuth callback/re-auth completion and native create/key-replace/delete advance it. An
ordinary refresh performs its network I/O outside any transaction, then in a short transaction
checks that the same Connection is still the current owner at the captured generation and writes
tokens and `last_refreshed_at`. Why: a browser re-auth already in flight on an active row reuses the
row in place and completes only at its captured generation, so a refresh that advanced the
generation would turn that callback into a false 409. A last-used touch does not advance either.

Check-without-advance primitive (clarified at formalization): `PairAuthorityStore.advance` always
writes `expected + 1`, and an absent `none` marker cannot be row-locked, so the refresh guard
locks the owning Connection row `SELECT … FOR UPDATE`, then re-reads the marker and requires the
captured generation and the same owner before writing. Ownership-changing writers on that pair
update or lock the same Connection row before their blob write, which serializes them against the
refresh. A Profile-owned refresh uses the existing account-index serialization instead. No new
table, lock store or job.

The G0 inventory includes authorize-triggered refresh, the token service and bootstrap where they
write a credential. A missed persistence path fails acceptance; "routes guarded" is not enough.

**Advance or check (owner decision 2026-10-06, after the G0 inventory).** Only an ownership change
advances the generation: key PUT/DELETE, OAuth callback/re-auth completion and native
create/OAuth start/key-replace/delete. OAuth begin records the pair it observed and its callback
claims that generation; OAuth failure, error marks and refresh publication only check the observed
generation where a lockable row exists and never advance it. Migrated paths keep the advances they
already make. On `none` and `quarantined` every claim keeps the state, the null reference and the
note; a native create or OAuth start on `none` keeps `none` (no auto-promotion). Non-effective native
rows of a `migrated` pair keep their existing fences. Legacy PUT and native key replacement capture
the pair after provider key validation, as the migrated paths do: a change during validation is
last-writer-wins, a change after the capture loses. G0 ships as three PRs (ownership writers,
refresh publication, failure and error checks), all merged before the G0 deployment.

**D14 refinement.** G0 fences `none` and `quarantined` writers with the pair generation; the legacy
owner, the absence of auto-promotion and the shadow Connection write of a legacy OAuth callback all
stay exactly as decided in D14. Stopping new shadow writes is deferred (§9).

G0 and G1 are two sequential releases of one Gateway landing: G0 adds writer guards without the
successor or bridge and changes no data in bulk; G1 adds the successor and bridge after a
writer-floor build runs on every Gateway writer. The UI switches after G1. Without the writer floor
safe coexistence with a pre-floor build cannot be promised. No feature flags, lock tables, jobs or
generic reconciliation services.

## 6. PUT, OAuth and DELETE

PUT body is exactly one member: `{"api_key": "..."}`.

- Existing normalization and validation primitives run before publication. A failed key check keeps
  the previous credential.
- `name`, `defaults` (`null` included), a selector and any other field are refused with a
  secret-safe 422; the raw key never appears in a response, validation error, form state or log.
- A successful create or replace answers 200 with the DTO; a repeated PUT never creates a second
  effective row. Idempotency does not promise no validation I/O, no generation advance or no
  timestamp change.
- OAuth connections are visible and can be deleted or replaced by an API key; no OAuth start or
  refresh surface is added to the console. Pending OAuth cleanup runs after commit and keeps fencing.
- Disconnect answers 204; a repeated DELETE of an absent credential answers 204. Unknown account or
  provider answers 404; a store outage or an ambiguous pair never becomes a false successful DELETE.
- Delete/revoke and compatibility changes share the existing transaction/authority mechanism; a
  blob another live owner needs is never deleted.
- A stale concurrent publication never resurrects a deleted credential. A deliberate PUT after a
  committed delete may reconnect. A superseded 409 is never retried automatically.

The repeated successor DELETE 204 is an intentional additive delta against the legacy 404. Legacy
Profile and native DELETE keep their own status and body.

### 6.1 Request/response hygiene — scoped to the new routes

- Authentication and audit actor: existing `CurrentAdmin` and `_note_actor`; key validation and
  storage I/O run after auth. Extra-field checks of valid JSON run as auth-dependent prevalidation,
  like the existing saved-default refusal; malformed JSON/body errors use the redacted successor 422.
- `defaults` present (`null` included) → existing 422 `defaults_not_accepted`, without submitted
  values. Any other unknown member → 422 `unsupported_credential_fields` with a static message that
  never lists field names. Invalid JSON, wrong type, missing or empty key → 422
  `invalid_credential_request`. Detail is exactly `{code, message}`; no raw input, validator
  context, exception text or field names. Existing provider validation refusals stay. OpenAPI PUT
  has `additionalProperties: false`.
- Any nonblank `X-Profile` on the new GET/PUT/DELETE (`default` and repeated fields included) →
  existing 400 `x_profile_unsupported`, without echo; blank or whitespace counts as absent.
  Unrelated admin routes get no new selector policy.
- The Gateway sets `Cache-Control: private, no-store` on every new-route response, success and
  error (auth, 422 and 503 included); the BFF fetch is no-store as well.
- The new router uses `route_class=AdminAuditRoute`; the authenticated actor is recorded by a
  dependency before a body refusal and by the handler before I/O. Unauthenticated audit keeps an
  unidentified actor. Errors are translated before audit status recording, so a scoped 503 is not
  logged as a raw 500.
- The scope of `_redact_validation_errors` and of the CAS translation never changes legacy bodies.
  `extra="forbid"`/`SecretStr` alone do not replace secret-safe rendering.

## 7. Errors and legacy contract protection

| HTTP | Successor code | Controlled message |
| --- | --- | --- |
| 503 | `credential_write_conflict` | `Credential update conflicted. Try again.` |
| 409 | `credential_publication_superseded` | `Credential state changed. Reload before submitting another change.` |
| 409 | `credential_pair_ambiguous` | `The provider credential cannot be addressed unambiguously.` |
| 409 | `credential_pair_unresolved` | `The provider credential cannot be managed safely. Resolve its state before retrying.` |
| 503 | `credential_authority_unavailable` | `Credential state is temporarily unavailable. Retry later.` |
| 503 | `credential_store_read_unavailable` | `Credential store is temporarily unavailable. Try again.` |
| 503 | `credential_store_unavailable` | existing safe write-refusal body and message |
| 422 | `unsupported_credential_fields` | `Only api_key is accepted.` |
| 422 | `invalid_credential_request` | `A valid API-key request body is required.` |

Other authentication, provider and key-validation failures keep their existing contract; no broad
rename. The existing HTTP error envelope stays. A pair error detail is exactly
`{code, message, provider}`; a whole-account read failure is `{code, message}`; a per-provider LIST
conflict is the pair detail without the outer envelope. An unknown migration state or an invalid
auth state becomes the typed authority-unavailable outcome, never a raw `ValueError`. No
migration-required code exists on the wire.

The existing legacy outcomes are unchanged — 503 `profile_index_conflict`, 409 `profile_conflict`
and 409 `connection_conflict` (`routes/provider_access_http.py::_write_conflict`) — with their
bodies. `connection_conflict` and `connection_ambiguous` get no new bodies under their old names.
A name collision needs an explicit contract decision, never an automatic rename.

The core returns typed refusals; the HTTP edge table in `routes/provider_access_http.py` owns the
status/body mapping with an explicit successor scope and keeps existing rows. The successor
boundary maps `PairAuthorityConflict`/`ProfileTransitionConflict` to superseded,
`CredentialBlobMutationConflict` to write-conflict and scoped store read errors to
store-read-unavailable. A CAS never falls into the app-wide `_profile_index_conflict` handler with
the legacy body. Only expected storage/domain failures are caught; a programming error never becomes
a successful empty result. Exception text, `WriteConflict.requested`, `migration_note`, cause chains
and model reprs are never serialized.

The UI classifier adds the retryable successor 503 to the existing `profile_index_conflict`
mapping; a bare or configuration 503 stays `unavailable`; superseded/ambiguous 409 are never
retried automatically. The UI dispatches by code before the generic status fallback: ambiguous →
resolve, unresolved → operator action, superseded → reload without resubmitting the secret.
Storage/authority 503 → temporary service failure, not "admin API disabled". In `describeFailure`
non-retryable codes never fall into the existing "conflict / try again"; code and detail reach the
action and page. A retryable read never auto-repeats a PUT. Metadata and errors are not cached in
the BFF. The existing selector policy of unrelated admin routes is not extended.

## 8. Compatibility window and acceptance

Order: formalize this contract (this document) → Gateway landing (G0 writer floor, then G1 pair API
and bridge) → Admin UI landing (exact Gateway OpenAPI revision → generated types →
list/actions/forms; remove the visible name field, the Name column, name bindings and the `default`
fallback) → `OME-1209` legacy retirement after consumer, window, reference and rollback checks.

The API window closes after a confirmed UI migration, an accounting of remaining consumers, an agreed
operator path for conflicting pairs and verified coexistence/rollback guarantees. Until then legacy
APIs and documents stay; no calendar removal date is set.

Implementation acceptance: tenant/admin isolation; no secret disclosure; mandatory Connection-only
and single-candidate `none` support; the ordered pair table; PUT/DELETE/legacy/native/OAuth races;
shared blob references; legacy three-code parity; supported old/new writes and reads; a truthful R1
refusal on an alias-addressed mirror instead of a silent bad restore; generated DTO/client match;
UI 409/503 guidance; route audit/headers/422; full Gateway and UI gates and the PostgreSQL
concurrency lane. Prior tests are kept; any exception is approved explicitly.

Mandatory falsifiers:

- post-backfill legacy create → successor LIST/PUT/DELETE;
- pending-only Connection → LIST plus replace and delete;
- legacy OAuth on `none` creates Profile plus shadow at different locators → LIST conflict without
  decrypt; PUT/DELETE succeed when both identities exist and match, including AFTER a refresh has
  rotated the Profile token; refuse when an identity is missing, unextractable or different;
- a stale legacy/native writer that read `none` before a bridge loses;
- a stale OAuth callback after a bridge or deletion loses;
- start re-auth → ordinary refresh publishes → callback with the original generation succeeds;
- an old refresh publication after a key replacement loses, including on an unmarked `none` pair
  (PostgreSQL lane);
- native create inserts a second candidate while the bridge validates → the bridge refuses;
- a cached strategy's next legitimate refresh is not stuck on an obsolete epoch;
- two first-marker creates → exactly one commits, no orphan;
- migrated with a null reference and leftover compat documents → LIST empty, DELETE 204, PUT
  reuses a single leftover document as the mirror and the pair does not become ambiguous;
- LIST leaves marker and database unchanged; failed key validation leaves owner and data unchanged.

G0 guards are exercised on mixed legacy/native writers on their own; the G1 bridge is never tested
over pre-G0 guards.

## 9. Decisions recorded at formalization (2026-10-05)

| Item | Decision | Status |
| --- | --- | --- |
| Shadow proof (§5.1) | stable OAuth identity (`identity_sub`) instead of blob byte equality, which fails after the first refresh | owner decision 2026-10-05 |
| Refresh guard (§5.3) | lock the owning Connection row, re-read the marker, require the captured generation; no advance | formalization clarification; mechanism only |
| Row 6 leftover document (§5.2) | a single leftover document becomes the mirror; no second `default` | formalization clarification of "stale docs do not resurrect" |
| D14 (§5.3) | G0 fences `none`/`quarantined` writers; legacy owner and shadow write unchanged | refinement of D14, not a reversal |
| Stop new shadow writes | deferred: reverses D14's decided "shadow Connection write included", and the Local Engine reads `/v1/oauth/connections*`; needs a D14 amendment and a consumer check | open follow-up, not in G0 |
| Legacy concurrency baseline | three wire outcomes, not two; the umbrella D18 row and the OME-1375 description are corrected | correction of existing behaviour, not a new API |
| Advance or check, native create, capture point (§5.3) | only ownership changes advance; begin/fail/error marks/refresh check; native create on `none` keeps `none`; key validation precedes the capture | owner decision 2026-10-06 |

## 10. Landing issues

Filed only with owner authorization, under `OME-1138`, assignee `me`, actor `agentic`, who-acts
`autonomous`, one component leaf per issue (`aigateway` for the Gateway landing; the UI landing
uses the `aigateway-ui` stack): the Gateway landing (G0 then G1) is blocked by this formalization;
the UI landing is blocked by the Gateway landing. Labels are checked against the live board; no
label is created automatically. The OME-1333 disposition is recorded separately as an owner comment,
never as a production assessment performed in this work.

Filed 2026-10-06: Gateway landing `OME-1497` (blocked by `OME-1375`; its release checklist orders
G0 deployed before G1 deployed) and Admin UI landing `OME-1498` (blocked by `OME-1497`). `OME-1209`
is blocked by `OME-1498`.

## 11. Out of scope

Storage deletion, production reads, backfill/apply, deployment, cache reset, a multi-credential
policy, OAuth start in the console, a hint column, Engine/URL4/SDK changes, `OME-1209` retirement
and stopping shadow writes (§9).
