---
ticket: OME-1209
parent: OME-1138
status: accepted   # owner approval 2026-10-14; E1b and the E3 catalog delta amended 2026-10-15; E4 split and its marker rule amended 2026-10-20; each landing gets its own leaf issue under OME-1138 at PR-open
created: 2026-10-14
base: origin/main 9be66ecb0
spec: docs/spec/2026-10-14-OME-1209-retire-legacy-profiles.md
---

# OME-1209 — Stage E: retire the legacy Profile surface (plan)

The contract and the owner decisions are in the spec (§3 R1-R5, §7). This plan holds the sequence,
the evidence that shaped it and the tests per landing. It decides nothing the spec does not, except
where §6 below says so.

## 1. Evidence on the base

Paths are relative to `apps/aigateway/src/aigateway` unless stated.

| Fact | Source |
| --- | --- |
| `reauth_url` is built in six places, five of them as an inline f-string on the legacy path | `core/provider_access/profile_authorize.py` `reauth_url_for`; `connection_authority.py:103,240`; `connection_facade.py:108`; `profile_backed.py:173`; `routes/auth.py:213` |
| An api-key Connection already gets its successor URL (`/v1/oauth/connections/{id}/api-key`) | `profile_authorize.py` `reauth_url_for` |
| No client outside the gateway reads `reauth_url` | `git grep reauth_url` over `packages/`, `apps/screamingface-engine`, `apps/aigateway-ui/src`: no match |
| The successor writes work on a pair the legacy Profile still owns: the first native write claims the pair | `core/provider_access/connection_native.py` `claim_native_write`; `routes/oauth_connections.py` `create_api_key_connection` |
| 13 gateway test files assert a legacy `reauth_url` | `git grep -l reauth_url -- tests` filtered on `profiles/` |
| `profile_models` is imported by 51 source files and 102 test files; it holds two neutral aliases, two name functions and four Profile models | `core/profile_models.py` |
| The saved-defaults pipeline survives only as declarations kept "until stage E" | `core/provider_access/defaults.py`, `profile_defaults.py`, `routes/chat_profile_defaults.py`, `routes/chat_credentials.py`, `ProviderAccess.defaults_for`, `CredentialTarget.defaults`, `RequestDefaults` |
| Profile-named plugin hooks are declared on the base and overridden by seven provider plugins | `core/plugin_base/_provider.py`, `_contract.py`, `plugins/*/plugin.py` |
| On a pair the legacy Profile still owns, chat reads the Profile first; a native successor write claims the pair (generation) but leaves `migration_state` unchanged, so an errored Profile keeps shadowing the new Connection | `core/provider_access/profile_backed.py` `resolve`; `connection_backed.py` `resolve`; `writer_floor.py` `claim_observed` |
| dev census 2026-10-15 (after one owner-run cleanup and backfill): every pair with a Profile document is `migrated` | spec §7 Q3 |
| D18 plan: "no bulk production migration is needed; the bridge serves later mutations" | `docs/plan/2026-10-02-provider-credential-admin-contract.md` §3 E. E4 removes that bridge, hence spec §7 Q3 |

## 2. Sequence

```
E1 successor pointers ─▶ E1b native re-authorisation ─┐
                                                      ├─▶ E3 route retirement ─▶ E3b dead core ─▶ (census + backfill, owner) ─▶ E4a readers ─▶ E4b writers ─▶ E4c hooks
E2a neutral types ────────────────────────────────────┤
E2b dead defaults ────────────────────────────────────┘
```

E1, E2a and E2b are independent and may be open at the same time; each is one PR. E3 starts after
E1 and E1b are merged **and** the census shows no Profile-owned pair in any environment: on such a pair the
successor does not fix an errored credential (§1), so its Profile route is the tenant's only repair
path until it is migrated. E4 starts only after the owner reports the census (§3 E4). E5 is a separate issue
(spec §7 Q4).

## 3. Landings

### E1 — successor pointers

- One builder, `successor_reauth_url(provider, *, auth_type=None, connection_id=None)`, in
  `core/provider_access/` replaces `reauth_url_for` and the five inline strings:
  - authorize-time, api-key, Connection known → `/v1/oauth/connections/{connection_id}/api-key`
    (unchanged);
  - authorize-time, api-key, no Connection → `/v1/oauth/connections/api-key`;
  - OAuth, and every resolve-time refusal where the target is unknown →
    `/v1/oauth/connections` (start a new flow; re-auth supersedes an errored Connection, SF-291);
  - a migrated api-key target names its effective Connection, so a re-key replaces the credential
    chat reads instead of creating a second row the marker ignores.
- `routes/auth.py:213` (inside the legacy refresh route, still live until E3) uses the builder too.
- Copy: no tracked Markdown outside `docs/spec|plan|work|tasks` cites a Profile route; the one
  stale sentence is `apps/aigateway-ui/README.md:17` ("finds a profile"), which E1 rewords.
  Error codes in copy stay (R3).
- Prior tests: the 13 files that pin the legacy URL change their expected value only. This is a
  contract change the spec approved (R2); it goes through an approval manifest
  `.claude/test-change-approvals/OME-<E1>.json` listing each file and assertion, shown to the
  owner before commit.

### E1b — native repair of a migrated OAuth pair (spec R6)

- Start (`routes/oauth_connections.py` `start_connection_oauth`): the pair it already observes
  is checked: when it is `migrated` and its effective row is unusable (`error`/`revoked`, any
  auth type), the flow names no label (the main connection; the replaced row's real label is
  inherited, a placeholder one is not), or it carries the requested label, the pending entry records that observed pair (new
  field `PendingAuthEntry.replaces_effective`) and the pending row takes a placeholder label (the
  callback gives it the requested one after revoking the old row). Any other pair is unchanged.
- Same provider identity as another row of the pair: the callback's one row-lock statement also
  locks every row holding that identity (`retire_replaced(..., identity_sub=...)`, still one
  ascending id order) and revokes it with the old effective row; the new row then activates with
  the identity and the fresh tokens. The repair is never treated as a duplicate, and no existing
  row is reused, so a stale refresh failure of the revoked row (its `mark_error` waits on the
  lock, then matches no `active` row) changes nothing.
- No repair branch touches the Profile document: the callback's compat-document update runs only
  when the flow replaces nothing (R6, §8 Q7).
- API-key create (`create_api_key_connection`): the same rule (`effective_to_replace`); in its
  one transaction the fresh row is created under a placeholder label, the marker CAS makes it
  effective, the replaced row is revoked, then the row takes the requested label
  (`take_over_effective`). A lost CAS is 409 `connection_conflict`; nothing is created.
- Rows touched by the callback lock in one ascending id order (the order delete uses); a lost
  callback revokes its own row so its label is freed.
- Delete holds the pair marker before any row lock: it advances the marker when it deletes the
  effective row, and otherwise locks it at the generation it observed
  (`PairAuthorityStore.hold`). A repair that moved the generation first makes the delete lose
  (409 `connection_conflict`). Without it, on PostgreSQL the repair's marker advance holds a
  key-share lock on its new row (the marker's foreign key), and a delete that locked rows first
  deadlocked with the callback, or, deleting the repair's own row, left the marker naming a
  revoked row.
- Callback (`routes/auth.py` `_record_oauth_connection_completion`, native branch), inside its
  existing transaction and in the D14 lock order: marker CAS from the observed generation to
  `effective_connection_id=<new row>` → `mark_revoked` of the old
  effective row (which also frees its `identity_sub` and label, both unique regardless of status,
  so a re-login of the same provider identity can activate) → `complete_pending` of the new row →
  blob. A lost CAS is the native superseded conflict (409 `connection_conflict`), and the
  transaction rolls back. The strategy cache entry of the old row is evicted.
- The two steps live in `core/provider_access/connection_native.py` beside
  `republish_effective_api_key`, using `PairAuthorityStore.advance` and the Connection store only:
  no Profile index, no `writer_floor`, so E4 keeps them unchanged.
- No route, OpenAPI or `reauth_url` change; E1 tests untouched.

### E2a — neutral types

- New `core/auth_types.py`: `AuthType`, `AuthMode`. New `core/credential_names.py`:
  `credential_name_for`, `profile_id_for` (the second keeps its name: it computes the stored
  locator of a migrated blob, which E5 still needs).
- Every importer of those four names moves to the new modules (51 source, up to 102 test files).
  `profile_models.py` keeps only `ProfileState`, `ProfileDefaults`, `Profile`, `ProfileIndex`.
- The import-boundary test gains a rule: outside the Profile-backed modules nothing imports
  `profile_models`. This is the only new test; every other test edit is an import line
  (mechanical, listed in the ledger, no manifest needed).

### E2b — dead defaults and chat shims

- Delete `routes/chat_profile_defaults.py`, `routes/chat_credentials.py` (after moving any live
  re-export to its real module), `core/provider_access/defaults.py`, `profile_defaults.py`,
  `RequestDefaults`, `ProviderAccess.defaults_for`, `CredentialTarget.defaults`, and the
  `should_apply_profile_default` hook with its plugin overrides.
- RED first proves each is dead: a test that the chat path builds no `RequestDefaults` and calls
  no `defaults_for` on a stored target, then the deletion.
- Tests that only pinned the deleted declarations retire; the list and the reason per file go
  into the manifest `OME-<E2b>.json` for owner approval before commit.

### E3 — route retirement

- One module `routes/legacy_profiles_retired.py` registers the 13 paths of spec §2.1 for every
  method they served, `include_in_schema=False`, and answers R1 from a static table
  (path → successor) without reading the body or touching storage. The old handlers, their
  request/response schemas and `_begin_legacy_pending` are deleted. The OAuth callbacks stay
  (their legacy-pending branch is E3b).
- Catalog delta (spec §8 Q6), in the design repository, before E3 merges: the retired
  operations and schemas are recorded as retired with historical provenance in the aigateway
  catalog (`protocol/http-api/openapi.yaml`, `protocol/provider-access` with
  `workflows/oauth-profile.yaml`, `datamodel/patch-profile-request`, `_coverage`), and the E1b
  repair rule is described on the Connection OAuth flow. Nothing is deleted to make a check pass; the catalog write follows a
  semantic review; catalog checks green.
- `apps/aigateway-ui/src/lib/aigateway/schema.d.ts` is regenerated with the pinned
  `openapi-typescript` from the E3 OpenAPI; the UI imports nothing that disappears (checked by
  `npm run typecheck`).
- Test map first, as in Stage C: the 54 files that hit a Profile HTTP path are classified into
  *retire* (they test the route itself), *adapt* (they use the route as setup; setup moves to the
  successor route or to store seeding, assertions unchanged) and *keep*. The map is shown to the
  owner and becomes the manifest `OME-<E3>.json` before any test is edited.

### E3b — dead core after the route retirement

Added 2026-10-19 (owner decision D3). After E3 the only producer of a `PendingAuthEntry` is the
native start `POST /v1/oauth/connections`, and the pending table is per process with a 600 s TTL,
so no Profile or facade flow survives a deploy. E3b deletes the core that only those flows and the
retired handlers reached. Nothing live changes.

- Callbacks (`routes/auth.py`): only the native path stays. The legacy-pending and migrated-facade
  branches move here from E4. `PendingAuthEntry.connection_id` becomes a required `str`;
  `profile_id`, `oauth_generation`, `pair_generation`, `compatibility_profile_name` and
  `pop_for_profile` are deleted.
- Deleted modules and symbols: `connection_oauth.py`, `connection_facade.py`; the Profile-backed
  and Connection-backed admin operations (`list`, `set_api_key`, `delete`), `summary_of`,
  `provider_credential_admin_for`, `legacy_view`, the `ProviderCredentialAdmin` port,
  `CredentialSummary`, `hold_observed`, `LEGACY_STATE_FOR_STATUS`, the legacy delete refusal
  renderers, `app.state.provider_credential_admin`; `ProfileIndexStore.begin_pending`,
  `authenticate_pending`, `mark_pending_error`, `update_metadata`; `ProfileIndex.oauth_generations`
  (the model ignores the extra key on read, so no migration).
- Kept for E4: the D14 mirror on the native callback, the D18 pair PUT/DELETE
  (`publish_api_key`, its sibling mirror, `addressed_by_a_live_connection`), Profile bootstrap,
  the `stamp_refreshed` PENDING branch, and the `ProfileBackedCredentialAdmin` base class (its
  collapse is E5).
- Tightenings: `_credential_strategy_for_credential_name` loses `auth_type`; `publish_api_key`
  requires `expected_live` and `claim_check`; the package no longer re-exports
  `ConnectionBackedCredentialAdmin`.
- Test map first, as in E3: retire, adapt or keep per test, new tests for every live branch whose
  only test retires; the map becomes the manifest `OME-<E3b>.json`.
- Not in E3b: purging expired entries of other states from the pending table. Its only caller was
  `pop_for_profile`, idle since E3; it is parked as an improvement idea.

### E4 — authority end

Precondition (owner, outside the repo): a census in every environment shows every pair with a
Profile document `migrated`; any other pair is backfilled with the existing tooling first. Met on
2026-10-20 (spec §7 Q3); the read-only census is re-run before each E4 landing is deployed to an
environment.

Amended 2026-10-20 (spec §9). A map of every Profile-index consumer after E3b showed that the
first version of this section ("an absent, `none` or `quarantined` marker fails closed") would
refuse every natively created pair, because a native write publishes a `none` marker and never
promotes it. The owner decisions:

- An absent or `none` marker is Connection-owned: the pair resolves through its Connections and
  nothing reads the index for it. Only `quarantined` fails closed, with 409
  `credential_pair_unresolved` (spec §9 Q8).
- A `migrated` pair resolves from the marker's effective Connection when it names one, otherwise
  through the label path over active rows (Q9).
- No runtime or admin path writes or removes a Profile document; documents left behind wait for
  E5 (Q10).
- Three PRs, each with its own leaf under `OME-1138` (Q11).

#### E4a — Connection-only readers

- `ConnectionBackedProviderAccess` stops subclassing `ProfileBackedProviderAccess`, which is
  deleted; the helpers they share (`_resolve_without_profile`, `_active_connection`,
  `_repair_api_key_only`, `targetless`, `connection_target`, `context_stamp`) move to the
  Connection side.
- Resolve reads no Profile document: absent or `none` → the label path, chatless or ambient, as
  today when no document matches; `quarantined` → coded refusal; `migrated` → the effective
  Connection when the marker names one (`migrated_target`, which loses its unused `document`
  parameter), otherwise the label path. A named selector is answered by the effective Connection
  only when it is that Connection's label (the document name the backfill gave it); any other
  name takes the label path, so a name is matched or refused, never served by another row.
  Production rejects every named selector (Stage D), so this keeps the port's contract only.
- Authorize and op 5 lose their Profile-target branches (`ProfileRefreshOwner`,
  `mark_profile_error_fresh`), which no target reaches once resolve builds none. The bare-Connection
  branch stays for label-path targets.
- Availability (op 6): the registry plus the migrated markers, each migrated provider from its
  effective Connection as today; every other provider `not_connected` (D17 unchanged).
- D18 classification reads no document: rows 8 and 10, the document half of row 3 and the
  row-11 shadow proof (`pair_shadow`) are deleted, row 11 is refused like row 4, and LIST renders
  no Profile. Rows 7 and 9 (an empty pair, one
  Connection) keep publishing `migrated`.
- Left for E4b: every Profile write and the reads that only feed it, Profile bootstrap and the
  `main.py` wiring.

#### E4b — no Profile writer; the index is offline-only

- Removed: the D14 mirror on the native callback and its `CredentialBlobMutationConflict` arms;
  the D18 PUT mirror (`api_key_mirror`, `_mirror_siblings`, `addressed_by_a_live_connection`) and
  the DELETE's document removal; the mirror in `republish_effective_api_key` and the document
  removal in `retire_effective`; the document check in `credential_has_other_owner`; Profile
  bootstrap (`bootstrap_under_the_floor`, `plugins/anthropic_provider/bootstrap.py`,
  `bootstrap_profiles`, the settings and error only it used); `ProfileIndexStore` wiring in
  `main.py` and `BackfillContext.from_app`.
- `writer_floor.py` keeps its live Connection-side fences (`claim_pair`, `claim_observed`,
  `hold_pair`, `mark_error_checked`, `observe_pair_of`); only the bootstrap leaves it. A set
  `AIGATEWAY_BOOTSTRAP_FROM_CLAUDE_CODE` logs a startup warning that the import is retired.
- Kept until E5: the `ProfileIndex` read models, `ProfileIndexStore` and the backfill tools,
  because E5's reference check reads the same documents. The import boundary allows
  `profile_index` only in the offline tools, and importing `aigateway.main` loads no
  `profile_index` (the package stops re-exporting the backfill modules).

#### E4c — neutral plugin hooks

- The surviving Profile-named hooks get neutral names: `allows_chatless_profile` →
  `allows_chatless_credential`, `profileless_auth_mode` → `credentialless_auth_mode`,
  `invalidate_profile_session` → `invalidate_credential_session`,
  `should_mark_profile_error_on_dispatch_status` → `should_mark_credential_error_on_dispatch_status`,
  and the `profile_name` parameters of `*_strategy_for` → `credential_name`.
- The hooks are looked up duck-typed with a silent default, so a missed rename would fail
  silently; a test asserts that no plugin or base class defines an old name.

A rollback to the pre-E4 build stays safe after every landing: E4 deletes no document or blob
(R5). The R1 rollback tool is not coherent for a pair changed after E4b, as spec §8 Q7 already
accepts for a native repair.

## 4. Tests

| Landing | Mandatory cases |
| --- | --- |
| E1 | every refusal kind (missing, pending, reauth at resolve, reauth at authorize, refresh) on both a migrated and an unmigrated pair carries a successor that the app's router resolves to a live route; no response body names `/profiles`; api-key Connection URL unchanged |
| E1b | errored (and revoked) effective OAuth row on a migrated pair → native start → callback → new row effective, old row revoked, chat 200 on the new row; same provider identity re-login activates; a usable effective row is not displaced; a newer start, a delete or a key write in between → 409 and nothing half-published; non-migrated pairs unchanged |
| E2a | full suite green with only import lines changed; boundary test fails when a non-Profile module imports `profile_models` |
| E2b | chat on a stored target builds no defaults; deleted names absent (`git grep` check in the ledger); full suite green |
| E3 | each of the 13 paths × each method it served → 410, R1 body, `Cache-Control: private, no-store`, with and without a body, with no storage read (spy) and no audit write; a malformed body still gets 410, not 422; OpenAPI has no `/profiles` path and none of the retired schemas; successor routes' OpenAPI fragments byte-identical before and after; callbacks unchanged |
| E3b | every deleted symbol has no production caller; the native start and callback, the D14 mirror, the D18 pair PUT/DELETE and chat keep their assertions; live branches whose only test retires gain one: `publish_api_key` conflict mapping, index-before-blob order, an unsupported auth mode, the sibling mirror, `addressed_by_a_live_connection` both ways, `stamp_refreshed` on a PENDING document, the D14 mirror's `last_refreshed_at`; PostgreSQL lane green for the touched concurrency suites |
| E4a | chat, model admission, availability and D18 LIST and classification read no Profile index (spy on the wired store); absent and `none` pairs resolve through their Connections, chatless or ambient, as before; `quarantined` → 409 `credential_pair_unresolved` with no index read; a `migrated` pair resolves from its effective reference with or without a document and falls back to the label path when the reference is empty; availability unchanged for migrated pairs and for providers without a document |
| E4b | the native callback, native re-key and delete, D18 PUT/DELETE and startup write and remove no Profile document; `main.py` wires no `ProfileIndexStore`; importing `aigateway.main` loads no `profile_index`; the import boundary allows it only in the offline tools; the backfill CLI still classifies, applies and rolls back from its own stores; PostgreSQL lane green for the concurrency suites listed in the D18 plan §4 |
| E4c | rename-only: full suite green with only names changed; no plugin or base class defines an old hook name |

## 5. Gates

From the repository root, per landing:

```sh
uv run .claude/scripts/run_gates.py aigateway --base origin/main
uv run .claude/scripts/run_gates.py aigateway-ui --base origin/main   # E1 copy, E3 schema
# from apps/aigateway, E4 (and E3 if a concurrency suite is touched):
AIGW_TEST_PG=1 uv run pytest -m needs_postgres -v
```

## 6. Deviations from the spec

- Spec §4 puts the plugin-hook rename in E2. This plan moves it to E4: several of those hooks are
  deleted at E4, and renaming them first would touch seven plugins twice.
- Spec §4 E2 is split into E2a (move) and E2b (delete) so the large mechanical diff and the
  deletion are reviewed apart.
- Spec §4 E4 says `ProfileIndexStore` is "no longer wired"; this plan keeps its offline reads
  until E5 (§3 E4), consistent with R5.

- Added 2026-10-15 (spec §8 Q5): E1b, because the test map for E3 showed the Profile facade is
  the only in-place re-authorisation of a migrated OAuth pair. E1's note that an OAuth re-auth
  "supersedes an errored Connection" holds for a pair the legacy Profile owns, not for a migrated
  pair, whose marker ignores a new native row.
- Order: E3 retires the routes before E4 ends Profile authority, whereas the OME-1138 rollout
  ends authority before cleaning up the legacy surface (spec §8). Accepted because every pair
  with a Profile document is `migrated`.
- E3 gains the catalog delta (spec §8 Q6), which this plan did not list.
- Added 2026-10-19: E3b, between E3 and E4. It takes the callbacks' legacy-pending and facade
  branches from E4, because E3 left them without a producer; E4 keeps the authority end.
- Added 2026-10-20 (spec §9): E4 lands as E4a, E4b and E4c. An absent or `none` marker resolves
  through its Connections instead of failing closed; E4 also removes the Profile-document writes
  this plan did not list (the D18 mirror and removal, the native re-key mirror and delete
  removal); `should_mark_profile_error_on_dispatch_status` joins the hook renames because it gates
  op 5 for migrated targets too.

The spec's §4 table was updated to match on approval.
