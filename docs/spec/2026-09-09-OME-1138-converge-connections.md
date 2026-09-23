---
ticket: OME-1138
status: draft   # adapter-first revision; D2 REMOVE retained; execution approval remains separate
created: 2026-09-09
updated: 2026-09-16
base: 17048f5d9794dc39401352cc049dc1b17a54f7c0
catalog: screamingface-design 679aa8f (branch OME-1178-add-the-aigateway-metamodel, PR #18); generator inputs 802bed9a
revises: 2026-09-10 revision (Connection-first ordering; its verified content is retained below)
---

# Converge Profiles onto one effective credential per (account, provider) — adapter-first

## 1. Purpose, end state and approval boundary

AIGateway holds two credential domains: encrypted `Profile`/`ProfileIndex` documents (Hosted,
Admin UI, `X-Profile`) and `OAuthConnection` rows (Local, managed label). Consumers know Profile
records, states and defaults directly: three gateway routes and the dispatch-failure marker, the
Hosted Engine listing, the Admin UI and the codes relayed to the SDK.

**End state (unchanged owner target):** one effective credential per `(account, provider)` shared by
Local and Hosted, OAuth and API key; one resolver for chat, model parameters, admission,
availability and future credential-scoped discovery; no selectable Profiles, no `X-Profile`, no
`listing_source="profiles"` in the target runtime; saved ProfileDefaults removed in full (D2);
compatibility only inside a declared window with a defined removal point.

**Adapter-first change (owner direction, 2026-09-12):** introduce a stable provider-access boundary
first and back it with the existing Profile mechanisms; move every consumer onto it while Profiles
remain the only storage; then transition the storage/authority behind the same boundary. Profiles
are not removed in this pass. Which model finally backs the boundary — a transfer to Connections
(plus the retained slot design) or an internal aggregate that absorbs the current Profile mechanisms
— was an open owner decision (D11) until 2026-09-22, when the transfer to Connections through the
retained slot design was decided (§8). The boundary is designed so either backing satisfies the same
contract, which is what let Stage B swap the backing without a consumer rewrite.

**Naming decision (OME-1210, 2026-09-16):** the final product/API/domain noun is **Connection**.
`Provider access` names the internal boundary and its HTTP successor family, not a persisted
credential resource. `Profile` is a legacy compatibility surface and current backing implementation;
new docs should say `legacy Profile` when the distinction matters. `Provider Account` is not
introduced as a resource, API object or UI noun because it conflicts with account ownership and would
create a third credential concept; if a future internal implementation keeps a provider-account-like
aggregate, it must still publish and document the effective credential as a Connection. `Credential
target` remains an internal per-request resolution value, and `effective credential` remains an
invariant, not a user-facing object name.

**Approval boundary:** this revision authorises nothing. No runtime code, no catalog write, no data
migration, no task mutation, no staging or push follows from it. Implementation starts only after
explicit approval of the first unit (Stage A1) and the re-approval D7 now requires (§8).

**Baseline note:** the branch is at `17048f5d`. `origin/main` has since advanced to `c1c92562`
(tracing, OME-1132: `routes/chat_dispatch.py` gains one import line before the failure marker,
`main.py` gains five lines before the conflict handler, Engine `runner/main.py:281` moves to `:283`;
`apps/aigateway-ui` and `packages/url4` are unchanged). Anchors below are at `17048f5d`; re-anchor
when the branch is moved, which needs an instruction.

## 2. Verified as-is at 17048f5d

Paths are relative to `apps/aigateway/src/aigateway/` unless prefixed. Every row was confirmed by
at least two independent source reads in this pass; tests are cited as pins, not as run evidence.

| Fact | Anchor |
| --- | --- |
| `X-Profile` is read at exactly three sites, each normalising `(header or "default").strip() or "default"`; no middleware reads it; a message string and a docstring also name it. | `routes/chat.py:242`, `routes/model_parameters.py:134`, `routes/model_admission.py:106`; `routes/chat_credentials.py:200`, `routes/model_parameters.py:3` |
| Chat order: normalise → pre-cache defaults read → merge → cache lookup (hit returns without any credential read) → resolver → auth mode → re-merge only when the pre-cache read was unreadable → inject → dispatch → failure marking. | `routes/chat.py:242,306-308,323,327,343-351,356-377,461-470,490-502` |
| The de-facto resolver returns a typed tuple `(Profile \| None, OAuthConnection \| None, ProfileDefaults)`: Profile named by the selector first regardless of state; else active Connections by label, the single one for `default`, else 409 `connection_ambiguous` / 404 `connection_not_found` with `valid_labels`; no target → 404 `profile_not_found` unless the plugin allows chatless or the caller passed `missing_target_ok`; pending → 409 `profile_pending_auth`; error → 401 `auth_required` + `reauth_url`. | `routes/chat_credentials.py:170-212,215-275` (escape `:240-245`, OME-1167) |
| The resolver's index read is unguarded; a persistent index fault escapes as an unhandled exception (no catch-all handler). Two distinct conflict contracts exist. (i) CAS-retry exhaustion: `CredentialBlobMutationConflict` after `_MUTATE_MAX_ATTEMPTS` → app-wide handler **503** `profile_index_conflict` (also on the HTML callback); the Admin UI special-cases that pair as retryable. (ii) A conditional publish that observes a concurrent delete or state transition: `ProfileTransitionConflict` → **409** `profile_conflict` in the API-key upsert (delete-wins), PATCH metadata and reauth paths, **409** `profile_auth_conflict` in the OAuth callback; deliberately swallowed where a late transition must lose. The Admin UI classifies any 409 as `conflict`. | `routes/chat_credentials.py:224-225`; `core/credential_blob/store.py:161`, `main.py:295-307,369`, `routes/auth.py:665-673`; `core/profile_index.py:17`, `routes/auth.py:178-183,783-790,1213-1217,1342-1348` (swallowed `:159-160,1144-1145`); `apps/aigateway-ui/src/lib/aigateway/client.ts:105-121` |
| Pre-cache defaults read never raises; `None` strictly means unreadable → cache bypass; it never inspects state or Connections. Connection targets contribute empty defaults. | `routes/chat_profile_defaults.py:37-85`, `:239` of the resolver, `tests/unit/test_chat_global_cache_effective_request.py:22-28,351,497-545` |
| The read path mutates: api-key-only auth-type repair, `mark_error`/`mark_authenticated_error` (fenced on `auth_type` + `last_refreshed_at`), `touch_last_used`, strategy-cache eviction, plugin session invalidation; the dispatch-failure marker does the same for provider auth failures. | `routes/chat_credentials.py:145-167,158,333-347,432,450,454,481`; `routes/chat_dispatch.py:45-94` |
| Model parameters: keyless datasheet allowed only for the default selector; context identity digests `profile.id/state/last_refreshed_at` or `connection.id/status/last_refreshed_at`; `scope="account_profile"`; `Vary: Authorization, X-Profile`; keyless mode = `profileless_auth_mode()` else `available_auth_modes()[0]` (api_key before oauth, else `none`). Admission string-matches `auth_required`/`profile_pending_auth`. | `routes/model_parameters.py:72-75,78-94,140-147,178,192-216`; `core/plugin_base/_contract.py:338-359`; `routes/model_admission.py:106-131` |
| Slot naming is Profile-owned on one side only: Profile blob key `credential_name_for(account_id, name)`; Connection blob key `credential_key_for(account_id, connection_id)`; both are plain strings consumed by the strategy factory and by the strategy cache key `(provider, auth_type, credential_name)`, and eviction is by that string. Blob `account` is the plugin `keychain_account` (anthropic, env-configurable, default `default`); other plugins hard-code `default`. The chat path rebuilds the Connection address instead of reading the stored `credential_locator`. | `core/profile_models.py:28`, `core/oauth/store.py:20-32`, `core/credential_strategy_cache.py:28-30,60-66`, `routes/auth.py:118-124,929-931,954`, `routes/chat_dispatch.py:68-70`, `plugins/anthropic_provider/settings.py:87`, `plugins/anthropic_provider/bootstrap.py:59-62` |
| ProfileIndexStore fences (single-row CAS via `ORMStore.mutate`, process lock only same-process): `upsert(require_present)` delete-wins `:76-77`; `begin_pending` claims a generation `:106-107`; `authenticate_pending` pending guard `:156-157` + generation `:158-162`; `mark_pending_error` `:207-212`; `mark_authenticated_error` `:239-245`; `update_metadata` presence `:273-274`; `remove` keeps the generation as tombstone `:300-305`; legacy global row seeds the account row `:48-53,70,102`. | `core/profile_index.py:32-326` |
| Profile writers: OAuth start/callback (`begin_pending`/`authenticate_pending`), the shared callback's unfenced `_mark_profile_authenticated(require_pending=False)` for Connection flows, `upsert_api_key_profile` (index CAS first, blob second, one transaction; defaults assigned wholesale when supplied), `delete_profile_for_account` (index removal + blob delete in one transaction), `update_metadata` (tenant/admin PATCH), refresh lifecycle, chat-path error marking, bootstrap upsert. | `routes/auth.py:527-625,717-812,870-911,1251-1359 (1303-1304),1370-1402,127-184,1405-1424`; `routes/admin.py:261-282`; `main.py:210-222` |
| Dual OAuth write exists today: a Profile OAuth completion also creates a shadow Connection and a second token blob for every `ProviderPluginBase` plugin; a Connection completion flips a same-named Profile. A deleted Profile's shadow Connection stays reachable through the label fallback. Untested. | `routes/auth.py:799-801,957-1021,1024-1025`; `core/plugin_base/_provider.py:159-166` |
| Tenant listing returns the full Profile JSON (state, auth_type, scopes, account_label, defaults). Admin list/PATCH read the index directly; admin PUT/DELETE reuse the tenant facades. No admin Connection API exists. | `routes/auth.py:498-518`, `routes/admin.py:243-337` |
| Effectively dead: `PendingAuthEntry.compatibility_profile_name` is never assigned (only read); `OAuthConnectionStore.complete()` has no production caller (tests only). Neither is a migration item. | `core/pending_auth.py:17`, `routes/auth.py:1132`, `core/oauth/store.py:161-178` |
| Access control: `CurrentAccount` supplies the account and does not authorise a provider profile or model; the same identity must resolve to the same account-scoped credential namespace. Gemini's chatless path reads a process-wide env key at dispatch, outside account scope. | design catalog `component/access-control`; `core/auth/middleware.py`; `plugins/gemini_provider/plugin.py:190-196`, `chat_handler.py:43-44,151-166` |
| Hosted Engine aggregates `GET /v1/auth/profiles` per provider (authenticated > pending > error; none → not_connected; strict 3-state decoder; never `needs_reauth`/`auth_method`/`account_label`); mutations refused with 400 before any I/O. Local Engine uses `/v1/oauth/connections*` with label `screamingface`; more than one non-revoked managed row of any status → 409; status map active→connected, pending→pending, expired/revoked→needs_reauth (revoked branch unreachable: the gateway list excludes revoked), error→error. Flipping `listing_source` alone is not behaviour-preserving. | `apps/screamingface-engine/src/screamingface_engine/connections/aigateway.py:36,79-91,93-164,169-173,208-212,250-256,283-289`; `connections/profile_availability.py:11,14-37`; `app.py:404`; `local.py:205`; gateway `core/oauth/store.py:49` |
| Selector carrier: REST header (`str \| None`, no normalisation) → `schedule(profile=)` → in-process sets **or pops** `AIGATEWAY_PROFILE`; queued message encodes it only when present and the worker child env inherits the ambient value when absent (same asymmetry for identity and cache-policy keys); runner reads env; connector forwards even `""` unchanged; the Engine also forwards the header on listing and connection calls, where the gateway ignores it. Chart supplies no `AIGATEWAY_PROFILE`. Engine never interprets the value and never injects `default`. | Engine `rest/routes.py:485-488,524`; `ports.py:68`; `adapters/inprocess.py:179-185,190-199`; `runner_queue.py:227-230`; `adapters/queue_runner.py:308`; `worker/supervisor.py:741-742`; `worker/exec_wrapper.py:26`; `runner/main.py:281`; `runner/connector.py:885-886`; `catalog/aigateway.py:100-121,208-241`; `connections/aigateway.py:410-411` |
| Admin UI writes defaults: PUT sends six fields or `null` on API-key attach/replace (form exposes model/temperature/max_tokens; name defaults to `default`); the gateway assigns wholesale, so a UI submission nulls fields set by tenant PATCH. Defaults are never rendered. `schema.d.ts` is committed openapi-typescript output without a script. | `apps/aigateway-ui/src/app/actions.ts:161-237`, `credentials/new/form.tsx:134-192`, `app/accounts/[id]/detail.tsx:43-65,112-149`, `lib/aigateway/client.ts:249-280`, `lib/aigateway/schema.d.ts` |
| SDK has no Profile client: relayed codes (`profile_not_found` permanent, `profile_pending_auth` retryable, `auth_required` permanent), scope literal pinned by fixtures, exact-field Connection decoder, hosted status collapse; the e2e replay guard asserts 404 `profile_not_found` and runs on `apps/aigateway/**` changes. | `packages/screamingface/src/screamingface/_engine/catalog.py:233-313`, `discovery.py:162-223`, `_engine/connections.py:56-63,332-354`, `_ui/connection_view.py:454-469`, `tests/e2e/test_replay_plumbing.py:89-93`, `.github/workflows/screamingface-e2e-replay.yml` |
| URL4 `JobRunner.schedule(profile=, credential=)`: abstract carrier, no caller or implementation inside `packages/url4`; `credential` is never read. | `packages/url4/src/url4/streaming/interfaces/jobs.py:79-89` |
| Tests: 25 gateway test files construct `ProfileIndexStore`; by lifecycle they split four ways. 18 feature suites seed a Profile only as a precondition for route/feature behaviour (one also patches `ProfileIndexStore.get` on the class). 4 storage-invariant suites test the legacy store's own semantics (`test_profile_index.py`; OME-307 `test_profile_publication_locking.py`, `test_profile_oauth_flow_ownership.py`, `test_profile_delete_set_race.py`). 2 facade suites pin the HTTP write-facade contract with storage-specific assertions mixed in (`test_auth_routes.py`, `test_api_key_routes.py`: forced `CredentialBlobMutationConflict`, an upsert double, blob inspection). 1 bootstrap suite constructs the store for the bootstrap path (`anthropic/test_bootstrap.py`). Only the 18 are shared-fixture candidates. Coupling to the resolver cluster: three modules import names from `routes/chat_credentials.py` by path, one imports the module object for a source scan, two patch `_inject_credentials` / `_credential_target_for_chat` on the `routes.chat` namespace (these break once `chat.py` stops binding those names), and one patches `ProfileIndexStore.get` at class level. Storage-invariant suites and the PostgreSQL lane (`needs_postgres`) exist. Historical gate baseline: 4104 passed, 58 skipped, 92.53 % coverage, one pre-existing bcrypt timing failure; not rerun in this pass. | `tests/unit/test_chat_profile_default_provenance.py:20`, `core/test_no_auth_mode.py:35`, `gemini/test_profileless_auth_provenance.py:9`, `test_model_parameters_discovery_wiring.py:25,155`, `openrouter/test_openrouter_routing_policy_route_rejections.py:193,285`, `usage_accounting/test_chat_route_accounting.py:1057`, `test_chat_global_cache_effective_request.py:536`; `tests/integration/test_lifecycle_postgres_races.py`; scratchpad `gates-aigateway-baseline.txt` |
| Persistence: Tortoise 1.1.8 native migrations `0001`–`0010`; Helm pre-upgrade job runs migrations with the DSN only (no `AIGATEWAY_SECRET_KEY`); `PartialIndex` has no unique flag; composite PKs rejected. Local vs Hosted differ only by account resolution (`disabled` → anonymous account). | `migrations/`, `charts/aigateway/templates/job-migrate.yaml`, `core/auth/middleware.py:19,184` |

## 3. The boundary

### 3.1 Placement and rationale

The three credentialed routes already depend on one resolver plus one pre-cache defaults read; the
smallest useful boundary makes that cluster the contract and changes only its **surface**: the
triplicated header normalisation moves inside, the typed tuple becomes an opaque target, the
read-path mutations become named operations, and the pre-cache read stays a separate operation.
The body of the Profile-backed implementation is today's code relocated, not rewritten. Nothing is
a separate deployable, a plugin framework or a second credential authority.

The port lives in a new `core/provider_access/` package (core defines ports; the package imports
only core stores, `plugin_base` and `profile_models` literals). The Profile-backed read
implementation also lives there because it composes two core stores. The Profile-backed **admin**
implementation receives the bodies of `upsert_api_key_profile` and `delete_profile_for_account`;
the routes keep their HTTP shells, because core must not import routes. `routes/chat_credentials.py`
and `routes/chat_profile_defaults.py` remain re-export shims until the importing tests are
re-pointed; the shim's resolver renders refusals through the edge table, so by-path importers still
see today's `HTTPException` bodies. Every new module stays at or below 450 lines (`chat_credentials.py` is 483 today); the
relocated bodies total roughly 550 lines, so the Profile-backed implementation is split by
responsibility into at least three modules (resolve + defaults read, authorize + dispatch failure,
admin + availability) rather than one. Layout (split fixed at the A1 RED step; module names carry
no leading underscore by owner decision D19, `__init__.py` being the one Python-required exception):
`selector.py`, `types.py`, `ports.py`, `auth_mode.py`, `defaults.py` (pure `apply_defaults`),
`profile_backed.py` (resolve, repair, Connection fallback), `profile_authorize.py` (strategy, reauth
URL, authorization, dispatch failure), `profile_defaults.py` (legacy-defaults reader), at A3
`profile_admin.py` (admin bodies, availability); the rendering table is
`routes/provider_access_http.py`.

### 3.2 Contract: types

- `Selector(name: str, explicit: bool)` with `is_default`. `Selector.from_header(raw)`: absent,
  blank or whitespace → `("default", explicit=False)`; otherwise the stripped value, `explicit=True`.
  The only interpretation point for `X-Profile`.
- `ResolvePolicy = DISPATCH | DATASHEET`. `DATASHEET` permits an absent target only when
  `selector.is_default` (today's `missing_target_ok=profile_name == "default"`).
- `CredentialTarget` (opaque): `kind ∈ {stored, ambient, none}` (`ambient` = provider-declared
  chatless env credential, `none` = provider needs no credential); `auth_type`; `credential_name`
  (the storage-neutral strategy/cache key of §2); `context_stamp` (byte-identical to today's
  `prof:`/`conn:`/`anon` strings in the window); `reauth_url`; `defaults` (window-only); a private
  backing handle that only the producing implementation reads. No `Profile`, `ProfileState`,
  `OAuthConnection`, UUID, slot or locator reaches a consumer.
- `RequestDefaults`: structurally today's six-field `ProfileDefaults`; window-only; deleted with D2.
- Refusals (typed, core): `TargetMissing`, `TargetPending`, `TargetReauthRequired(reauth_url)`,
  `SelectorAmbiguous(provider)`, `SelectorUnknown(provider, requested, valid_labels)`,
  `WriteConflict(kind ∈ {retry_exhausted, superseded})` (admin interface; rendered 503
  `profile_index_conflict` / 409 `profile_conflict` on the legacy shells), `UnsupportedAuthMode`,
  `SelectorUnsupported` (sunset only). One rendering table
  at the HTTP edge (`routes/provider_access_http.py`) maps them to today's status codes and detail
  bodies verbatim; codes are decided at the edge, never inside an implementation.
- `AvailabilityRow(provider, status ∈ {not_connected, pending, connected, needs_reauth, error})` —
  provider and status only (D17, decided 2026-09-14): no ids, labels, defaults, `auth_method`,
  `account_label` or secrets; `CredentialSummary` for admin listings
  (masked; window-only projection fields keep today's admin JSON byte-identical).

### 3.3 Operations: two interfaces

`ProviderAccess` (read/resolve, held on `app.state.provider_access`):

1. `defaults_for(account_id, provider, selector) -> RequestDefaults | None` — never raises; `None`
   strictly means unreadable; never inspects state or Connections; no memoisation shared with
   `resolve` (two independent reads, as today). Window-only.
2. `resolve(account_id, provider, selector, *, plugin, policy) -> CredentialTarget` — raises the
   refusal family; Profile-backed order and codes exactly as §2 row 3.
3. `auth_mode(target, plugin)` and `contract_auth_mode(target, plugin)` — provider-declared mode
   logic, including the keyless datasheet branch. These, not `resolve`, raise `UnsupportedAuthMode`
   (400 `api_key_not_supported` / `provider_does_not_use_oauth`); `authorize` raises it when the
   target says `api_key` but the provider has no strategy.
4. `authorize(target, *, plugin, provider) -> Authorization(headers, credential_name, auth_type)`
   with a pure `apply_authorization(body, headers)` — strategy build via the shared cache, today's
   fenced error marking, eviction, session invalidation and `touch_last_used`.
5. `record_dispatch_failure(target, status, detail, *, plugin)` — the store half of the dispatch
   failure marker; the plugin hook that decides whether a status marks an error stays in the route.
6. `availability(account_id) -> tuple[AvailabilityRow, ...]` — no secret read, no refresh, no
   mutation. The Profile-backed implementation reproduces the Engine aggregation exactly
   (authenticated > pending > error; Connection-only accounts show `not_connected`; `needs_reauth`
   never emitted in the window), proven by golden-equivalence tests at A3; folding Connections in
   is a later flagged behaviour change.

`ProviderCredentialAdmin` (mutations, `app.state.provider_credential_admin`):

7. `list(account_id, provider=None) -> tuple[CredentialSummary, ...]`.
8. `set_api_key(account_id, provider, *, raw_api_key, legacy_name, defaults)` — Profile-backed:
   `upsert_api_key_profile` with `legacy_name or "default"`; wholesale defaults replacement and
   delete-wins preserved; both conflict contracts unchanged in the window: retry exhaustion → 503
   `profile_index_conflict`, superseded publish (delete-wins) → 409 `profile_conflict`.
9. `delete(account_id, provider, *, legacy_name)` — Profile-backed: `delete_profile_for_account`
   (index CAS first, blob second, one transaction).

Deliberately on no port: OAuth start/callback/refresh (write authority, D14), PATCH metadata,
bootstrap, `/v1/oauth/connections*`, token delegation. They stay owners of their stores.

Why two interfaces: different callers (per-request routes vs management shells), different fencing
(narrow error-marking CAS vs the OME-307 lock order, generation fencing and delete-wins), an
unresolved dual-write ownership (D14) that must be settled before any backing switch, and D8
(API-key only, masked, no OAuth start, no defaults editor) becomes a structural property of the
admin interface. The read interface is not pure: its two mutating operations are the writes the
read path performs today, named so that consumers stop touching rows.

### 3.4 Profile-backed implementation (relocation map)

| Today | Becomes |
| --- | --- |
| `routes/chat_credentials.py:170-275` (fallback + resolver), `:145-167` (repair) | `ProviderAccess.resolve` |
| `routes/chat_profile_defaults.py:37-85` | `ProviderAccess.defaults_for` |
| `routes/chat_credentials.py:33-85` (auth modes), `:350-391` (`_apply_defaults`) | core helpers `auth_mode`/`contract_auth_mode`, `apply_defaults` |
| `routes/chat_credentials.py:278-330,394-483` (strategy, reauth URL, inject) | `authorize` + `apply_authorization` |
| `routes/chat_dispatch.py:45-94` store half | `record_dispatch_failure` |
| raw listing `routes/auth.py:498-501` (`ProfileIndexStore.list`, no aggregation) + the Engine aggregation `connections/profile_availability.py:14-37` (authenticated > pending > error; none → not_connected) | `availability` — the Engine rule reproduced gateway-side at A3, golden-equivalent to `decode_profile_statuses` over recorded listings; the Engine decoder is deleted at A4 |
| `routes/auth.py:1251-1359,1370-1402` | `ProviderCredentialAdmin.set_api_key`/`delete` bodies; routes keep shells |
| `routes/chat.py`, `model_parameters.py`, `model_admission.py`, `chat_dispatch.py` | call the port; import no Profile/Connection types |

### 3.5 HTTP-level boundary

Window: `POST /v1/chat/completions`, `GET /v1/model-parameters`, `POST /v1/models/admit` keep
byte-identical contracts (header semantics, codes, `reauth_url` shapes, `scope`, `Vary`); all
tenant and admin Profile routes and `/v1/oauth/connections*` are unchanged. Nothing outside the
gateway process has to change to introduce the adapter.

Successors (each an owner decision, published only when the consumer that needs it is scheduled):

- Availability for the Hosted Engine (D17, decided 2026-09-14): a caller-scoped read-only
  `GET /v1/provider-access` returning rows of `provider` and `status` only (no names, states,
  defaults, ids, locators, `auth_method`, `account_label` or secrets; `Cache-Control: private,
  no-store`; inbound `X-Profile` documented and tested as non-selecting, exactly like today's
  listing). Published at A4 together with the Engine switch, not earlier. The 2026-09-10
  alternative `GET /v1/oauth/connections?effective=true` is rejected: it presupposes the Connection
  backing and exposes labels, ids and locators.
- Admin successor (D18): a pair-addressed, API-key-only, masked resource without a name segment and
  without defaults (`409` when a pair holds more than the single compatible record; the legacy
  routes remain the way to act on named records). Its final shape depends on D11/D12; the in-process
  admin interface lands first so the HTTP shape changes once. The Admin UI cannot move its
  attach/replace call before the D2 cutover because that call carries defaults.
- Legacy Profile routes: unchanged behaviour in the window; OpenAPI deprecation flags and any
  `schema.d.ts` regeneration are coordinated changes recorded with the gateway revision.

### 3.6 Legacy selector handling

Window (D4, supported semantics preserved): the Profile-backed `resolve` honours every selector
exactly as today; absent/blank/whitespace mean `default`; a named selector that matches nothing
still returns 404 with the requested label; nothing is ignored or retargeted. Ambient vs
caller-supplied provenance is not expressible today (the gateway sees only the header); the
implementation counts `explicit` vs default selectors without logging names to build the D4 census.

Sunset (separate stage, owner-set): a boundary-level policy makes `Selector.from_header` raise
`SelectorUnsupported` → 400 `x_profile_unsupported` for present, non-blank selectors the backing
cannot honour; absent selectors resolve to the pair's effective target; an explicit literal
`default` is accepted only with the equivalence proof D4 requires. Any implementation that cannot
honour a selector must refuse, never return a different target (a port contract test enforces
this). The policy has one enforcement point — the parse step, configured at the composition root;
implementations never consult it. Because the gateway is the sole interpreter, a rejected selector on a queued run surfaces as
a 400 on that run; carrier retirement and the accepted-work disposition therefore precede enabling
the policy. Hosted listing routes retire with a code, never with an empty list.

### 3.7 Defaults (D2 preserved)

`defaults_for` stays on the interface as a distinct never-raising operation, but its Profile-backed
body is a separately composable legacy-defaults reader (window-only) that the Profile-backed
implementation delegates to and that any later backing composes unchanged until stage C, so
switching the backing and cutting over defaults remain independent switches (D16); chat keeps its
order: defaults → merge → cache lookup → resolve. No defaults enter Connections, slots, presets, jobs or any new HTTP
resource; the successor admin request forbids a `defaults` key (422) instead of ignoring it; the
Profile-backed `set_api_key` passes `defaults=None` from any defaults-free caller so stored values
are preserved, never wiped. At the explicit cutover: `defaults_for`, `apply_defaults`,
`CredentialTarget.defaults`, the chat merge, `invalid_profile_defaults` attribution and the request
fields go together; legacy writes carrying defaults are rejected; the UI fieldset and its tests
retire; cache-key impact is tested, not assumed. A backing switch performed before the cutover must
keep reading the encrypted legacy index for defaults only (D16), otherwise defaults would silently
stop applying.

### 3.8 Connection-native paths and the dual write

`/v1/oauth/connections*`, the token service and the Local Engine adapter are not routed through
the port; the Profile-backed `resolve` keeps today's Connection fallback, so Connection-only
accounts dispatch exactly as before. The dual OAuth write (§2) is outside the boundary: the adapter
neither adds to nor fixes it. Stage 0 pins it with a characterisation test; D14 must name one
owner before any second implementation is enabled, because a label-match fallback over shadow
Connections could otherwise resurrect a deleted credential.

### 3.9 Call paths before and after

| Path | Before (17048f5d) | After A1/A2 (window) |
| --- | --- | --- |
| Chat | `chat.py:242` parse → `:306` `profile_defaults_for_key` → merge → cache → `:361` `_credential_target_for_chat` → `resolved_auth_mode(profile, connection)` → `:461` `_inject_credentials(profile, connection)` → dispatch → `chat_dispatch.py:45` marks Profile/Connection | `Selector.from_header` → `defaults_for` → `apply_defaults` → cache (unchanged) → `resolve(DISPATCH)` → `auth_mode(target)` → `authorize(target)` + `apply_authorization` → dispatch → `record_dispatch_failure(target)`; same order, same codes |
| Model parameters | `:134` parse → `:140` resolver with `missing_target_ok` → `_contract_auth_mode(plugin, profile, connection)` → `_context_identity` reads fields → scope/Vary | `Selector` → `resolve(DATASHEET)` → `contract_auth_mode(target)` → `target.context_stamp` → scope/Vary literals unchanged |
| Admission | `:106` parse → resolver → string-match codes → presence | `Selector` → `resolve(DISPATCH)` → catch `TargetReauthRequired`/`TargetPending` → same relayed pairs → `target.kind == "stored"` |
| Hosted Engine | `app.py:404` profiles → `GET /v1/auth/profiles` → 3-state aggregation → Connection DTO | window: identical; after D17: one adapter-internal switch to the successor listing, `listing_source` → a hosted/local mutability flag, DTO unchanged (SDK decoder untouched) |
| Local Engine | `/v1/oauth/connections*`, label `screamingface` | unchanged; label rule reconciled with the effective rule only at Stage B (D3) |
| Admin UI | admin Profile routes; PUT with six-field defaults | window: identical; list/delete may move after D18; attach/replace moves only with the D2 cutover |
| SDK | relayed codes, scope literal, strict decoder | unchanged until the sunset renames codes (same release train as the gateway change) |
| Carrier chain | REST → `schedule(profile=)` → env → runner → header → gateway | unchanged; retired at Stage D after disposition |

## 4. Consumer migration table

Knowledge: D direct Profile API/model · S selector carrier only · B shared machinery · W wire
vocabulary only. Stages per §5. "Adapter-first change" describes the window unless a stage says
otherwise.

| Consumer | File / operation | Knowledge | Adapter-first change | Stage | Migrate? |
| --- | --- | --- | --- | --- | --- |
| Chat route | `routes/chat.py:242,306-308,323,361-377,461-470,490-502` | D | port operations per §3.9; ordering preserved; HTTP unchanged | A2 | yes |
| Model parameters | `routes/model_parameters.py:33-35,72-75,78-94,134-148,178,192-216` | D | `resolve(DATASHEET)`, `context_stamp`, `contract_auth_mode`; scope/Vary frozen | A2 (literals at D) | yes |
| Admission | `routes/model_admission.py:106-131` | D/W | typed refusals; same relayed codes | A2 | yes |
| Dispatch failure marking | `routes/chat_dispatch.py:30-35,45-94` | D | `record_dispatch_failure`; module imports no row types | A1/A2 | yes |
| Resolver cluster | `routes/chat_credentials.py:33-483` | D | becomes the Profile-backed implementation; shim keeps names | A1 | implementation |
| Pre-cache defaults read | `routes/chat_profile_defaults.py:37-85,88-142` | D | `defaults_for`; rejection helper stays; both retire at C | A1 / C | implementation |
| Composition root | `main.py:406-408,295-307` | — | wire `provider_access` (A1) and `provider_credential_admin` (A3); conflict handler unchanged in window | A1/A3 | yes |
| Tenant Profile routes | `routes/auth.py:498-518,1158-1424` | D | list/get render `availability`/`list`; PUT/DELETE become shells over the admin interface; PATCH/OAuth/refresh untouched; retire at E | A3 / E | yes (sunset) |
| Admin Profile routes | `routes/admin.py:243-258,285-337` | D | shells over the admin interface; PATCH stays direct; DTO unchanged | A3 / E | yes |
| Write facades | `routes/auth.py:1251-1359,1370-1402` | D | bodies move to the Profile-backed admin implementation with their OME-307 tests | A3 | yes |
| Shared OAuth callback dual write | `routes/auth.py:799-801,870-911,957-1025` | D + Connection | untouched; characterisation test at Stage 0; owner (D14) before B | 0 / B | yes (B) |
| Bootstrap | `main.py:210-222`; `plugins/anthropic_provider/bootstrap.py:59-73` | D | untouched in window; writes through the admin interface at B | B | yes |
| Provider plugin hooks | `core/plugin_base/_provider.py:331-349,373-378` | B | names only; optional rename at E | E | selector-only |
| Gemini env credential | `plugins/gemini_provider/plugin.py:190-196`, `chat_handler.py:43-44,151-166` | outside | `kind="ambient"`; boundary never reads env; account-unscoped exposure recorded, not closed | A1 (type) | no |
| Connection routes, token service | `routes/oauth_connections.py:46-471`; `core/oauth/token_service.py:67-136` | B | untouched | — | no |
| Hosted Engine availability | Engine `connections/aigateway.py:36,79-84,169-173,208-212`; `profile_availability.py:14-37`; `app.py:404` | D | window unchanged; one switch to the D17 successor; flag → mutability; decoder replaced; DTO unchanged | A4 | yes |
| Local Engine + BYOK | Engine `connections/aigateway.py:85-164,250-256,280-302`; `local.py:205` | Connection | unchanged; D3 reconciliation at B | B | no |
| Engine carrier chain | Engine `rest/routes.py:485-488,524`; `ports.py:68`; `adapters/inprocess.py:179-185`; `runner_queue.py:227-228`; `worker/supervisor.py:741-742`; `runner/main.py:281`; `runner/connector.py:885-886`; `catalog/aigateway.py:239-240`; `connections/aigateway.py:410-411` | S | unchanged; Stage 0 pins ambient inheritance; retire at D after disposition and env audit | D | selector-only |
| URL4 `schedule(profile=)` | `packages/url4/src/url4/streaming/interfaces/jobs.py:79-89` | S | unchanged; retire after Engine (S9 after S6) | D | selector-only |
| Admin UI list/delete | `client.ts:249-251,271-280`; `actions.ts:219-237`; `detail.tsx:127-143` | D | unchanged in window; moves after D18 | D18 | yes |
| Admin UI attach/replace + defaults | `actions.ts:161-217`; `client.ts:259-269`; `form.tsx:170-192` | D | stays on the legacy route until the D2 cutover; then defaults controls drop and the call moves | C | yes |
| Admin UI error classification | `client.ts:105-123`; `lib/auth.ts:66-70` | W | unchanged while 503 `profile_index_conflict` and 409 `profile_conflict` are emitted; successor codes mapped at D18/C | D18 | yes |
| Admin UI schema | `lib/aigateway/schema.d.ts` | G | regenerate when OpenAPI changes; record the gateway revision | D18 / C | yes |
| SDK diagnostics, scope, decoder, e2e pin | `_engine/catalog.py:233-313`; `discovery.py:162-223`; `_engine/connections.py:56-63`; `tests/e2e/test_replay_plumbing.py:89-93` | W | no change while today's codes are emitted; mapping edit in the same release train as any rename | D | no (window) |
| Desktop tracked bundles | `apps/desktop/out/*` | unrelated | untouched (D9) | — | no |
| Test layer: HTTP pins | `test_chat_x_profile.py`, `test_model_parameters_route.py:99-148`, `test_chat_global_cache_effective_request.py:351,497`, `test_chat_request_cache.py`, openrouter admission | — | acceptance suite for A1–A4; green unmodified | A1 | no |
| Test layer: storage invariants | `test_profile_index.py`, `test_profile_oauth_flow_ownership.py`, `test_profile_publication_locking.py`, `test_profile_delete_set_race.py`, PostgreSQL lane | — | unchanged through A4; re-expressed on the new backing at B | B | yes |
| Test layer: fixtures and lifecycle | 18 feature / 4 storage-invariant / 2 facade / 1 bootstrap suites constructing `ProfileIndexStore` | — | 18: optional `seed_credential` helper at A2, swap to the new backing at B. 4: stay on the legacy store until E; the new store gains its own invariant suites at B. 2: keep pinning the facade contract through A3 (shells) and B (legacy routes byte-identical); at B their storage-specific assertions are split — the HTTP-contract part stays, the storage part is re-expressed on the new backing or moved to the storage suites. 1: changes at B when bootstrap writes through the admin interface. | A2 / B / E | 18 and 1 yes; 2 split; 4 no |
| Metamodel | design catalog `component/credential-store`, `protocol/{provider-access,administration,chat-processing,model-discovery}`, solution `protocol/{completions,model-catalog}` | — | additive text for the port and any new operation after M0; successors at D/E | A1 text / D / E | yes |

## 5. Staged sequence

Each stage is its own gate; later stages inherit nothing from an earlier approval.

| Stage | Scope | Acceptance | Tests |
| --- | --- | --- | --- |
| **A0** planning (this pass) | spec/plan/task updated; D7 conflict and D11–D18 presented | owner approves A1 explicitly | none |
| **0** characterisation, no runtime change | pin: Profile `default` wins over active Connections; whitespace `X-Profile`; shadow Connection reachable after Profile delete; persistent index fault outcome; Engine `_child_env` inherits ambient `AIGATEWAY_PROFILE` while in-process pops; Local 409 on mixed non-active rows | all new tests pass at HEAD with `apps/*/src` untouched | gateway unit suites; Engine `test_worker_child_env` (new) |
| **A1** port + Profile-backed read implementation | `core/provider_access/` package; relocation map §3.4 rows 1–5; wiring; HTTP rendering table; shims | whole gateway suite green **unmodified** (PostgreSQL lane included); OpenAPI byte-identical; no new route; `context_stamp` pin; files ≤450 lines; gates green | selector table; port contract suite parameterised over fake + Profile-backed; two-read no-memoisation; `None` = unreadable; refusal matrix; fake-adapter retarget test fails as designed |
| **A2** in-process consumers | four routes call the port; three normalisations, `_context_identity` and target inspection deleted; import guard; the two suites patching `_inject_credentials` / `_credential_target_for_chat` on the `routes.chat` namespace re-expressed at the port seam | HTTP pins green; guard test: `Profile`/`ProfileState`/`ProfileIndexStore`/`OAuthConnection` imported only by allowed modules; Vary/scope/codes unchanged. **As built (`OME-1207`): five suites re-expressed, not two** — `test_provider_access_helpers.py`, `test_provider_access_shims.py` and `test_model_execution_access.py` also reference `_context_identity`/`_contract_auth_mode`, which this stage deletes. `routes/chat_credentials.py` and its `profile_backed.py` translation helpers survive (A1 shim suite still imports them) with their removal point moved to Stage E; `core/admin_schemas.py` stays an owner because `AdminProfileOut.state` is wire-typed `ProfileState` | import-boundary test; `DATASHEET` equivalence table; admission relay test |
| **A3** admin interface + shells | facade bodies relocated; tenant/admin PUT/DELETE/list become shells; `availability` implemented | OME-307 suites and PostgreSQL races green unmodified; wholesale-replacement pin; JSON parity for tenant listing; no secret build on availability; both conflict contracts preserved (503 retry-exhausted, 409 delete-wins); `availability` equals Engine `decode_profile_statuses` per fixture | admin adapter tests; listing parity; availability golden |
| **A4** Hosted Engine on the successor listing (needs D17; two units — gateway route and Engine adapter, rule 8) | successor route; Engine hosted branch switched; `listing_source` → mutability flag; decoder replaced | per-fixture equality with today's aggregation; hosted mutations still refused before I/O; Engine `/v1/connections` DTO field set unchanged; SDK suites untouched and green; e2e replay lane green | gateway route tests (scoping, no defaults/ids/labels, no-store); Engine adapter tests incl. malformed body; layering gate |
| **B** backing transition (needs D11, D14, Q01–Q04) | option (a): S1 slot store + pair-marker authority + S4 backfill + R1 rehearsal + Connection-backed implementations; option (b): internal aggregate and its migration, still publishing Connections as the credential resource; bootstrap through the admin interface; fixture swap of the 18 feature suites; the 2 facade suites split (HTTP contract kept, storage assertions moved); the bootstrap suite re-targeted; the 4 storage-invariant suites untouched and new-store invariant suites added | port contract suites pass against the new implementation with consumers unedited; commit-time authority checks on every writer; quarantine keeps legacy authority; rollback rehearsed | §11 storage/authority/mapping/backfill/rollback matrices |
| **C** D2 cutover | §3.7 removals; legacy writes with defaults rejected; UI fieldset drops; attach/replace moves | saved defaults never influence requests; explicit parameters validate; no ignored writes; no wrong cache hits across the transition | REMOVE matrix; retired defaults tests with recorded mapping |
| **D** D4 selector sunset + carriers + vocabulary | reject policy; Engine stops emitting (S6), URL4 retires (S9); Vary/scope; neutral codes if adopted; SDK/e2e/UI copy in the same train | accepted work drained or dispositioned; ambient env audited; no silent retarget anywhere | 400 tests; carrier matrix; SDK mapping incl. retryable pending |
| **E** retirement and cleanup (G6, D6) | legacy Profile routes, classes, index store, bootstrap path, shims, hooks rename; tooling retirement list; guarded blob cleanup | named rollback build reads all it needs; no referenced blob deleted; catalog checks green after M0 | reference-fencing tests; tooling tests |

## 6. Conditions

### 6.1 Switching the backing behind the boundary

All of: D11 decided; D14 owner of the dual OAuth write decided and tested; the port contract suites
pass for the new implementation with consumer modules unedited; storage invariants (CAS, generation
fence, delete-wins, stale callback, tombstone) re-expressed on the new store on SQLite and
PostgreSQL; slot-naming compatibility proven (a migrated target reads its legacy-addressed blob via
an authoritative locator without re-entry or re-encryption); Q01–Q04 (versions, census, key access,
writer fencing); D3 quarantine keeps legacy authority; R1 rollback rehearsed after create, re-key,
replace and delete (D5); Local label rule reconciled with the effective rule or explicitly kept;
availability vocabulary change accepted (`needs_reauth`); defaults source defined for the
transition (D16); fixture swap of the 18 feature suites done so they exercise the new backing; the 2
facade suites split (HTTP contract green on the legacy shells, storage-specific assertions
re-expressed on the new backing); the bootstrap suite re-targeted to the admin interface; the 4
storage-invariant suites keep covering the legacy store until E and the new store has its own
invariant suites.

### 6.2 Retiring Profile APIs, selectors, storage and history

- APIs: successor published, its consumers moved (Hosted Engine, Admin UI), sunset date set,
  accepted-work disposition approved; retirement returns a code, never an empty list.
- Selectors (D4): provenance census (explicit vs default counts), queued and in-flight work carrying
  `AIGATEWAY_PROFILE` drained or dispositioned, worker ambient env audited, Engine emission and
  URL4 argument retired, then the gateway rejects present selectors with 400.
- Storage: after the backing switch, no unresolved quarantine, D6 retention fulfilled, the named
  rollback build no longer needs the legacy index.
- History: separately authorised cleanup; reference validation and deletion share one atomic
  boundary that also fences concurrent reference creation.

## 7. What the adapter does not solve (retained mechanism, conditional on D11 option a)

The boundary removes consumer knowledge; it does not migrate data, serialise concurrent writers,
own the OAuth dual write or provide rollback. The 2026-09-10 design for these is retained as the
mechanism for option (a) and as the semantic requirements for option (b):

- **Slot (D1):** `provider_credential_slots(id PK, account_id FK CASCADE, provider str(64),
  UNIQUE(account_id, provider), effective_connection_id FK NULL, generation int monotonic,
  migration_state none|migrated|quarantined, migration_note str(255) NULL, updated_at)`. Purpose: a
  persistent generation/tombstone fence and one effective reference per pair, never defaults.
  Tortoise 1.1.8: single PK plus `unique_together`; no unique partial index.
- **Locator authority:** Connection reads use the stored `credential_locator`, letting a migrated
  Connection read a Profile-addressed blob without re-entry; new Connections keep UUID locators.
- **State mapping:** authenticated+blob → active; authenticated without blob → error
  (`credential_missing`); pending → pending; error → error; no target → no effective; revoked/expired
  never effective; no auto-activation.
- **Mutation invariants:** commit-time authority, account/provider, selected-target, generation and
  state checks on every writer; one lock/CAS order for index/slot/row/blob; API-key publish fences
  the prior target and advances the generation; delete clears the reference before blob removal
  in one transaction; refresh/error cannot republish a superseded target.
- **E/B/C migration:** expand (schema only, Helm-safe) → backfill (application-owned CLI
  `python -m aigateway.migrate_profiles --dry-run|--apply --account|--all`, secret-aware, per-account
  transaction, classify before write, quarantine non-equivalent pairs, journal, resumable, never the
  pre-upgrade job) → contract (after G6/D6; reference-safe deletion).
- **Authority and rollback R0–R4:** R1 bridge fences pre-R1 writers before any pair switches; R2
  backfilled keeps quarantine on legacy authority; R3 cutover needs disposition and no quarantine;
  R4 cleanup after retention. The first canonical write, not running backfill, ends R0 eligibility;
  R0 return needs an independently proven reverse migration. Accepted queued/in-flight/redelivered
  jobs need a compatibility matrix and explicit disposition.
- **Concurrency and cache:** two caches stay distinct; the gateway keys the effective body only;
  Tavily retrieval lane untouched; `gateway_call_id` and redaction preserved; availability never
  reads secrets or triggers refresh.

## 8. Decision register

D1–D10 are preserved as decided; D11–D20 are new (D11, D14, D15, D16, D17, D19 and D20 decided; D12 carries a decided Stage B rule and stays open for Stage D; D13 and D18 open).
Conflicts are presented, not resolved.

| ID | Decision | Contract | Status |
| --- | --- | --- | --- |
| D1 | Persistence | slot with single PK + UNIQUE pair, generation fence, no defaults | preserved; **conditional on D11(a)**; option (b) needs the same semantics in its own table |
| D2 | Defaults | full REMOVE at an explicit cutover; no transfer anywhere; behaviour preserved until then | settled 2026-09-10; restated by the adapter-first input |
| D3 | Collisions | only unambiguous, compatibility-safe automatic mappings; otherwise quarantine | preserved; applies at Stage B and to the admin successor's pair→record mapping |
| D4 | Selector retirement | supported semantics in the window; reject unsupported after sunset; never silent | preserved; enforcement point is now the boundary's parse step; activation detail open: blank header treated as absent or rejected, literal `default` accepted only with the equivalence proof |
| D5 | Rollback | tested R1 after the first canonical write; R0 needs proof | preserved (Stage B) |
| D6 | Retention | API sunset separate from data retention | preserved (Stage E) |
| D7 | Units | first units were S1–S3 | **re-approved 2026-09-14:** Stage 0 then A1 are the first units; U0/U0e/U1 authorised and filed; stop after A1 for review; A2–A4 and any backing migration need a new authorisation |
| D8 | Admin API | API-key only, masked, no OAuth start, no defaults editor | preserved; correction: the UI has a defaults fieldset on attach today (no PATCH editor) |
| D9 | Desktop output | untouched | preserved |
| D10 | Catalog retirement | built-in `supersedes`, deprecate without deletion | preserved |
| D11 | Backing model | (a) transfer to Connections + slot, remove Profiles; (b) rework the current Profile mechanisms into an internal aggregate that still publishes Connections as the credential resource | **decided 2026-09-22 (owner; design PR #23): (a), conservatively** — one deterministic effective credential per `(account, provider)` pair, no selectable accounts or credentials per provider; Stage B moves credential authority to Connections through the `provider_credential_slots` pair marker and locator-authoritative reads without secret re-entry (`OME-1208`); Profile storage, routes and schemas are retained until Stage E (`OME-1209`); D17/D18 shapes follow from it; whether `Selector` survives is D12 (Stage D) |
| D12 | Selector after cutover | (a) selector-less pair → one target, multi-Connection pairs dispositioned (D3); (b) label disambiguation stays supported (today's 409) | **open** for Stage D; **Stage B rule decided 2026-09-22 (owner; design PR #23):** a Connection-only pair with several active Connections is not migrated (`none`) — today's label resolution and its 409 stand; the 2026-09-10 selector-less `resolve_effective` would change today's 409 behaviour, so it is not the consumer signature in the window |
| D13 | Approved protocol surface | removing `X-Profile` from solution `completions` v6 / `model-catalog` v5: successor protocols vs prose bump | **open** (M0) |
| D14 | Dual OAuth write owner | (a) gate the Profile flip and stop shadow Connections; (b) shadow Connection canonical, Profile a view; (c) both until B with a reconciliation rule | **decided 2026-09-22 (owner; design PR #23): per-pair authority marker** — for a `migrated` pair the Connection backing owns every write, including the OAuth callback publication (the Profile routes are facades over it); an unmigrated or `quarantined` pair keeps today's legacy behaviour, shadow Connection write included; never two independent write owners for one owned pair; applied by `OME-1208`; the census stays a Q02 item for the apply run |
| D15 | Hosted read-only rule | (a) explicit mutability flag; (b) gateway-side policy | **decided 2026-09-14: (a)** explicit flag on the Engine connections adapter, Hosted `mutable=False`, Local `mutable=True`; any Hosted mutation refused before network or storage I/O; applied at A4 |
| D16 | Defaults during transition | (a) legacy index read-only for defaults until cutover; (b) cutover precedes the switch | **decided 2026-09-22 (owner; design PR #23): (a)** — a migrated pair's legacy index entry remains a defaults-only compatibility document during the transition; Stage B creates no Connection defaults, presets or hidden saved defaults; the full REMOVE at Stage C (D2) is unchanged |
| D17 | Availability successor | (a) neutral `GET /v1/provider-access` (recommended); (b) `?effective=true`; plus whether Connection-only accounts fold into the window listing | **decided 2026-09-14: (a)** caller-scoped read-only `GET /v1/provider-access` returning only `provider` and `status` ∈ {not_connected, pending, connected, needs_reauth, error}; the Profile-backed implementation never emits `needs_reauth` in the window; no ids, labels, defaults, `auth_method`, `account_label` or secrets; `private, no-store`; `X-Profile` non-selecting; A3 reproduces the Engine aggregation with golden-equivalence tests; the Hosted Engine switch is A4, separately |
| D18 | Admin HTTP successor | pair-addressed neutral resource: publish after D11, or now beside the legacy routes | **open**; the UI attach call cannot move before C regardless; the UI defaults fieldset stays until C unless the owner drops it earlier; conflict codes on the successor to confirm — the legacy contract has two (503 retry-exhausted, 409 superseded-by-delete) |
| D19 | Module naming | no file introduced by the provider-access unit has a name beginning with `_`; `__init__.py` is the required Python exception; underscores between words in `snake_case` names are allowed | **decided 2026-09-15**; applied by `OME-1204` (A1 follow-up: five package modules and two test helpers renamed, rename-only); binds A3's `profile_admin.py` and every later module of the package |
| D20 | Provider identity naming | final product/API/domain noun is `Connection`; `provider access` is the boundary/successor family; `Profile` is legacy compatibility/current backing only; `Provider Account` is not a resource/API/UI noun | **decided 2026-09-16** by `OME-1210`; binds OME-1207 wording and every successor API/doc/UI change; D11 remains open for backing mechanics |

Q01–Q07 and M0 stand as in the previous revision (versions and external callers; authorised census
and key access; writer fencing; rollback rehearsal; D3/D4 compatibility; clean branch; catalog
write/version handling). Spec-text conflicts with the 2026-09-10 revision: §4.4 selector-less
signature and §4.6 Connection-shaped successors are superseded as consumer contracts by §3; their
mechanism survives in §7. No owner decision is contradicted.

## 9. Differences from the previous plan

| Previous unit | Verdict | Reason |
| --- | --- | --- |
| S1 slot store + locator factory | necessary for D11(a); deferred behind D11 | not needed to introduce the boundary; the locator-authoritative factory is needed under either backing |
| S2 shared resolver | necessary; **reordered first** as A1/A2, Profile-backed | the resolver exists; only its surface changes |
| S2 pair-marker facade | necessary for D11(a) at Stage B | commit-time authority routing between legacy and canonical writers cannot be replaced by a port |
| S3 admin Connection API + `effective=true` | reshaped (D17/D18); `connection_id` addressing redundant as a consumer boundary | it hard-codes the backing; in-process admin interface lands at A3 instead |
| S4 backfill | necessary for D11(a), unchanged in content; after D14 | option (b) needs the same discipline for its own migration |
| S5 Hosted Engine | reordered to A4 (after D17), before any storage work | one switch only |
| S6/S9 carrier retirement | unchanged; Stage D | disposition-gated |
| S7 Admin UI | later than before: list/delete after D18, attach/replace with C | the attach call carries defaults |
| S8 SDK | no work in the window; mapping edit only at D | codes unchanged |
| S11 cutover, S12 cleanup, S13 catalog | unchanged in content; S13 gains additive text at A1 | as before |
| Route-level "facade in chat_credentials.py" | redundant | the cluster itself becomes the implementation |

## 10. Risks and unresolved items

- D7 re-approval and new first units; the pass created no issue.
- Dual OAuth write (D14) is preserved by the Profile-backed implementation, including
  delete-leaves-shadow reachability; security-relevant; census not run.
- Hosted availability semantics for Connection-only accounts and `needs_reauth` change at the
  backing switch unless deliberately reproduced (D17).
- Post-sunset 400 on queued runs with `AIGATEWAY_PROFILE` and on workers with an ambient value
  (out-of-band injection unverified; chart supplies none).
- Re-pointing the 4 storage-invariant, 2 facade or 1 bootstrap suites to a shared seed fixture would
  silently weaken the CAS, locking, delete-wins and bootstrap checks; only the 18 feature suites are
  fixture candidates. The facade suites carry a second risk: leaving their storage-specific
  assertions unsplit at B either breaks them or lets them silently stop covering the new backing.
- Two independent index reads per chat request must stay independent; a persistent index fault is
  an unhandled exception today; both pinned, neither changed.
- Relocating a 483-line module carrying SF-282/SF-244/OME-1167 invariants; shims and parity tests
  are the guard; three test modules import by path, one scans the module object, two patch the
  `routes.chat` namespace (re-expressed at A2) and one patches the class method.
- Gemini's process-wide env credential is account-unscoped in Hosted mode; recorded, not closed.
- `schema.d.ts` regeneration is manual; record the gateway revision each time.
- CI path filters run no consumer lane for a gateway-only diff except the e2e replay lane; run
  Engine/SDK/UI gates explicitly at A1–A4.
- Metamodel writes need M0; class retirement collides with the exporter import and the
  disappearance guard and must be one change set.

## 11. Test matrix (RED tests land with their stage)

- Boundary: selector table; refusal matrix with legacy bodies; `None` = unreadable; two-read
  independence; `context_stamp` parity; fake-adapter contract suite; retarget-refusal test.
- Consumers: import guard; `DATASHEET` equivalence; admission relay; HTTP pins unmodified.
- Admin: OME-307 ordering at the adapter seam; wholesale defaults replacement pin; listing parity;
  no secret build or refresh on availability.
- Hosted Engine: per-fixture aggregation equality; mutation refusal before I/O; DTO field-set pin.
- Backing (B): slots/authority crossing/mapping/bridge/backfill/rollback matrices of the previous
  revision, on SQLite and PostgreSQL.
- Cutover (C) and sunset (D): REMOVE matrix; cache agreement; 400 tests; carrier compatibility
  matrix; SDK mapping with retryable pending; e2e replay pin updated in the same PR.
- Cleanup (E): reference fencing; tooling retirement list; disappearance guard still fails on an
  unlisted disappearance.

## 12. Metamodel

The AIGateway catalog is committed in `screamingface-design` at `679aa8f` (PR #18): 110 entities
(91 generated + 19 retained; 106 approved, 4 draft). Generated cards carry `source_revision
802bed9a` (last commit touching `apps/aigateway/src`); only authored `profile-defaults` cites
`17048f5d`. The app checkout holds an untracked `solutions/` overlay with the generator tooling
(`_tools`, `_coverage`) the design repo does not carry; no CI gate runs it. Do not move the catalog
or its history into the application repository.

- No in-process consumer-facing contract exists in the catalog; `component/credential-store` lists
  three in-process boundaries and places resolution inside `chat-api`. The port is representable
  as a content bump on that card plus renamed workflow messages in `chat-processing`,
  `chat-streaming` and `model-discovery`, or as a new in-process protocol entity modelled on
  `plugin-contract` (owner choice, S13). Either is additive; M0 gates any write.
- `X-Profile` is contract-grade in solution `completions` v6 and `model-catalog` v5 (D13);
  `gateway-admin` v4 encodes Profile admin operations (successor at D/E); `token-delegation` v5
  draft is Connection-native.
- Carriers `AIGATEWAY_PROFILE` and `schedule(profile=)` are absent from the catalog; the Engine card
  omits the provider-access surface it consumes (`/v1/providers`, `/v1/oauth/connections*`,
  `/v1/auth/profiles`). Document before retiring; do not invent edges without evidence.
- Tool guards unchanged while classes stay exported: exporter imports `Profile`/`ProfileIndex`;
  projector inventory pin; disappearance guard; authored `profile-defaults` equivalence check;
  coverage requires protocol text for every operation and an owner for every source file.
