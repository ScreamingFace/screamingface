---
ticket: OME-1209
parent: OME-1138
status: accepted   # owner approval 2026-10-14; E1b and the E3 catalog delta amended 2026-10-15; each landing gets its own leaf issue under OME-1138 at PR-open
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
                                                      ├─▶ E3 route retirement ─▶ (census + backfill, owner) ─▶ E4 authority end
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
  (their legacy-pending branch is E4).
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

### E4 — authority end

Precondition (owner, outside the repo): a census in every environment shows every pair
`migrated`; any other pair is backfilled with the existing tooling first. The agent prepares the
read-only census command and its expected output; it does not run it.

- Chat and model admission resolve through the Connection authority only:
  `ConnectionBackedProviderAccess` stops subclassing the Profile-backed class; an absent, `none`
  or `quarantined` marker fails closed with a coded refusal instead of reading the index.
- Removed: the D14 dual write in the native OAuth callback, the legacy-pending branch of the
  callbacks, Profile bootstrap (`writer_floor.py`, `plugins/anthropic_provider/bootstrap.py`,
  `bootstrap_profiles`), the D18 none-pair bridge and the Profile read in `pair_admin*`,
  `ProfileIndexStore` wiring in `main.py`.
- Plugin hooks: Profile-only hooks are deleted with their callers; the surviving ones get
  neutral names (`allows_chatless_profile` → `allows_chatless_credential`,
  `profileless_auth_mode` → `credentialless_auth_mode`, `invalidate_profile_session` →
  `invalidate_credential_session`, `profile_name` parameters → `credential_name`).
- Kept until E5: the `ProfileIndex` read models, `ProfileIndexStore` reads and the backfill
  tools, because E5's reference check reads the same documents. They are reachable only from the
  offline tools, which the import boundary enforces.
- A rollback to the pre-E4 build stays safe: E4 deletes no document or blob (R5).

## 4. Tests

| Landing | Mandatory cases |
| --- | --- |
| E1 | every refusal kind (missing, pending, reauth at resolve, reauth at authorize, refresh) on both a migrated and an unmigrated pair carries a successor that the app's router resolves to a live route; no response body names `/profiles`; api-key Connection URL unchanged |
| E1b | errored (and revoked) effective OAuth row on a migrated pair → native start → callback → new row effective, old row revoked, chat 200 on the new row; same provider identity re-login activates; a usable effective row is not displaced; a newer start, a delete or a key write in between → 409 and nothing half-published; non-migrated pairs unchanged |
| E2a | full suite green with only import lines changed; boundary test fails when a non-Profile module imports `profile_models` |
| E2b | chat on a stored target builds no defaults; deleted names absent (`git grep` check in the ledger); full suite green |
| E3 | each of the 13 paths × each method it served → 410, R1 body, `Cache-Control: private, no-store`, with and without a body, with no storage read (spy) and no audit write; a malformed body still gets 410, not 422; OpenAPI has no `/profiles` path and none of the retired schemas; successor routes' OpenAPI fragments byte-identical before and after; callbacks unchanged |
| E4 | with every pair `migrated`: chat, D18 and native OAuth construct no `ProfileIndexStore` (spy); absent/`none`/`quarantined` marker → coded refusal, no index read; the native callback writes no Profile document; startup writes no Profile; PostgreSQL lane green for the concurrency suites listed in the D18 plan §4 |

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

The spec's §4 table was updated to match on approval.
