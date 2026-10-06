---
ticket: OME-1375
parent: OME-1138
status: accepted   # sequence for the D18 landings; each landing needs its own filed issue
created: 2026-10-02
updated: 2026-10-06
base: 40214a746d741aace7ff80b5a48038e4c0d626de
spec: docs/spec/2026-10-02-provider-credential-admin-contract.md
---

# Provider credential admin successor (D18) — rollout plan

The contract is the spec above; this plan holds the sequence, the evidence that shaped it and the
tests. It decides nothing the spec does not.

## 1. Evidence on the base

| Fact | Source (relative to `apps/aigateway` unless stated) |
| --- | --- |
| Admin GET/PUT/DELETE address a Profile; PATCH keeps metadata separately | `routes/admin.py` (`list_account_profiles`, `set_account_api_key`, `delete_account_profile`, `patch_account_profile`) |
| The admin port requires `legacy_name`; its summary carries `selector/state`; masked metadata sits in the opaque legacy projection | `core/provider_access/ports.py` (`ProviderCredentialAdmin`); `core/provider_access/types.py` (`CredentialSummary`) |
| Migrated PUT writes the effective Connection and rollback mirrors under the marker generation | `core/provider_access/connection_admin.py::set_api_key` |
| DELETE requires an existing legacy document even when an effective Connection exists; LIST iterates documents and renders every document of a migrated pair from its effective Connection | `connection_admin.py::delete`, `::list` (lines 100-123); `test_connection_backed_admin_delete_list.py` |
| A single active Connection-only pair becomes `migrated` without a document | `core/provider_access/backfill_classify.py::_connection_only`; `backfill_apply.py::_apply_pair` |
| The backfill same-credential check is decrypted-JSON equality | `backfill_classify.py:201` |
| An OAuth refresh rotates and writes only its own address, inside the plugin | `_refresh_credential` → `_write_to_store` in `plugins/anthropic_provider/auth.py:81,111`, `codex_provider/auth.py:176,208`, `gemini_provider/auth.py:104,138`, `antigravity_provider/auth.py:125,158` |
| A legacy OAuth callback on a `none` pair writes the Profile and a shadow Connection at a UUID locator | `routes/auth.py:864-867`, `_connection_for_pending` (`create_pending` without a locator) |
| Every OAuth plugin extracts an identity; the Connection stores `identity_sub`, unique per account/provider | `plugins/*/plugin.py::extract_identity` (codex reads `id_token`; gemini/antigravity read `id_token` claims first and fall back to a network userinfo call, `core/google_code_assist.py:88-104`); `core/oauth/models/oauth_connection.py:25,40` |
| `PairAuthorityStore` has only `read` and `advance`; `advance` always writes `expected + 1` | `core/provider_access/pair_authority.py:90-150` |
| An in-place re-auth of an active migrated row completes only at its captured generation | `core/provider_access/connection_oauth.py:82-94,163` |
| Legacy concurrency has three wire outcomes | `routes/provider_access_http.py::_write_conflict` (503 `profile_index_conflict`, 409 `connection_conflict`, 409 `profile_conflict`) |
| The UI classifier treats only 503 `profile_index_conflict` as a retryable conflict and every 409 as retryable | `apps/aigateway-ui/src/lib/aigateway/client.ts:109-128` |
| The Console PUT sends only `api_key`; the action substitutes `default`; the form shows a name; detail and delete depend on it | `apps/aigateway-ui/src/lib/aigateway/client.ts:302-335`; `src/app/actions.ts:159`; `src/app/accounts/[id]/credentials/new/form.tsx:136-146`; `detail.tsx:132` |
| The PostgreSQL lane is opt-in locally (`AIGW_TEST_PG=1`) and an unconditional CI step | `tests/integration/test_provider_access_backing_postgres.py`; `.github/workflows/aigateway-tests.yml:82-85` |
| File sizes: `routes/auth.py` 1451 lines (oversized), `routes/admin.py` 357 | `wc -l` on the base |

Gateway and UI runtime did not change between the design base `db6757bc5` and this base.

## 2. Mechanism choice

| Option | Against the constraints | Decision |
| --- | --- | --- |
| Rename `/profiles` and serialize a Profile as a Connection | keeps name/defaults and the legacy projection; Connection-only list/delete still broken | rejected |
| A new table and an independent credential writer | a second source of truth beside the existing authority layer | rejected |
| Neutral pair operations inside the existing admin boundary, the shared fenced write mechanism and separate DTOs | one write owner; old and new APIs coexist without leaking the legacy shape | accepted |
| Refuse every `none` pair | leaves ordinary post-copy keys unmanageable | rejected |
| One-shot CLI apply | does not stop the next `none` write | rejected |
| A reconciliation service | a second lifecycle and more scope | rejected |

The accepted mechanism is a bounded in-band association at mutation time plus the existing writer
fence, in two Gateway releases.

## 3. Sequence

### A. Formalization (OME-1375, docs only)

1. Branch based on `origin/main` `40214a746`. Done 2026-10-05.
2. The approved packet becomes `docs/spec/2026-10-02-provider-credential-admin-contract.md`; the
   umbrella spec §3.5 and the D18 row point to it; this plan; the ledger and the OME-1375 mirror.
3. Corrections carried with it: three legacy concurrency outcomes (umbrella D18 row, OME-1375
   description); D14 refinement; the four formalization decisions in spec §9.
4. Owner-authorized filing of the Gateway and UI landing issues (spec §10) — done 2026-10-06:
   `OME-1497` (Gateway) and `OME-1498` (UI), with `OME-1209` blocked by `OME-1498`. Still pending
   owner authorization: the OME-1375 description correction and the OME-1333 disposition comment.
   Nothing in Linear changes without that authorization.
5. Out of this repository: synchronize D18 with the design-repo metamodel catalog
   (`provider-credential-admin`); an insufficient accepted catalog is its own gate.

### B. Gateway landing — G0 writer floor

Fresh branch from current `origin/main`; test-first; exact installed FastAPI, Pydantic and
Tortoise versions and their docs checked for the touched mechanisms (`select_for_update`, nested
`in_transaction` savepoints, request validation hooks).

1. Ledger → RED tests: unmarked legacy writer vs adopter; native create/delete; stale OAuth
   callback; stale refresh publication after a key replacement (marked and unmarked pairs);
   start re-auth → refresh → callback succeeds; last-used touch does not advance.
2. Inventory every first credential persistence: the four plugins' `_refresh_credential`, the
   token service, authorize-triggered refresh, bootstrap, legacy admin/tenant key set/delete, OAuth
   begin/callback/fail, native create/key-replace/delete, state transitions.
3. Split plugin network fetch from guarded publish. Add the check-without-advance refresh guard
   (lock the owning Connection row, re-read the marker) and the CAS guard where `none`/native
   publication bypassed the fence. Do not wrap migrated paths in a second advance.
4. Assertions that change only where a legacy write now passes the writer floor — to be approved
   exactly before editing: `test_connection_backed_admin.py:72-98,101-123`,
   `test_connection_backed_oauth_flow.py:205-226,229-258`, `test_connection_backed_refresh.py:271-282`.
   Facade read/no-promotion tests stay no-advance invariants.
5. GREEN → focused races and compatibility → full Gateway gates → PostgreSQL lane → review → PR.
   Release G0; G1 waits until a writer-floor build runs on every Gateway writer.

### C. Gateway landing — G1 successor and bridge

1. RED route/port matrix: post-copy legacy key → LIST/PUT/DELETE; sole `pending`/`error`
   Connection; first-marker race; LIST conflicts; aliases and shared addresses; legacy OAuth shadow
   identity proof (match after rotation, missing, unextractable, different); row 6 with one leftover
   document; rollback refusal on an alias-addressed mirror.
2. Neutral summary, ordered classifier and bridge inside the existing provider-access boundary
   (candidate cohesive module `core/provider_access/pair_admin.py`); a thin separate router
   (`routes/admin_connections.py`) and DTO module; composition-root registration with
   `AdminAuditRoute`. Nothing new in `routes/auth.py` beyond bounded delegation. New hand-written
   files at most 450 lines.
3. Scoped domain/CAS/read/422 rendering before audit and the global fallback; legacy bodies
   unchanged; additive OpenAPI diff.
4. GREEN → focused races → full gates → PostgreSQL lane → review → PR. Deploy G1 after G0.

### D. Admin UI landing

1. Export OpenAPI from the exact accepted Gateway revision; record revision, hash and command;
   regenerate `src/lib/aigateway/schema.d.ts` (never edited by hand).
2. RED client/action/page tests: paths, DTO mapping, no name/defaults, masking, conflict states,
   code-first dispatch (`credential_write_conflict` retryable beside `profile_index_conflict`;
   superseded/ambiguous/unresolved never retried; storage/authority 503 as a temporary failure;
   bare/configuration 503 stays `unavailable`).
3. Move the server-only client, actions, account detail list/delete and the key attach/replace form;
   remove the name field, Name column, name bindings and the `default` fallback; no PATCH call; no
   silent legacy fallback; BFF-only identity, write-only key, success-only revalidation.
4. Full UI gates; browser smoke against a local or mocked Gateway of the supported build.

### E. Retirement

`OME-1209` retires legacy routes, types and storage only after consumer migration, the window exit,
retention/reference safety and the R1 truthful refusal. No bulk production migration is needed; the
bridge serves later mutations without touching other pairs. The production copy is not a permission
to delete compatibility data.

## 4. Tests

| Group | Mandatory cases |
| --- | --- |
| Auth/scoping | non-admin denial; actor vs target; two tenants; missing account/provider; audit actor |
| Secrets/schema | only `api_key`; key absent from JSON/errors/repr/logs/form state; `defaults: null` refused; no-store on success and error |
| Mapping | empty/single/multi legacy; aliases vs targets; backfill-produced Connection-only migrated LIST/DELETE; migrated null with compat docs; legacy OAuth shadow identity proof; quarantined; unsupported/OAuth dispositions |
| Mutation | create/replace/delete; repeated PUT/DELETE; correct locator; no orphan blob; invalid key keeps the previous credential |
| Concurrency | new PUT vs new DELETE; new vs legacy/native/OAuth; stale callback; eligibility change after pre-read; full rollback on CAS conflict |
| Writer floor/bridge | late `none` writer loses after adoption; two first markers, one winner; post-copy legacy creates stay manageable; bridge refuses a concurrent second candidate; refresh never supersedes an in-flight re-auth; stale refresh loses on an unmarked pair |
| Error contracts | three legacy outcomes unchanged; successor mapping of both superseded subjects; reused codes keep their bodies; ambiguity distinct from superseded |
| Shared references | aliases and shared locator ownership; delete never removes another live reference |
| Coexistence | old writes → new reads, new writes → old reads; refusals on unsupported states; named routes unchanged |
| Rollback | after create/re-key/delete a marker reset or R1 never resurrects a deleted key |
| UI/client | generated contract match; neutral fields; 503 retryable vs unavailable; superseded/ambiguous guidance; no name field; no PATCH; no legacy fallback |
| Route hygiene | X-Profile nonblank/blank/repeated; JSON/extra/defaults key-safe 422; no-store on auth and error; audit actor/status; legacy OpenAPI and error parity |

Existing suites reused for regression (relative to `apps/aigateway`):
`tests/unit/core/provider_access/test_provider_credential_admin.py`,
`test_connection_backed_admin.py`, `test_connection_backed_admin_contract.py`,
`test_connection_backed_admin_delete_list.py`, `tests/unit/test_profile_admin_shells.py`,
`test_profile_delete_set_race.py`, `test_connection_delete_set_race.py`,
`test_profile_publication_locking.py`, `tests/integration/test_provider_access_backing_postgres.py`.

## 5. Gates

From the repository root (the stack card stays authoritative):

```sh
uv run .claude/scripts/run_gates.py aigateway --base origin/main
uv run .claude/scripts/run_gates.py aigateway-ui --base origin/main
# from apps/aigateway, with the approved ephemeral PostgreSQL setup:
AIGW_TEST_PG=1 uv run pytest -m needs_postgres -v
```

The PostgreSQL lane is mandatory for concurrency claims; SQLite does not prove READ COMMITTED
ordering or `SELECT … FOR UPDATE`. A prior green CI does not validate the new API.
