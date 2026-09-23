---
ticket: OME-1208
stack: aigateway
status: in_progress   # S1 + S2'a + S2'b1 + S2'b2 + S2'b3 + S2'b4 + S2'c + S4 DONE (commit 2c39a949, PR #1029); R1 review fixes DONE uncommitted, gates green 2026-09-23
started: 2026-09-22
finished:
---

# OME-1208 — Move the provider-access backing from legacy Profiles toward Connections (Stage B)

## Intent

Stage B of `OME-1138` (plan units S1, S2', S4 under the D11 conservative path). Today a hosted
credential is `alice + anthropic -> Profile(default) -> encrypted credential blob`; after this
unit the provider-access boundary is backed by a canonical Connection for every safely migrated
`(account, provider)` pair — `alice + anthropic -> Connection -> encrypted credential blob` —
with no secret re-entry and no external behaviour change. Settled for this unit (owner,
recorded on the issue and on `OME-1138` on 2026-09-22): one deterministic effective credential
per pair (D11, no multi-account expansion); Connection becomes the source of truth after a safe
migration and the legacy Profile APIs become compatibility facades over that backing, never a
second independent writer; ambiguous Profile/Connection collisions are quarantined and reported
(D3), never resolved by last-write-wins; no destructive cleanup — Profile storage and rollback
data stay (expand-only, rehearsed R1 rollback, D5); saved Profile defaults are not migrated as a
permanent feature (D2) and no permanent Connection defaults or presets are created.

Spec: `docs/spec/2026-09-09-OME-1138-converge-connections.md` §3.8, §6.1, §7, §8 (D1, D3, D5,
D11, D14, D16), §11 "Backing (B)". Plan: `docs/plan/2026-09-09-OME-1138-converge-connections.md`
§2 S1/S2'/S4, §3 B, §4 G4. Design catalog: `component/provider-access` v3,
`protocol/provider-credential-admin` v2, `protocol/provider-access-availability` v1,
`component/credential-store` v4 (design `main` at the PR #22 merge).

## Preflight (2026-09-22)

- Source `origin/main` = `99e2d4b2`; it includes Stage A4 (`OME-1244` PR #1006 `2da45896`,
  `OME-1245` PR #1007 `54fa8673`). Branch
  `OME-1208-aigateway-migrate-provider-access-backing-from-profiles` created from it in its own
  worktree; nothing staged or committed.
- Linear `OME-1208`: High, parent `OME-1138`, blocked by `OME-1207` and `OME-1210` (both Done);
  moved Backlog → In Progress at ledger creation; labels completed to
  `aigateway` + `agentic` + `autonomous` (the actor and who-acts leaves are mandatory per the
  task-board card and match the sibling units `OME-1244`/`OME-1245`). D11 decision text read
  from the issue comments (2026-09-22 13:02Z).
- **Metamodel gate against design `main` (PR #22 merge, `a2468ee`):**

  | Required by the unit | Catalog state | Verdict |
  | --- | --- | --- |
  | `Connection` final noun; `provider access` boundary family; `legacy Profile` compatibility backing | `protocol/provider-access-availability` "Naming", `protocol/provider-credential-admin` "Boundary", `component/provider-access` "Current Backing" | covered |
  | One effective credential per `(account, provider)` | absent (D11 exists only in Linear) | **missing** |
  | Profile APIs as facades, not independent writers | admin card: management routes are shells, but OAuth start/callback/refresh, bootstrap and `/v1/oauth/connections*` "stay direct owners of their stores"; Stage B "once the backing model and the dual OAuth write owner are decided" | **missing / D14 open** |
  | Connection-backed source of truth after migration for non-conflicting pairs | component card: "No Connection-backed store exists behind either Protocol … nothing in this card describes it as live" | **missing** |
  | Conflict / quarantine / report for ambiguous collisions | absent | **missing** |
  | Rollback / expand-contract: no Profile storage deletion in Stage B | absent (only Stage E deletions listed) | **missing** |
  | Later-stage boundaries (no defaults cutover, no selector sunset, no retirement) | availability card "Later Stages", admin card "Backing and Later Stages" | covered for D/E; Stage C boundary not tied to Stage B |

  Verdict: **not covered**. Per the unit's rule the design repository is updated first and the
  work stops for review/merge before application code.
- **D14 (dual OAuth write owner) — current code, read on the branch:** a Profile-flow callback
  (`routes/auth.py:_complete_oauth_for_app`) publishes the Profile row and its blob in one
  transaction and then `_record_oauth_connection_completion` also activates a shadow
  `OAuthConnection` with its own blob for every adapter that extracts an identity; a
  Connection-flow callback activates the Connection and, through `_mark_profile_authenticated`
  without `require_pending`, also flips a same-named Profile when one exists. Spec §8 still lists
  D14 as open (options a/b/c). The owner's settled decision #2 for this unit (facades, not a
  second independent writer) and its write-ownership rule ("all writes for an owned pair go
  through one backing authority") resolve the target as a per-pair authority: the design
  revision records it; the formal D14 register row in the spec is proposed to the owner, not
  edited unilaterally.
- Not decided here, presented to the owner with the design draft: whether Stage B may fold
  Connection-only pairs into the availability listing (the D17 flagged change) — the
  conservative path keeps the window listing unchanged.

## Design revision (drafted 2026-09-22; PR #23 opened the same day)

Authored in an isolated worktree of the design repository on branch
`OME-1208-provider-access-backing-transition` from design `origin/main` `a2468ee` (the shared
design checkout, which holds the owner's uncommitted edits on another branch, was not touched):

- `solutions/screamingface/product/aigateway/component/provider-access/index.md` v3 → v4:
  new section "Stage B Target — Connection-Backed Authority" (what changes / what does not; the
  pair authority marker `provider_credential_slots` with `none|migrated|quarantined`; reads
  without re-entry via the stored locator and the derived state mapping; the classification
  table incl. "Connection only, several active Connections → not migrated (D12 open)"; dry-run /
  apply / reporting rules; write ownership = D14 as resolved for Stage B; D16 presented open with
  option (a) recommended; expand-never-contract and the R1 rollback rehearsal; later-stage
  boundaries; obligations before any pair switches); "Current Backing" now points at it; spec
  and plan references added to Sources.
- `solutions/screamingface/product/aigateway/protocol/provider-credential-admin/index.md`
  v2 → v3: the Stage B bullet now names the accepted target and the write-owner rule.
- `solutions/screamingface/protocol/provider-access-availability/index.md` v1 → v2: op 6 reads
  each pair's authority; rows and status family unchanged; D17 flagged changes stay flagged.
- `solutions/README.md`: changelog paragraph for the Stage B preparation.

Validator (`@bershadsky/metaframework@0.5.1 check --dir ./solutions --since origin/main`, run in
the design worktree): baseline on `a2468ee` 0 errors / 3 warnings (pre-existing
`W_ACTOR_ORPHAN` ×2, `W_PROTO_PARTICIPANT_UNLINKED` token-delegation); after the edits
0 errors / the same 3 warnings, 113 entities, "3 entities changed, each either bumped its
version or changed only its status". Review states left as they were (owner sets them at
merge). Nothing staged, committed or pushed in either repository.

Owner decisions (2026-09-22, on the goal and mirrored on the issue):

1. Design PR authorized: commit, push and open it; title
   `docs(catalog): describe the Stage B backing transition behind provider access`, body
   `Refs: OME-1208`. Merge remains the owner's step.
2. **D14 decided** — per-pair authority marker: migrated pair → Connection-backed authority owns
   all writes including OAuth callback publication; unmigrated/quarantined pair → legacy Profile
   behaviour unchanged, existing shadow write included; no two independent write owners for the
   same owned pair. D11/D14 may be marked decided in the spec register in the app PR after the
   design PR merges.
3. **D16 decided (a)** — for a migrated pair the legacy Profile index entry may remain as a
   defaults-only compatibility document during the transition; credential authority moves to
   the Connection; the defaults cutover stays Stage C.
4. **D12 (Stage B rule)** — Connection-only pairs with several active Connections stay
   unmigrated in Stage B.
5. Design PR scope: Stage B target only; A4 sections not refreshed (nothing contradicted and the
   validator passed without it).

The cards were updated to record 2–4 as decided before the PR was opened; validator re-run
0 errors / 3 baseline warnings / 3 entities bumped. After the design merge: app implementation
under OME-1208 with sdlc-python + tortoise-dev, RED first; no Stage C/D/E.

## App implementation start (2026-09-22)

- Design gate closed: PR #23 merged into the design repository's `main` (merge commit
  `12d1bbe3`, Stage B Target section present on `origin/main`). Source `origin/main` is still
  `99e2d4b2`; the unit branch needs no rebase. `uv sync` done in the unit worktree
  (Tortoise 1.1.8, Python 3.13.11); `pytest --co -m "not live"` collects 4709 tests.
- Linear `OME-1208` moved to In Progress with a start comment (decisions restated; no local paths).
- Order: S1 (slot store + locator-authoritative strategy factory, RED first) → S2' → S4. Each
  slice ships its migration in the same iteration (S1 rule). Owner decisions carried into code:
  D14 per-pair authority marker; D16 option (a); multi-Connection pairs stay unmigrated.

## Planned changes

Design (repository `screamingface-design`, branch `OME-1208-provider-access-backing-transition`
from design `origin/main` `a2468ee`, own worktree; PR after owner authorization):

- `solutions/screamingface/product/aigateway/component/provider-access/index.md` v3 → v4: new
  section "Stage B Target — Connection-Backed Authority" (pair authority marker, one effective
  credential per pair, locator-authoritative reads without re-entry, classification and
  quarantine, write ownership, expand-only rollback, later-stage boundaries, test obligations);
  "Current Backing" cross-reference.
- `solutions/screamingface/product/aigateway/protocol/provider-credential-admin/index.md`
  v2 → v3: Stage B bullet points at the accepted target and names the write-owner rule.
- `solutions/screamingface/protocol/provider-access-availability/index.md` v1 → v2: op 6 reads
  each pair's authority in Stage B; rows and status family unchanged; flagged changes stay
  flagged.
- Catalog bookkeeping the validator or the contract map requires for a version bump.

Application (only after the design revision is merged; separate authorization):

- S1 — `provider_credential_slots` slot store (model-per-file with abstract `Base*`, Tortoise
  1.1.8 single PK + `unique_together`, migration `0012_*` in the same iteration) and a
  locator-authoritative credential-strategy factory.
- S2' — pair-marker authority routing; Connection-backed `ProviderAccess` and
  `ProviderCredentialAdmin` implementations behind the existing Protocols; OAuth callback and
  API-key publication through the pair's authority; Profile routes stay shells.
- S4 — `python -m aigateway.migrate_profiles --dry-run|--apply --account|--all`: secret-aware
  classification before any write, journal, quarantine, idempotent/resumable apply, R1 rollback
  rehearsal; SQLite and PostgreSQL.

### S1 — planned files (2026-09-22, before RED)

Design inputs: card v4 "Stage B Target" (pair authority marker; reads without re-entry), D1
(single PK + `unique_together`, Tortoise 1.1.8 has no partial unique index), D14, D16 (a), D19
(no leading-underscore module names), tortoise-dev (model-per-file, abstract `Base*`, `Meta`
first, built-in migrations). Verified installed facts: every plugin's `credential_service_for`
is `aigateway:<credential-provider>:<credential-name>` and the core's
`credential_locator_for` already assumes it, so a locator is invertible; `credential_key_for`
and `credential_name_for` share the shape `<account>:<x>`, so
`credential_locator_for(cp, account, profile_name)` IS the Profile blob's address; Tortoise's
SQLite client sets `PRAGMA foreign_keys=ON`; `QuerySet.update` does not touch `auto_now`.

- `src/aigateway/core/provider_access/models/__init__.py` — re-exports + `__models__`.
- `src/aigateway/core/provider_access/models/provider_credential_slot.py` —
  `BaseProviderCredentialSlot` (abstract: id, provider, generation, migration_state,
  migration_note, updated_at) + `ProviderCredentialSlot` (table `provider_credential_slots`,
  `unique_together=(("account_id","provider"),)`, FK `account` CASCADE, FK
  `effective_connection` NULL SET_NULL). No defaults, no secret.
- `src/aigateway/db.py` — register `aigateway.core.provider_access.models`.
- `src/aigateway/migrations/0012_provider_credential_slots.py` — `CreateModel`, generated with
  `tortoise makemigrations -n provider_credential_slots` then documented (S1 rule: schema and
  migration in the same iteration).
- `src/aigateway/core/provider_access/pair_authority.py` — `PairAuthority` (frozen view),
  `PairAuthorityConflict`, `PairAuthorityStore.read/list/advance`; an absent row reads as
  `none`/generation 0; `advance` is a compare-and-set on the generation (create when the
  expected generation is 0, `UPDATE … WHERE generation = expected` otherwise); an effective
  Connection is only meaningful for `migrated` (a `migrated` row with no effective Connection is
  the post-delete state and stays Connection-owned — never falls back to the legacy Profile).
- `src/aigateway/core/provider_access/connection_locator.py` —
  `credential_name_for_connection` (locator-authoritative: a well-formed locator names the blob;
  a malformed one falls back to today's `credential_key_for`, which addresses a blob unique to
  that Connection, so no foreign secret can be served) and `credential_strategy_for_connection`
  (the factory S2' uses for reads AND writes of a migrated pair).
- Tests (new files only): `tests/unit/core/provider_access/test_pair_authority_store.py`,
  `tests/unit/core/provider_access/test_connection_locator.py`,
  `tests/unit/test_migration_0012_provider_credential_slots.py`; PostgreSQL migration coverage
  through the existing `tests/integration/test_tortoise_migration_smoke.py` run locally with
  `AIGW_TEST_PG=1` (Docker 29.6.1 reachable).

### S1 — RED → GREEN evidence and findings (2026-09-22)

- RED: the two provider-access test modules failed at collection (`ModuleNotFoundError` for
  `provider_access.models`, `pair_authority`, `connection_locator`); the 0012 suite failed 6/8
  (no migration; autodetector proposed `Create model ProviderCredentialSlot`).
- GREEN: 34/34 across the three new files after the model, registration, store, locator module
  and migration 0012 landed. One test-side correction to a NEW test (never a prior one): the
  factory tests need the `authenticated_client` fixture, as the contract harness does.
- Migration authoring: `tortoise makemigrations -n provider_credential_slots models` generated
  the `CreateModel`; edited to `bases=["Model"]` (every earlier `CreateModel` here) and to DROP a
  second proposed operation, see the finding below. Generated foreign-key spelling
  (`source_field`/`to_field`/`db_constraint`) kept so the projected state equals the model.
- **Finding (pre-existing, not fixed here):** the autodetector proposes
  `Alter field account on OAuthConnection` on `main` WITHOUT this unit's model — drift between
  migration 0002's foreign-key spelling and Tortoise 1.1.8's projected state. Not applied in 0012:
  unrelated to the marker, and an `AlterField` on SQLite rebuilds `oauth_connections`, dropping
  its standalone indexes (the 0009–0011 defect). Needs its own decision/ticket; the 0012 drift
  test filters on the marker only, as the 0009/0011 drift tests filter on their own models.

## Test plan

RED before GREEN, prior tests untouched (append-only):

- Provider-access contract suite (and the admin contract suite) green against the Profile-backed
  implementation and the Connection-backed implementation / transition harness, consumers
  unedited.
- Profile-only pair migrates to a Connection without re-entry; Connection-only pair stays usable
  and gets no Profile; Profile + Connection proven same or mapped → Connection chosen after the
  mapping is recorded; ambiguous pair → quarantined and reported, legacy authority kept, no
  last-write-wins.
- Pending / error / missing-blob / corrupt Profile never promoted to active; revoked / deleted /
  tombstoned state never resurrected.
- OAuth stale callback and delete-wins fencing survive on the new backing; API-key replace and
  delete survive; one effective credential per pair under create/rotate/revoke races.
- Compatibility shells: HTTP bodies, status codes and OpenAPI unchanged.
- Legacy Profile storage present and readable after apply (rollback R1 rehearsed).
- SQLite and PostgreSQL migration/coexistence lanes; dry-run writes nothing and logs no secret,
  default, token, revealing name or ciphertext; apply idempotent and crash/retry safe.

## Acceptance

- Design revision merged on design `main` covering all nine gate items (owner review).
- Contract suites pass against the Connection-backed backing without consumer rewrites.
- Existing Profile-backed credentials remain usable during the transition; no re-entry.
- Collision, rollback, stale callback, delete-wins and replacement behaviour covered on SQLite
  and PostgreSQL; destructive cleanup remains blocked.
- AIGateway gates green: `uv run ruff check .`, `uv run ruff format --check`, `uv run pyright`,
  `uv run python scripts/check_no_enterprise.py`, `uv run pytest -m "not live"`, plus the
  focused PostgreSQL/migration lane (or the recorded reason CI must cover it).

### S2'a — planned files (2026-09-22, before RED): pair-authority routing + Connection-backed read path

**Intent.** Behind the unchanged `ProviderAccess` port, a pair whose marker is `migrated` is served
from its effective Connection (D14); `none`/`quarantined` pairs keep today's Profile-backed path
byte for byte. Reads go through the stored `credential_locator`, so a migrated Connection serves the
Profile's blob with no secret re-entry. Writes (admin ops 7–9, OAuth callback, facades) are S2'b.

**Design decisions (recorded for review):**
- D-S2a-1 `ConnectionBackedProviderAccess` SUBCLASSES `ProfileBackedProviderAccess` and overrides
  `resolve`/`authorize`/`record_dispatch_failure`/`availability`; op 1 (`defaults_for`) and op 3 are
  inherited untouched (D16 (a): defaults stay in the legacy index until Stage C). WHY a subclass:
  prior tests pin `isinstance(app.state.provider_access, ProfileBackedProviderAccess)` and patch
  `ProfileBackedProviderAccess.resolve/authorize` as seams (shims, accounting, openrouter policy,
  model-execution tests); `super()` keeps every seam live for unmarked pairs and no prior test moves.
- D-S2a-2 For a migrated pair the selector still names the legacy compatibility document (the pair's
  Profile row): document found → the effective Connection is the target (status active → target,
  pending → `TargetPending`, error → `TargetReauthRequired` with the BARE legacy URL, revoked or no
  effective Connection → `TargetMissing`, never the document's own state); document absent → exactly
  today's `_resolve_without_profile` path. The target's `credential_name` is the locator-derived blob
  address, `reauth_url` the legacy facade URL, `defaults` the document's, `context_stamp` the
  Connection's (`conn:…`) — published contract ids re-key once at migration (flagged).
- D-S2a-3 `connection_target` becomes locator-authoritative for EVERY Connection (a `plugin` keyword
  is added; UUID locators keep today's `credential_key_for` address — S1 test). WHY: without it a
  wrong selector on a migrated pair would fall to the legacy Connection fallback with the UUID
  address, find no blob and mark the effective Connection errored (poisoning by a bad header).
- D-S2a-4 Ops 4–5 for a migrated target follow the Profile rules on the Connection row: a MISSING
  credential evicts only (recoverable, marks nothing); a REJECTED credential and a dispatch failure
  mark the Connection errored, evict, invalidate the session; a dispatch failure REWRITES the detail
  with the legacy `reauth_url` (facade HTTP unchanged). A successful authorize touches the
  Connection's `last_used_at`.
- D-S2a-5 Op 6 reads the pair authority: a migrated provider's status comes from its effective
  Connection (active→connected, pending→pending, error→error, none/revoked→not_connected), the
  legacy precedence stays for every other provider. An unreadable marker store propagates its
  error — never a silent fall-back to the legacy credential of a migrated pair.

**Planned files.** NEW `src/aigateway/core/provider_access/connection_authority.py` (migrated-pair
target/authorize/failure/availability helpers + `MigratedBacking`), NEW
`src/aigateway/core/provider_access/connection_backed.py` (`ConnectionBackedProviderAccess`);
MODIFY `profile_backed.py` (`connection_target(..., *, plugin)` reads the locator; two call sites),
`core/provider_access/__init__.py` (export the new class + `PairAuthority*`), `main.py` (wire the
subclass into `app.state.provider_access`). Tests NEW under `tests/unit/core/provider_access/`:
`connection_backed_harness.py` (`ConnectionBackedHarness(ProfileBackedHarness)`: `seed_profile`
seeds a MIGRATED pair — document + Connection with a Profile-addressed locator + blob + marker;
`profile_state` reads the authority), `test_connection_backed_resolve_contract.py` and
`test_connection_backed_authorize_contract.py` (re-run the existing contract tests by explicit
import over the new harness; the one Profile-shaped stamp assertion gets a Connection twin, the
fake-only test is not re-imported), `test_connection_backed_routing.py` (routing, marker read per
call, quarantine → legacy, no re-entry, status mapping, wrong-selector locator safety, document
never consulted for state, availability overlay, unreadable marker propagates).

**Test plan / acceptance.** RED: the new suites fail on import of the new modules; GREEN: all new
tests + the full `-m "not live"` suite; `run_gates.py aigateway --base 99e2d4b2` green; no prior
test modified (append-only check).

### S2'b1 — planned files (2026-09-22, before RED): Connection-backed credential admin (ops 7–9)

**Intent.** For a `migrated` pair, every credential WRITE the legacy Profile routes perform (op 8
`set_api_key`, op 9 `delete`) goes through one Connection-backed authority, and op 7 `list`
renders the pair from its effective Connection — D14 "Connection owns all writes" for the admin
boundary. `none`/`quarantined` pairs keep the Profile-backed body byte for byte. The OAuth
callback, `start_oauth` and the read facades (`profile_status`, `patch_profile`, `refresh_profile`)
are the next slice (S2'b2); Connection-native routes becoming slot-aware is S2'b2 as well.

**Decisions.**
- **D-S2b-1 subclass:** `ConnectionBackedCredentialAdmin(ProfileBackedCredentialAdmin)` — the
  admin contract pins `isinstance(admin, ProfileBackedCredentialAdmin)` and patches its seams;
  the subclass reads the marker once per op and defers to `super()` for non-migrated pairs.
- **D-S2b-2 compat document = faithful mirror (D16 (a), D5):** on every authority write the legacy
  document is rewritten as today's Profile would be (AUTHENTICATED, `auth_type`, masked
  `account_label`, `scopes=[]`, `last_refreshed_at`, defaults replaced wholesale / kept when
  omitted) so an R1 rollback (marker reset, blobs kept) serves the same credential from the legacy
  path. While migrated the document is never READ as authority — state comes from the Connection.
  An absent document is created (the facade's "PUT creates" contract). A document whose name is
  not the locator's name is an alias: rollback-fragile (legacy would read `<account>:<alias>`),
  so S4's R1 rehearsal must report alias documents. Recorded, not solved here.
- **D-S2b-3 one lock/CAS order:** marker advance (the generation fence) → index row CAS →
  Connection row → blob, inside ONE `in_transaction()`. `PairAuthorityConflict` →
  `WriteConflict("superseded", subject="connection")` (409 `connection_conflict` at the edge);
  the index conflicts keep today's `subject="profile"` mapping. A brand-new Connection row is
  inserted BEFORE the marker names it (FK), which is safe: nobody else can contend a row whose id
  was minted in this transaction.
- **D-S2b-4 set_api_key on the effective Connection:** `set_auth_type("api_key")`, then
  `reactivate` (active/error) or `complete_pending` (pending) — the fenced UPDATEs, so a
  concurrent revoke wins (0 rows → conflict). The label is kept (Connection-native rule) except an
  `error:<id>` placeholder left by `mark_error`, which becomes `api-key-<id>` (unique by
  construction). No effective / revoked effective → `create_api_key` with the requested name's
  Profile address as `credential_locator` (same blob placement as legacy → rollback-safe) and the
  `api-key-<id>` label; the marker then names it. `OAuthConnectionStore.create_api_key` gains an
  optional `credential_locator` keyword (additive; default unchanged).
- **D-S2b-5 delete:** marker advance with `effective_connection_id=None` (still `migrated`, the
  S1 post-delete state) → document removed → `mark_revoked(effective)` → blob at the locator
  deleted; no effective → document removal + marker advance only; document absent →
  `TargetMissing`. The marker advance in delete is what serializes a racing set_api_key.
- **D-S2b-6 list:** every document of a migrated provider renders from the effective Connection
  (active→authenticated, pending→pending, error→error; `auth_type` the Connection's); a pair
  with no effective / a revoked effective lists nothing (it is `not_connected`); other providers
  are the legacy rows; the provider filter is honoured.

**Planned files.** NEW `apps/aigateway/src/aigateway/core/provider_access/connection_admin.py`
(`ConnectionBackedCredentialAdmin`, `legacy_view`, the migrated op bodies). MODIFIED
`core/provider_access/__init__.py` (export), `main.py` (`app.state.provider_credential_admin`),
`core/oauth/store.py` (additive `credential_locator` keyword on `create_api_key`). NEW tests
`tests/unit/core/provider_access/test_connection_backed_admin_contract.py` (re-runs the admin
contract over a migrated seam; the list test is re-expressed) and
`tests/unit/core/provider_access/test_connection_backed_admin.py` (routing, write ownership,
fence, rollback availability). No schema change (S1 rule n/a).

**Test plan / acceptance.** RED: the new modules fail collection on the missing export; GREEN:
all new tests + full `-m "not live"` suite; `run_gates.py aigateway --base 99e2d4b2` green; no
prior test modified.

### S2'b2 — planned files (2026-09-22, before RED): the Profile-facade OAuth flow of a migrated pair

- **Intent:** for a `migrated` pair the Profile-facade OAuth flow (`POST /v1/auth/{provider}/profiles`
  → callback / `exchange-code`) publishes the pair's ONE effective Connection and the blob its
  locator names — never the Profile index as authority, never a shadow Connection at a UUID
  address (card §Stage B, D14: "OAuth callback publication included"; the dual write ends for
  owned pairs). `none`/`quarantined` pairs keep today's body, byte for byte, after one marker read.
- **Design (D-S2b2-1..6):**
  - **D-S2b2-1 placement:** new core module `core/provider_access/connection_oauth.py`
    (`begin_oauth` → `MigratedFlow | None`, `complete_oauth` → credential name, `fail_oauth`);
    `routes/auth.py` gains only delegation branches keyed on a new optional
    `PendingAuthEntry.pair_generation` (the legacy `begin_pending` lines move unchanged into a
    helper so the route stays one `try` around "publish this flow"). `routes/auth.py` is already
    far over 450 lines (pre-existing); the responsibility lands in the new module, not there.
  - **D-S2b2-2 the fence is the marker generation:** start advances the marker in the same
    transaction as the flow row and the mirror document; the pending entry carries that
    generation; the callback CAS-advances from it. A newer start, a delete or an API-key write in
    between makes the CAS fail → the LEGACY stale body `409 profile_auth_conflict
    {provider, profile}` (unchanged on the wire). The failure path marks anything only while the
    flow still owns that generation.
  - **D-S2b2-3 the flow row:** effective `active` → re-auth IN PLACE (`complete_active`, label
    kept, identity set, `auth_type` flipped to `oauth`); `pending` → `complete_pending`;
    `error`/`revoked`/absent → a NEW pending row labelled with the requested name, locator =
    that name's Profile address (`create_pending` gains the same additive `credential_locator`
    keyword `create_api_key` got in S2'b1), named effective at start; error/revoked rows are
    never revived (their placeholder labels stay). Visible-window difference, flagged: while an
    ACTIVE row re-authenticates the pair stays usable and reads `authenticated` until the
    callback swaps the blob (the Connection-native H-1 semantics); legacy showed `pending` and
    refused. The alternative (a second row) is excluded by the `(account, provider, label)`
    uniqueness and by "one effective credential".
  - **D-S2b2-4 no shadow, no UUID blob:** `_record_oauth_connection_completion` is skipped for a
    migrated flow; exactly one Connection row and one blob (at the locator) exist afterwards.
  - **D-S2b2-5 mirror (D-S2b-2 applied):** start → PENDING mirror when a pending row is created
    (scopes, defaults when supplied, `auth_type` kept), scopes/defaults only when re-auth is in
    place; completion → AUTHENTICATED, `oauth`, `last_refreshed_at`, plugin account label; a
    pending-row failure → ERROR mirror. The card's sentence "the legacy Profile's credential
    state is not written again" is deliberately NOT followed literally — the mirror is written BY
    the authority, in its transaction, so it is not a second writer, and it is what keeps D5's
    R1 rollback (marker reset, blobs kept) coherent: a document whose `auth_type`/state disagrees
    with its blob would break the rolled-back legacy path. Flagged for the owner in the report.
  - **D-S2b2-6 failures:** exchange failure with a pending flow row → `mark_pending_error`
    (row fence) + marker advance (marker fence) + ERROR mirror; with an in-place active row →
    nothing is marked (the old credential stays valid; legacy marked ERROR). Store failure at
    completion → `CredentialStoreUnavailable` → today's `503 credential_store_unavailable`,
    everything rolled back (row, document, marker), then the failure marking above.
- **Planned files:** NEW `apps/aigateway/src/aigateway/core/provider_access/connection_oauth.py`
  (≤300 lines); MODIFIED `core/pending_auth.py` (+`pair_generation: int | None = None`),
  `core/oauth/store.py` (`create_pending(..., credential_locator=None)`), `routes/auth.py`
  (`start_oauth` delegation + `_begin_legacy_pending` extraction; `_complete_oauth_for_app`
  migrated branch; `_mark_oauth_completion_error` migrated branch; `_invalidate_credential`
  taking a credential name), `core/provider_access/__init__.py` (exports). Tests NEW
  `tests/unit/core/provider_access/connection_backed_oauth_probes.py` (token factories, start/
  callback/status helpers), `test_connection_backed_oauth_flow.py` (happy paths),
  `test_connection_backed_oauth_fences.py` (fences + failures). No schema change (S1 n/a).
- **Test plan (RED first):** (1) migrated active pair: start keeps the SAME effective row active,
  callback republishes it — same id, `oauth`, identity/last_refreshed_at set, blob at the Profile
  address carries the new token, NO blob at the UUID address, exactly one Connection row for the
  provider, marker +2 (start, callback), document AUTHENTICATED/oauth, status route
  `authenticated`, evicted/invalidated under the locator name; (2) migrated pair with no effective
  row (post-delete): start creates a pending row named effective (+ PENDING mirror, status
  `pending`, resolve → `TargetPending`), callback activates it with label = name; (3) start with
  `defaults` on a migrated pair replaces the document's defaults (D16 (a)) and touches no row;
  (4) a Connection-only migrated pair (UUID locator, no document) re-authenticates in place with
  the blob at the UUID address and a mirror document created; (5) stale callback: a concurrent
  marker advance between start and callback → `409 profile_auth_conflict`, row/blob/document
  untouched; (6) delete-wins: DELETE between start and callback → 409, row stays revoked, no
  blob, no document resurrected, marker effective None; (7) API-key-wins: PUT api-key between →
  409, api_key blob and row stand; (8) exchange failure on a fresh flow → 500 sanitized, row
  `error`, document ERROR, no blob, marker advanced once more; (9) exchange failure during
  in-place re-auth → 500, row still active, blob unchanged, document AUTHENTICATED; (10) store
  failure at completion → 503 `credential_store_unavailable`, row/document/marker rolled back, no
  token in response or log; (11) unmigrated pair: prior flow unchanged — legacy shadow
  Connection still created, marker never written, `pair_generation is None`; (12) quarantined
  pair: legacy body, marker untouched. Prior suites (`test_auth_routes.py`,
  `test_profile_oauth_flow_ownership.py`, `test_chat_x_profile.py`) stay green unmodified.
- **Acceptance:** all of the above green; full `-m "not live"` suite green; gates green;
  `routes/auth.py` diff is delegation only; no secret in any new log line or exception text.

### S2'b3 — planned files (2026-09-22, before RED): the Profile status/patch/refresh facades of a migrated pair

- **Intent:** the remaining Profile routes that still read or write the index directly —
  `GET …/profiles/{name}/status`, `PATCH …/profiles/{name}`, `PATCH /v1/admin/accounts/{id}/profiles/{provider}/{name}`,
  `POST …/profiles/{name}/refresh` — become facades: for a `migrated` pair they RENDER state and
  `auth_type` from the effective Connection (locator-authoritative reads; agreeing with op 7's
  list and with op 5's error marking) and the refresh runs THROUGH the Connection (card: "the
  Connection backing owns … refresh, error marking"). Metadata (`defaults`, `account_label`) stays
  on the compatibility document (D16 (a)). `none`/`quarantined` pairs keep today's bodies, byte
  for byte, after one marker read. Item 0 first: prove the chat path over a migrated pair already
  carries the credential and marks the Connection (the `backing_rows` finding).
- **Finding closed by evidence (item 0):** `routes/chat.py` resolves a `CredentialTarget` through
  the port (`_resolve_credential_target`) and hands THAT target to `record_dispatch_failure`; the
  lossy `(profile, connection)` triple lives only in the A1 shim `routes/chat_credentials.py`,
  which no route imports any more (its own suite is the sole importer, kept append-only). So
  `backing_rows(MigratedBacking) == (None, None)` cannot reach production; characterisation
  tests pin the route behaviour instead of changing the shim (Stage E retires it).
- **Design (D-S2b3-1..5):**
  - **D-S2b3-1 placement:** new core module `core/provider_access/connection_facade.py` —
    `FacadeTarget(document, connection | None)` with `.view` (legacy document for a legacy pair;
    `legacy_view(document, connection)` for a migrated one), `facade_target(app, *, account_id,
    provider, name) → FacadeTarget | None`, `patch_facade(app, target, *, defaults, account_label)
    → Profile`, `refresh_facade(app, plugin, target, *, provider, account_id, name) → Profile`
    (migrated only; the legacy refresh body stays in the route). The routes keep their refusal
    rendering (`404 profile_not_found`, `409 profile_conflict`) and gain delegation only.
  - **D-S2b3-2 reads are Connection-authoritative:** a migrated pair renders from its effective
    Connection (`LEGACY_STATE_FOR_STATUS`, `auth_type_of(None, connection)`); a migrated pair
    with no document, or whose effective Connection is absent/revoked, is `404 profile_not_found`
    — exactly what op 7's list omits, so status/patch/list agree. The mirror document's own
    `state` is never load-bearing for a read.
  - **D-S2b3-3 patch is metadata-only:** `update_metadata` on the compat document, no marker
    advance (a metadata edit is not authority-changing), Connection row untouched; the response
    renders `view`. Admin PATCH identical through `AdminProfileOut.model_validate(view)`.
  - **D-S2b3-4 refresh through the Connection:** an `active` effective row refreshes with the
    SHARED cached strategy under the locator name (`credential_strategy_for_connection`; the
    SF-323 single-flight idiom of `refresh_connection`), then evicts it. Success → one
    `in_transaction()`: `touch_last_refreshed(connection)` + AUTHENTICATED mirror
    (`last_refreshed_at`, `require_present`) → `ProfileTransitionConflict` →
    `WriteConflict("superseded", subject="profile")` → legacy `409 profile_conflict` (a delete
    that removed the document during the network window wins, as in H-1). Failure
    (`CredentialNotFoundError`, `AuthError`) → `mark_error(connection)` (fenced `active`) + ERROR
    mirror only when the row was actually marked + evict + `invalidate_session` →
    `TargetReauthRequired(provider, bare legacy URL, message)` → the legacy `401 auth_required
    {message, reauth_url}` body. No marker advance on refresh (legacy refresh never fenced the
    OAuth callback either; the blob address does not change).
  - **D-S2b3-5 deviation (d), flagged:** an effective row in `error` or `pending` is NOT
    refreshed — `401 auth_required` with the bare legacy `reauth_url`, no network call, no row
    or document mutation. Legacy `refresh_profile` ignored the document state and could flip an
    ERROR/PENDING document back to AUTHENTICATED from whatever blob sat at the address. For a
    migrated pair the house rule holds instead (SF-291: an errored OAuth Connection is
    superseded by re-auth, never revived; `reactivate` is api-key-only by design), and a pending
    row belongs to the flow in progress. The alternative — reviving the row on refresh success
    — needs a new store transition and contradicts D-S2b2-3 (error rows are dead for re-auth).
- **Planned files:**
  - NEW `apps/aigateway/src/aigateway/core/provider_access/connection_facade.py` (≤ 200 lines)
  - MOD `apps/aigateway/src/aigateway/core/provider_access/__init__.py` (export `FacadeTarget`,
    `facade_target`, `patch_facade`, `refresh_facade`)
  - MOD `apps/aigateway/src/aigateway/routes/auth.py` (`profile_status`, `patch_profile`,
    `refresh_profile` delegate; legacy refresh body unchanged behind `target.connection is None`)
  - MOD `apps/aigateway/src/aigateway/routes/admin.py` (`patch_account_profile` delegates)
  - NEW `apps/aigateway/tests/unit/core/provider_access/test_connection_backed_facades.py`
    (status/patch/admin-patch + the two chat characterisation tests)
  - NEW `apps/aigateway/tests/unit/core/provider_access/test_connection_backed_refresh.py`
  - no schema change (S1 n/a); no prior test touched
- **Test plan (RED first, HTTP level over `ConnectionBackedHarness`):**
  0. chat over a migrated pair sends the Profile-addressed credential (`api_key == "tok"`) and
     touches the Connection's `last_used_at`; a rejected dispatch (`AuthenticationError`) answers
     `401 auth_required` with the legacy `reauth_url`, marks the Connection `error` and the
     status facade AGREES (`state == "error"`) — the status half is the RED.
  1. status renders state/auth_type from the effective Connection (document says
     authenticated/oauth, row says error/api_key); 404 with `{provider, name}` when the pair has
     no effective Connection, and the list omits it; an unmigrated pair keeps the document and
     writes no marker.
  2. patch keeps defaults/account_label on the document, response renders the Connection state,
     row and marker untouched; 404 when no effective Connection (document unchanged); admin
     PATCH renders the same.
  3. refresh over an active migrated pair rewrites the locator blob, touches
     `last_refreshed_at` on the row, mirrors AUTHENTICATED + `last_refreshed_at`, evicts and
     invalidates under the locator name, marker unchanged; a failed refresh marks the row
     `error` (label `error:<id>`), mirrors ERROR, status agrees, 401 with the bare `reauth_url`
     and no sentinel leak; a refresh whose network window saw the pair deleted answers
     `409 profile_conflict` and resurrects nothing; an `error` row and a `pending` row answer
     401 without any mutation; an unmigrated pair keeps the legacy body (marker stays `none`).
- **Acceptance:** all new tests green; `test_auth_routes.py` (`test_status_*`, `test_patch_*`,
  `test_refresh_*`), `test_admin_profile_routes.py`, `test_chat_x_profile.py`,
  `tests/unit/core/provider_access` green and untouched; `run_gates.py aigateway --base 99e2d4b2`
  ALL GREEN; no `# type: ignore`; files ≤ 450 lines (routes/auth.py pre-existing exception:
  delegation only).

### S2'b4 — evidence gathered (2026-09-22, before the plan): the Connection-native routes over a migrated pair's effective row

- **Finding (real defects once a pair is migrated; no test yet):** every Connection-native path
  addresses the blob at the UUID address `credential_key_for(account, connection_id)`, never at
  the row's `credential_locator` — for a migrated pair's effective row (locator = the Profile
  address) that is the WRONG slot: `routes/oauth_connections.py::refresh_connection` and
  `core/oauth/token_service.py::get_token` would read an absent blob → `CredentialNotFoundError`
  → `mark_error` on a healthy row; `set_connection_api_key` would write the new key where chat
  never reads and leave the old blob live; `delete_connection` deletes the right blob (it uses
  the locator) but evicts the strategy cache under the UUID name, so the locator-keyed cached
  strategy keeps serving the deleted token (SF-282 regression). `credential_strategy_for_connection`
  (S1) exists exactly for this — S2'b4 routes these paths through it and evicts under the
  locator-derived name.
- **Marker awareness:** `delete_connection`/`set_connection_api_key` on a pair's effective row
  are authority-changing → advance the marker (delete: effective → None, S2'b1 op 9 shape;
  api-key: mirror the compat document as S2'b1 op 8 does). `patch_connection` (label only) is
  metadata → no marker.
- **Stop-and-ask candidate:** `start_connection_oauth` / `create_api_key_connection` on a
  provider whose pair is `migrated` create a SECOND Connection for the pair — "multiple
  credentials per provider" (prompt: stop and ask). Options for the owner: (i) refuse with
  `409 connection_conflict` naming the effective Connection, (ii) allow the row but keep the
  marker's effective unchanged (a stray, never-effective Connection), (iii) treat the new row
  as a re-auth of the pair (= S2'b2's in-place flow). Not implemented until decided.

### S2'b4 — planned files (2026-09-22, before RED): the Connection-native routes over a migrated pair's effective row

- **Intent:** the Connection-native routes (`POST …/connections/{id}/refresh`, `GET …/{id}/token`,
  `PUT …/{id}/api-key`, `DELETE …/{id}`) address a migrated pair's effective row at its
  `credential_locator` (the Profile blob — today they read/write/evict the UUID address, the
  S2'b4 evidence defects) and, for the two authority-changing writes, keep the pair marker and
  the compat document coherent with what the legacy facade would have done (op 8 / op 9 shapes).
  A row that is NOT a migrated pair's effective row is a plain Connection: every native route
  behaves byte for byte as before (the UUID locator derives today's UUID name), and every prior
  Connection-native suite stays green unmodified.
- **Design (D-S2b4-1..6):**
  - **D-S2b4-1 placement:** new core module `core/provider_access/connection_native.py` —
    `credential_name_of(plugin, connection, *, account_id) → str` (locator-derived; today's UUID
    name for a plain row), `effective_pair_of(connection) → PairAuthority | None` (the `migrated`
    marker naming THIS row as effective, else None), `retire_effective(app, connection)` (delete
    time: marker effective → None, the pair's compat document(s) removed; runs inside the
    caller's transaction BEFORE `mark_revoked`), `republish_effective_api_key(app, connection, *,
    raw_api_key)` (key replacement: marker generation +1 with the SAME effective id, the compat
    document(s) mirrored; inside the caller's transaction BEFORE `reactivate`). Lost fences →
    `WriteConflict("superseded", subject="connection")`, rendered by the existing
    `refusals_as_http()` as `409 connection_conflict` — the native vocabulary. Routes delegate
    only and keep every 404/409/400 they answer today.
  - **D-S2b4-2 locator addressing everywhere:** `refresh_connection` builds the SHARED cached
    strategy with `credential_strategy_for_connection` under the locator-derived name;
    `token_service.get_token` derives its name from the locator (a duck-typed row without a
    locator falls back to the UUID name, so the service's own fakes are untouched);
    `set_connection_api_key` builds its strategy and evicts under that name; `delete_connection`
    evicts under it (SF-282 for a migrated row). Behaviour-preserving for plain rows: a UUID
    locator spells exactly `credential_key_for(account, id)` (S2'b3 evidence).
  - **D-S2b4-3 deleting the effective row retires the pair** (op 9 shape, one lock order marker →
    index → connection row → blob, inside the route's existing `in_transaction()`): `advance(
    migrated, effective=None)` → remove the pair's compat document(s) → `mark_revoked` → delete
    the locator blob; evict under the locator name. WHY remove the document: after an R1 rollback
    the legacy path must not find a document for a credential the user deleted ("delete removes
    only one → old credential later reappears"). Post-delete shape = op 9's (status 404, list
    omits, op 8 starts over at the Profile address).
  - **D-S2b4-4 replacing the key on the effective row fences and mirrors** (op 8 shape): `advance(
    migrated, effective=same id)` so a Profile-facade OAuth callback still in flight loses its
    generation fence instead of publishing tokens over the key just set (never last-write-wins
    between two secrets); mirror the compat document(s) exactly as op 8 does (`auth_type`
    api_key, AUTHENTICATED, masked `account_label`, `last_refreshed_at`; `defaults` untouched);
    then `reactivate` and the blob, as today. `connection_admin._mirror` is promoted to
    `api_key_mirror` (exported) so both writers share ONE mirror — code, no test touched.
  - **D-S2b4-5 refresh/token mark the row only:** per the card ("the legacy Profile's credential
    state is not written again — the shells render from the Connection") the native refresh and
    token paths touch neither the compat document (no ERROR mirror, no `last_refreshed_at`) nor
    the marker (as S2'b3's refresh). **Known asymmetry (f), flagged:** after a native refresh the
    legacy status body still shows the document's `last_refreshed_at`; the candidate fix is
    `legacy_view` rendering it from the Connection — owner call, not this slice.
  - **D-S2b4-6 a second Connection on a migrated provider:** the creation routes
    (`start_connection_oauth`, `create_api_key_connection`) are UNCHANGED = option (ii) of the
    evidence note (today's behaviour: the new row is never effective, the marker does not move,
    chat keeps the effective row). Pinned by a characterisation test so the "no silent authority
    change" property is explicit; the policy choice (i)/(ii)/(iii) is flagged for the owner. Not a
    STOP: nothing is guessed and no selectable multi-account is introduced.
  - `patch_connection` (label) is metadata → untouched. `credential_key_for` stays exported (the
    plain-row name, the shims, the prior suites).
- **Planned files:**
  - NEW `apps/aigateway/src/aigateway/core/provider_access/connection_native.py` (≤120 lines).
  - MOD `apps/aigateway/src/aigateway/core/provider_access/connection_admin.py` — `_mirror` →
    `api_key_mirror` (+ `__all__`), call site renamed; nothing else.
  - MOD `apps/aigateway/src/aigateway/core/provider_access/__init__.py` — export the four names.
  - MOD `apps/aigateway/src/aigateway/routes/oauth_connections.py` — `refresh_connection`,
    `set_connection_api_key`, `delete_connection` per D-S2b4-2/3/4 (delegation + name).
  - MOD `apps/aigateway/src/aigateway/core/oauth/token_service.py` — locator-derived name.
  - NEW `apps/aigateway/tests/unit/core/provider_access/test_connection_backed_native_routes.py`.
  - No schema change → no migration (S1 rule satisfied by construction).
- **Test plan (RED first, HTTP-level over `ConnectionBackedHarness`; probes reused):**
  - refresh of the effective row rewrites the LOCATOR blob (Profile address), leaves the UUID
    address empty, touches the row, evicts under `credential_name_for(account, "default")`,
    marker unchanged, document untouched; a rejected refresh marks the row, leaks no provider
    body, evicts under the locator name, document untouched.
  - token of the effective row serves the locator blob's access token and touches `last_used_at`
    (today: 401 + a healthy row marked error).
  - deleting the effective row: 204; row revoked; locator blob gone; marker migrated / effective
    None / generation +1; compat document gone; legacy status 404; eviction under the locator
    name. Deleting a STRAY row of a migrated pair leaves marker, document and effective row
    alone. A lost marker fence → 409 `connection_conflict`, nothing revoked or deleted.
  - replacing the key on the effective row: 200 active; locator blob holds the new key; UUID
    address empty; marker generation +1 with the same effective; document mirrored (api_key,
    AUTHENTICATED, masked label); eviction under the locator name; legacy status agrees. On an
    errored effective row it reactivates and the facade shows `authenticated`. A lost fence →
    409 `connection_conflict`, blob and row unchanged. On a stray row the marker does not move.
  - patching the effective row's label moves no marker and touches no document.
  - starting a second OAuth Connection on a migrated provider: 201, marker and effective
    unchanged (D-S2b4-6 characterisation).
- **Acceptance:** all new tests green; every prior Connection-native suite
  (`test_oauth_connections_routes.py`, `test_oauth_connection_api_key_routes.py`,
  `test_oauth_connection_token_service.py`, `test_connection_delete_set_race.py`,
  `test_api_key_connection_races.py`, `test_api_key_connection_validation.py`,
  `test_oauth_connection_label_exists.py`, `test_oauth_connection_store.py`) and every S1–S2'b3
  suite green unmodified; gates green; ledger outcome + memory updated; no commit.

### S2'c — planned files (2026-09-22, before the run): PostgreSQL coexistence and race tests for the Connection side

- **Intent:** prove on a REAL PostgreSQL (testcontainers `postgres:16-alpine`, `AIGW_TEST_PG=1`,
  `needs_postgres`) what SQLite's single-writer serialisation cannot: the pair marker's
  compare-and-set is a row-lock fence under READ COMMITTED, so two authority writers on one
  migrated pair — the native `DELETE …/connections/{id}`, the legacy
  `PUT …/profiles/{name}/api-key` (op 8), the Profile-facade OAuth callback — never both commit;
  the loser answers `409` with everything rolled back, and the pair ends in ONE coherent state
  (no orphan blob, no resurrected credential, no key silently overwritten by tokens). Also the
  JSONB round trip of `credential_locator` (a migrated row's locator must come back as the
  mapping `credential_name_from_locator` parses) and the `provider_credential_slots` table as
  migration 0012 creates it on PostgreSQL (unique pair, CAS on `generation`).
- **Design (D-S2c-1..3):**
  - **D-S2c-1 reuse the lane, add no fixture module:** import `postgres_database_url` /
    `pg_client` / `_ValidValidationService` from `test_lifecycle_postgres_races.py` (its module
    fixture spins one container per module and migrates to head — so a broken 0012 on
    PostgreSQL fails at fixture time); no `testcontainers` import of our own (no new
    `# type: ignore`), no shared `conftest.py` (would rewrite a prior test module).
  - **D-S2c-2 the hold is the marker advance:** monkeypatch `PairAuthorityStore.advance` with a
    wrapper that performs the real advance and THEN waits (inside the open transaction, holding
    the marker row lock) for the writer the predicate names; the second writer signals
    `attempted` before its own advance blocks on that lock. Release → the holder commits → the
    blocked `UPDATE … WHERE generation = <stale>` matches 0 rows → `PairAuthorityConflict` →
    `WriteConflict` → `409`. Both directions for delete vs op 8; one direction for the OAuth
    callback vs the native key replacement (the callback holds).
  - **D-S2c-3 verification tests, not RED:** the code under test exists (S1–S2'b4); these pin
    PostgreSQL behaviour — a first-run failure is a real defect, recorded as such.
- **Planned files:**
  - NEW `apps/aigateway/tests/integration/test_provider_access_backing_postgres.py` (≤450
    lines): a PostgreSQL-local seeding helper (document + Profile blob + effective Connection
    at the Profile locator + `migrated` marker) and the tests below.
  - No production change expected. If one is needed it gets its own RED test in this section.
- **Test plan:**
  - marker CAS on PostgreSQL: `advance(expected=0)` → gen 1; a second `advance(expected=0)`
    → `PairAuthorityConflict` (unique pair; the aborted transaction rolls back cleanly);
    `advance(expected=1)` → gen 2.
  - a migrated pair on PostgreSQL: legacy status renders `authenticated/oauth` from the
    Connection; native `GET …/token` serves the Profile blob (JSONB locator round trip).
  - native delete holding the marker → legacy op 8 blocks then answers `409`; final: row
    revoked, marker `migrated`/effective None/gen 2, no document, no blob; a retried op 8 then
    starts over (new effective Connection at the Profile address, gen 3).
  - legacy op 8 holding the marker → native delete blocks then answers `409
    connection_conflict`; final: row active with the NEW key at the Profile address, gen 2; a
    retried delete → 204, gen 3.
  - Profile-facade OAuth callback holding the marker → native key replacement blocks then
    answers `409 connection_conflict`; final: tokens published at the Profile address, the key
    never written, row active/oauth.
- **Acceptance:** `AIGW_TEST_PG=1 uv run pytest tests/integration/test_provider_access_backing_postgres.py -q`
  green locally (Docker 29.6.1); the module skips cleanly without `AIGW_TEST_PG=1` (the default
  gate lane); gates green; ledger outcome records the exact commands and counts.

### S4 — planned files (2026-09-22, before RED): the secret-aware backfill tool

**Intent.** `python -m aigateway.migrate_profiles --dry-run|--apply|--rollback (--account <id>|--all)
[--journal PATH]` — the card's "Classification before authority": classify every `(account,
provider)` pair from the legacy index, the non-revoked Connections and the marker, then (apply only)
publish the disposition through `PairAuthorityStore.advance` inside ONE transaction per account.
Nothing here decrypts a credential for transfer (a migrated Connection reads the Profile's blob
through its locator, S1), nothing calls a provider, and nothing deletes.

**Design inputs.** Card v4 "Stage B Target" classification table and its dry-run/apply/report
sentence; spec §7 "E/B/C migration" (per-account transaction, classify before write, quarantine
non-equivalent pairs, journal, resumable, never the pre-upgrade job) and "R0–R4" (R1 = marker reset
keeping every blob); D3 (quarantine, never last-write-wins), D5 (R1), D11 conservative, D12 Stage B
rule (several active Connections stay unmigrated), D14 (one write owner), D16 (a) (the legacy
document stays as the defaults-only compatibility document — the backfill leaves it untouched),
D19/D20 names. Verified facts: `credential_locator_for(cp, account, name)` IS the Profile blob
address (`aigateway:<cp>:<account>:<name>` / `default`); the legacy dual OAuth write persists a COPY
of the same credential document at the shadow Connection's UUID address
(`routes/auth.py:_record_oauth_connection_completion` → `_persist_connection_credentials`), so
"proven the same" is decidable by comparing the two decrypted documents in-process;
`OAuthConnectionStore.list` excludes revoked rows; `unique_together (account_id, provider, label)`
cannot collide for a Profile-only pair (revoked rows are relabelled `revoked:<id>`);
`ORMStore.read` raises `SecretDecryptionError` for an undecodable blob; `credential_service_provider_for(None,
provider)` falls back to the provider; `set_auth_type` returns `None` only when the row vanished.

**Decisions (D-S4-1..8).**
- **D-S4-1 — module placement.** Core logic in `core/provider_access/backfill_classify.py`
  (read-only classification) and `core/provider_access/backfill_apply.py` (apply, rollback, report);
  the CLI shell `aigateway/migrate_profiles.py` beside `main.py`/`cli.py` wires Settings → `init_db`
  → `build_secret_store`/`set_active_secret_store` → `ProviderRegistry` + `load_plugins` (the shell
  is app-level like `main.py`, so importing the loader keeps "core never imports plugins" intact)
  and prints the JSON report. No leading-underscore module names (D19).
- **D-S4-2 — classification is a pure function of three reads** (documents, non-revoked
  Connections, marker) plus blob reads at the Profile address and at a single active Connection's
  locator. Dispositions and categories (the category is the marker note and the report line):
  `already_migrated` (marker migrated, any effective — idempotency, no write);
  `provider_unknown` → none (no plugin, nothing could serve it); `several_documents` → none;
  `profile_pending` / `profile_error` → none; `profile_credential_missing` /
  `_undecodable` / `_malformed` → none; `profile_only` → migrated (CREATE a Connection);
  `connection_only` → migrated naming the single active row iff it is the ONLY non-revoked row;
  `several_active_connections` → none (D12 Stage B rule); `no_effective_connection` → none;
  Profile + exactly one non-revoked Connection that is `active`: locator equals the Profile address
  → `profile_mapped` (migrated, names it); decrypted documents equal → `profile_connection_same`
  (migrated, names it); documents differ → `credentials_differ` (quarantined); its blob missing /
  undecodable / malformed → `connection_credential_*` (quarantined); Profile + one non-active row
  → `connection_<status>` (quarantined); Profile + several rows → `several_connections`
  (quarantined). A `quarantined` marker is re-classified on every run: clean → migrated from its
  current generation (the owner removed the conflict), still conflicting → no write (KISS).
  Explicit owner mapping ("or explicitly mapped by the owner") is NOT a CLI option in S4 — the
  quarantine report is the owner's input; a mapping flag would be a policy choice (stop-and-ask).
- **D-S4-3 — the tool writes only `migrated` and `quarantined` rows.** An absent marker reads as
  `none` (S1), so "not promoted" is a report-only disposition; writing `none` rows would be a write
  for nothing.
- **D-S4-4 — apply = one `in_transaction()` per account** (card + spec): for each pair in the
  plan, `profile_only` creates the Connection (`create_pending(label=<Profile name>,
  credential_provider=cp, credential_locator=credential_locator_for(cp, account, name))` →
  `set_auth_type("api_key")` when the document says so → `complete(label, identity=None)`), then
  `advance(expected_generation=<marker generation observed by the plan>, migrated,
  effective=<id>, note=<category>)`; `connection_only`/`profile_mapped`/`profile_connection_same`
  advance naming the existing row; quarantines advance to `quarantined` with `effective=None`.
  `PairAuthorityConflict` or `IntegrityError` (a racing writer — including a second apply run
  creating the FIRST marker) rolls the whole account back and reports the account as `conflict`;
  the run continues with the next account and exits 3 so a scheduler retries. Idempotent by the
  marker: a re-run classifies every migrated pair `already_migrated` and mints nothing.
- **D-S4-5 — dry-run reads exactly what apply reads and writes nothing**; the tests compare raw
  snapshots of `credential_blobs`, `oauth_connections` and `provider_credential_slots` before and
  after, and scan the report, the journal and the captured log for the test credential strings,
  `system_prompt` text and the `v1:` ciphertext prefix.
- **D-S4-6 — report and journal carry opaque identifiers only**: account UUIDs, provider ids,
  Connection UUIDs, dispositions, categories, generations, counts. No Profile names, labels,
  defaults, tokens, keys, credential names or ciphertext. `--journal PATH` appends one JSON line
  per pair record plus one summary line (the report is the same records, printed as one JSON
  document on stdout).
- **D-S4-7 — `--rollback` is the R1 rehearsal** (D5, card "Expand, never contract"): for each
  `migrated` pair of the selected accounts `advance(expected=<gen>, "none", effective=None,
  note="rollback")` — every blob, Connection row and document is kept; the legacy Profile owns the
  pair again and its own blob serves it (an older refresh token recovers visibly through re-auth,
  never by a silent choice). The report lists per pair `alias_documents`: the count of legacy
  documents whose `credential_locator_for(cp, account, doc.name)` is NOT the effective Connection's
  locator — those would read as `credential_missing` after rollback (the S2'b1 finding), so the
  owner sees them BEFORE resetting. `--dry-run` combined with `--rollback` reports without writing.
  Flagged for owner review as a mechanism choice (a CLI flag rather than a manual marker reset).
- **D-S4-8 — `--all` enumerates `Account` rows** (every Connection has an Account FK; a legacy-index
  document whose account has no row is unreachable through the app anyway and is out of scope;
  recorded here, not solved).

**Planned files.**
- `apps/aigateway/src/aigateway/core/provider_access/backfill_classify.py` (NEW, ≤450):
  `Disposition`, `PairPlan` (frozen dataclass: account_id, provider, disposition, category,
  action `create|name|quarantine|skip`, connection_id, generation, profile: the single document
  when the action creates, alias_documents), `BackfillContext` (credential_store, profile_index,
  providers), `classify_account(ctx, account_id) -> tuple[PairPlan, ...]`, `classify_pair(...)`.
- `apps/aigateway/src/aigateway/core/provider_access/backfill_apply.py` (NEW, ≤450):
  `apply_account(ctx, account_id) -> AccountResult`, `rollback_account(ctx, account_id)`,
  `run_backfill(ctx, *, mode, account_ids, journal) -> BackfillReport` (+ `to_json`),
  `AccountResult`/`BackfillReport` dataclasses.
- `apps/aigateway/src/aigateway/migrate_profiles.py` (NEW, ≤450): `parse_args`, `main(argv) -> int`
  (0 ok, 2 usage, 3 conflicts/retry), `__main__` guard; `python -m aigateway.migrate_profiles`.
- `apps/aigateway/src/aigateway/core/provider_access/__init__.py`: export the new names.
- Tests (NEW): `tests/unit/core/provider_access/test_backfill_classify.py`,
  `tests/unit/core/provider_access/test_backfill_apply.py`,
  `tests/unit/test_migrate_profiles_cli.py` (argument contract + a real `python -m` subprocess
  dry-run on the fixture database), `tests/integration/test_provider_access_backfill_postgres.py`
  (`needs_postgres`: apply + idempotent re-run + the FIRST-marker create race between two apply
  runs → one wins, the loser rolls back with no duplicate Connection, the re-run is a no-op).
- No schema change (S1 rule satisfied trivially: no migration needed).

**Test plan (RED first).** Classification: one test per category above; a classification run
writes nothing. Apply: Profile-only oauth and api_key pairs migrate without re-entry (Connection at
the Profile locator, label = name, active, auth_type from the document; marker migrated gen 1; the
document and blob byte-identical; the legacy status shell and the native token route then serve
the pair); Connection-only naming; quarantine keeps legacy behaviour; idempotent second run;
crash before commit (advance raises once) leaves no Connection row; racing writer → conflict
reported, account rolled back (two providers, one account); dry-run no-write + no-leak; rollback
restores legacy authority and reports alias documents; `--all` visits a second provisioned
account. CLI: mutually exclusive modes, `--account` xor `--all`, exit codes, real subprocess
dry-run output is JSON with counts and no secret. PostgreSQL: as listed.

**Acceptance.** All new tests green; prior suites unmodified and green; `uv run
.claude/scripts/run_gates.py aigateway` ALL GREEN; `AIGW_TEST_PG=1 uv run pytest
tests/integration/test_provider_access_backfill_postgres.py -q` green; ledger outcome, mirror,
memory updated; NO staging/commit.

## Outcome (fill at the end — required before COMMIT)

### S1 — slot store + locator-authoritative strategy factory: DONE (uncommitted, 2026-09-22)

- **Actual files (all new unless noted):** `apps/aigateway/src/aigateway/core/provider_access/models/__init__.py`,
  `…/models/provider_credential_slot.py` (72 lines), `…/pair_authority.py` (159),
  `…/connection_locator.py` (85), `apps/aigateway/src/aigateway/migrations/0012_provider_credential_slots.py` (87),
  `apps/aigateway/src/aigateway/db.py` (+1 line: model registration);
  tests `tests/unit/core/provider_access/test_pair_authority_store.py` (323),
  `tests/unit/core/provider_access/test_connection_locator.py` (222),
  `tests/unit/test_migration_0012_provider_credential_slots.py` (230). Planned = actual.
- **Gates (worktree root, `uv run .claude/scripts/run_gates.py aigateway --base 99e2d4b2`):**
  append-only test check ✓ · `ruff check` ✓ · `ruff format --check` ✓ · `pyright` ✓ (0 errors) ·
  `check_no_enterprise.py` ✓ · `pytest --cov=aigateway --cov-fail-under=80 -q` ✓ — ALL GATES GREEN.
  Prompt gate `uv run pytest -m "not live" -q`: 4701 passed, 42 skipped, 0 failed (2:12).
  PostgreSQL lane: `AIGW_TEST_PG=1 uv run pytest tests/integration/test_tortoise_migration_smoke.py`
  (testcontainers, Docker 29.6.1) 1 passed — 0012 applied on Postgres over populated rows.
- **Prior tests:** none modified, skipped or weakened (append-only check vs base is green).
- **Deviations:** none from the plan. Two interpretive decisions recorded in code and here:
  (1) a `migrated` marker with no effective Connection is a legitimate post-delete state (the pair
  stays Connection-owned; falling back to `none` would let the retained, still-authenticated legacy
  index entry serve the old credential again — the "reappears later" bad state); (2) a malformed
  `credential_locator` falls back to today's UUID-derived blob address, which is unique to that
  Connection, so no foreign secret can be served (a migrated Connection with a corrupt locator
  therefore reads an absent blob → `credential_missing`, never another pair's secret).
- **Finding surfaced, not fixed:** pre-existing autodetector drift `Alter field account on
  OAuthConnection` (0002 spelling vs Tortoise 1.1.8 projected state) — see "S1 — RED → GREEN
  evidence and findings". Needs an owner decision / its own ticket.
- **Wisdom review:** store is read/list/advance only (no policy, no speculative transitions);
  tests assert the fence, tenant/provider isolation, cascade/SET NULL and the no-defaults/no-secret
  shape rather than "it ran"; blast radius = one new table + one config line, no public contract
  touched; no secret is stored, logged or derivable from the marker; model-per-file with abstract
  `Base*` and `Meta` first (tortoise-dev); migration shipped in the same iteration (S1 rule); no
  `# type: ignore`, no bare `except`.
- **Commit:** NOT made — owner authorization required (goal + prompt). Suggested at unit end:
  `feat(aigateway): move provider-access backing toward connections` / `Refs: OME-1208`.

### S2'a — pair-authority routing + Connection-backed read path: DONE (uncommitted, 2026-09-22)

- **Actual files (new unless noted):** `apps/aigateway/src/aigateway/core/provider_access/connection_authority.py`
  (176 lines — migrated-pair ops 2/4/5 + availability mapping), `…/connection_backed.py` (113 —
  `ConnectionBackedProviderAccess(ProfileBackedProviderAccess)`), `…/profile_backed.py` (modified:
  `connection_target` is locator-authoritative, `plugin` kw, both call sites), `…/__init__.py`
  (modified: exports `ConnectionBackedProviderAccess`, `PairAuthority`, `PairAuthorityConflict`,
  `PairAuthorityStore`), `apps/aigateway/src/aigateway/main.py` (modified: `app.state.provider_access`
  is the Connection-backed port; the admin slot is unchanged until S2'b);
  tests `tests/unit/core/provider_access/connection_backed_harness.py` (143),
  `test_connection_backed_resolve_contract.py` (63 — re-runs the resolve contract over a migrated
  seam + one twin), `test_connection_backed_authorize_contract.py` (33 — re-runs the authorize
  contract), `test_connection_backed_routing.py` (367 — marker routing, refusal mapping, write
  ownership on the Connection row, availability overlay). Planned = actual; the `legacy_name`
  field planned on `MigratedBacking` was dropped as unused (YAGNI).
- **RED evidence:** the three new modules failed collection with `ImportError` (`PairAuthorityStore`,
  `ConnectionBackedProviderAccess` not exported) — the right reason. **GREEN:** 58 new tests pass;
  `uv run pytest -m "not live" -q` → 4759 passed, 42 skipped, 0 failed (2:14).
- **Gates (worktree root, `uv run .claude/scripts/run_gates.py aigateway --base 99e2d4b2`):**
  append-only ✓ · `ruff check` ✓ · `ruff format --check` ✓ · `pyright` ✓ (0 errors) ·
  `check_no_enterprise.py` ✓ · `pytest --cov` ✓ — ALL GATES GREEN. PostgreSQL lane not exercised
  in S2'a (no schema change; Connection-side coexistence/race tests are S2'c).
- **Prior tests:** none modified, skipped or weakened. Contract suites are re-run by importing the
  existing modules and overriding only the `harness` fixture (append-only forbids adding a fixture
  parameter to the originals).
- **Decisions (D-S2a-1..5, recorded before RED above):** subclass not sibling (prior pins/seams);
  migrated pair = document-present → effective Connection decides, document-absent → today's
  no-profile path; `connection_target` locator-authoritative for every Connection (stray selector
  cannot poison the effective Connection's blob address); ops 4–5 apply the Profile rules to the
  Connection row (MISSING evicts only; REJECTED/dispatch failure → `mark_error` + evict +
  invalidate; dispatch failure rewrites `reauth_url` to the legacy facade URL); availability
  overlays migrated providers from the effective Connection and never falls back silently on an
  unreadable marker store.
- **Deviations:** none from the plan. **Flags for S2'b:** (1) a migrated target's `context_stamp`
  takes the Connection shape (`conn:…`), so published contract ids re-key exactly once at
  migration — expected and one-way; (2) `OAuthConnectionStore.mark_error` relabels an OAuth
  Connection `error:<id>` and clears `identity_sub`, so facade re-auth for a migrated pair must
  republish the SAME effective Connection (label restored by `complete`), never a new row;
  (3) facades `profile_status`, `patch_profile`, `refresh_profile`, `start_oauth` and the OAuth
  callback still read/write the Profile index directly — S2'b routes migrated pairs through the
  Connection authority (D14: Connection owns all writes incl. the callback).
- **Wisdom review:** no speculative generality (one subclass, one dataclass marker, one status
  table); tests assert the marker read count, the untouched legacy document, the Connection-row
  transitions and the blob addresses rather than "it ran"; blast radius = the app's provider-access
  slot (same class contract, isinstance-compatible) + a keyword-only `plugin` on an internal
  helper; no secret logged or exposed — refusals carry the bare legacy URL and the sanitized
  message; no `# type: ignore`, no bare `except`, files ≤450 lines.
- **Commit:** NOT made — owner authorization required.

### S2'b1 — Connection-backed credential admin (ops 7–9): DONE (uncommitted, 2026-09-22)

- **Actual files (new unless noted):** `apps/aigateway/src/aigateway/core/provider_access/connection_admin.py`
  (317 lines — `ConnectionBackedCredentialAdmin(ProfileBackedCredentialAdmin)`, `legacy_view`,
  the mirror builder and the fenced Connection publication), `…/connection_authority.py`
  (modified: public `LEGACY_STATE_FOR_STATUS`, the card's state mapping in legacy vocabulary),
  `…/__init__.py` (modified: export), `apps/aigateway/src/aigateway/main.py` (modified:
  `app.state.provider_credential_admin = ConnectionBackedCredentialAdmin(app)`),
  `apps/aigateway/src/aigateway/core/oauth/store.py` (modified: additive `credential_locator`
  keyword on `create_api_key`, default unchanged); tests
  `tests/unit/core/provider_access/connection_backed_admin_probes.py` (helpers, 116),
  `test_connection_backed_admin.py` (400 — routing + op 8, incl. the two fences),
  `test_connection_backed_admin_delete_list.py` (176 — op 9, op 7, R1 rollback),
  `test_connection_backed_admin_contract.py` (91 — re-runs the admin contract over a migrated
  seam; one test re-expressed). Planned = actual, plus the test split (the routing suite grew past
  450 lines, so the probes moved to a shared helper module and delete/list/rollback to their own).
- **RED evidence:** collection `ImportError: cannot import name 'ConnectionBackedCredentialAdmin'`
  in both suites that import it. **GREEN:** 37 new tests pass (18 re-run contract tests + 19 new);
  `uv run pytest -m "not live" -q` → 4795 passed, 42 skipped, 0 failed (2:14).
- **Gates (worktree root, `uv run .claude/scripts/run_gates.py aigateway --base 99e2d4b2`, run
  twice — after GREEN and after the coverage-pass test):** append-only ✓ · `ruff check` ✓ ·
  `ruff format --check` ✓ · `pyright` ✓ (0 errors) · `check_no_enterprise.py` ✓ · `pytest --cov` ✓
  — ALL GATES GREEN. PostgreSQL lane not exercised (no schema change; S2'c).
- **Prior tests:** none modified, skipped or weakened. The admin contract's `seam` fixture is
  overridden in the re-run module (append-only forbids parametrizing the original); the one test
  that cannot re-run — a seeded PENDING document listed as-is — is named in `NOT_REIMPORTED` and
  re-expressed: on a migrated pair every document of the provider lists as the effective
  Connection's state (one credential per pair).
- **Decisions D-S2b-1..6:** as planned above, all implemented. Two clarifications found in
  GREEN: (1) an effective Connection that is `revoked` at READ time is the post-delete state →
  a new Connection is created at the requested name's Profile address; a Connection revoked
  BETWEEN read and publish is caught by the row fence (`reactivate`/`complete_pending` match 0
  rows → `WriteConflict("superseded", "connection")`, and the unfenced `set_auth_type` rolls
  back with the transaction) — both tested; (2) `delete` with no effective Connection also
  deletes the blob at the document's legacy address, so no orphan can reappear after R1.
- **Coverage pass:** fence tests (stale marker; row revoked mid-flight), store-failure rollback
  (Connection row, document and marker all restored; no key in the exception or the log),
  alias name (second document, ONE blob, read path agrees), rollback availability (marker reset
  → legacy path authorizes with the new key).
- **Deviations:** none from the plan. **Flags for S2'b2:** the OAuth callback
  (`_complete_oauth_for_app`/`_mark_profile_authenticated`/`_record_oauth_connection_completion`),
  `start_oauth`, `profile_status`, `patch_profile`, `refresh_profile` (+ lifecycle) and
  `routes/admin.py::patch_account_profile` still read/write the Profile index directly — for a
  migrated pair they are the remaining second writer (D14). Alias documents are rollback-fragile
  (S4's R1 rehearsal must report them). `LEGACY_STATE_FOR_STATUS` is duplicated in the test
  harness vocabulary (kept: tests should not import the mapping they check).
- **Wisdom review:** no speculative generality (one subclass, three ops, one mirror builder);
  tests assert blob addresses, row transitions, marker generations and rollback state rather
  than "it ran"; blast radius = the app's admin slot (same class contract) + an additive store
  keyword; no secret logged or exposed (the mirror carries the masked label only; refusals carry
  provider/name); no `# type: ignore`, no bare `except`; every file ≤450 lines; no schema change.
- **Commit:** NOT made — owner authorization required.

### S2'b2 — the Profile-facade OAuth flow of a migrated pair: DONE (uncommitted, 2026-09-22)

- **Actual files (new unless noted):** `apps/aigateway/src/aigateway/core/provider_access/connection_oauth.py`
  (291 lines — `MigratedFlow`, `begin_connection_oauth`, `complete_connection_oauth`,
  `fail_connection_oauth`); modified `core/pending_auth.py` (`pair_generation: int | None`),
  `core/oauth/store.py` (`create_pending(..., credential_locator=None)`, default unchanged),
  `core/provider_access/__init__.py` (exports), `routes/auth.py` (delegation only: `start_oauth`
  branches on `begin_connection_oauth`, the legacy publication moved verbatim into
  `_begin_legacy_pending`; `_complete_oauth_for_app` calls `_publish_migrated_oauth` for a flow
  carrying `pair_generation` and skips the shadow write; `_mark_oauth_completion_error` calls
  `fail_connection_oauth`; `_invalidate_profile_session` now delegates to `_invalidate_credential`
  by credential name). Tests: `tests/unit/core/provider_access/connection_backed_oauth_probes.py`
  (helpers, 137), `test_connection_backed_oauth_flow.py` (315 — 4 migrated happy paths, 2
  unmigrated/quarantined characterisations, 3 start-time edges), `test_connection_backed_oauth_fences.py`
  (286 — 3 fences, 3 failures, mid-flight revoke, identity duplicate, taken row, manual exchange).
  Planned = actual. No schema change (S1 n/a).
- **RED evidence:** 12 tests, 9 failing for the right reasons (`'pending' == 'authenticated'`
  during in-place re-auth, `'NoneType' object has no attribute 'status'` — no pending row
  opened, `'PendingAuthEntry' object has no attribute 'pair_generation'`, blob still `ctok`
  at the UUID address, non-JSON body where `409 profile_auth_conflict` was due); the two
  legacy characterisations and the API-key-wins fence passed on the legacy body, as intended.
  One assertion of mine was wrong (`OAuthConnectionStore.list` hides revoked rows) and was
  corrected in the NEW test before GREEN. **GREEN:** 19 new tests pass; the prior OAuth, chat and
  provider-access suites (516 tests incl. the new ones) pass unmodified.
- **Gates (worktree root, `uv run .claude/scripts/run_gates.py aigateway --base 99e2d4b2`):**
  append-only ✓ · `ruff check` ✓ · `ruff format --check` ✓ · `pyright` ✓ (0 errors) ·
  `check_no_enterprise.py` ✓ · `pytest --cov` ✓ — ALL GATES GREEN. Full `uv run pytest -m "not live" -q`:
  4815 passed, 42 skipped, 37 deselected in 129s (2026-09-22). PostgreSQL lane not exercised (no schema change; S2'c).
- **Prior tests:** none modified, skipped or weakened.
- **Decisions D-S2b2-1..6:** implemented as planned. Clarified in GREEN: (1) the mirror's
  `auth_type` for an in-place re-auth comes from `auth_type_of(None, row)` (the house helper —
  the row column is a plain `str`); (2) `begin` treats a label already held by another row of the
  pair's provider as `WriteConflict("superseded", "connection")` → `409 connection_conflict`
  (a migrated-only edge; the legacy start never conflicts on labels); (3) an identity already
  held by another row at completion → the legacy `409 profile_auth_conflict` (the legacy flow
  silently skipped its shadow write instead — for a migrated pair the effective row cannot take
  the identity, so the publication is refused and rolled back).
- **Coverage pass:** marker race under `start` (rolled back, `409 connection_conflict`); foreign
  label; restart of a pending flow reuses its row; revoke between read and publish (row fence,
  marker advance rolled back); identity duplicate; failure whose pending row was taken (marks
  nothing, advance rolled back); manual `exchange-code` publishes identically; store failure at
  completion rolls back row, mirror and marker and leaks no token into the response or the log.
- **Deviations from the card, flagged for the owner (report):** (a) D-S2b2-3 — while an ACTIVE
  effective row re-authenticates through the facade the pair stays usable and reads
  `authenticated` until the callback swaps the blob (Connection-native H-1 semantics); legacy
  showed `pending` and refused. (b) D-S2b2-5 — the compat document IS rewritten as a faithful
  mirror by the authority (state, `auth_type`, label, `last_refreshed_at`), against the card's
  literal "the legacy Profile's credential state is not written again", for D5/R1 coherence.
  (c) D-S2b2-6 — a failed exchange during an in-place re-auth marks nothing (legacy marked
  ERROR). Each is a migrated-pair-only difference; no unmigrated behaviour changed.
- **Flags for S2'b3/S2'b4:** `profile_status`, `patch_profile`, `refresh_profile` (+
  `_profile_refresh_lifecycle`) and `routes/admin.py::patch_account_profile` still read/write the
  index directly (coherent today only because the mirror is faithful; a Connection-native
  `mark_error` or route write diverges them); Connection-native `delete_connection`,
  `set_connection_api_key`, `start_connection_oauth`/callback and `refresh_connection` do not
  consult the marker (the mid-flight-revoke test shows the row fence holds, but their blob writes
  go to the UUID address, so for a migrated pair they are still a second writer); the `400
  provider_does_not_use_oauth` pre-check in `_complete_oauth_for_app` uses the Profile-address
  name as a capability probe (fine: the strategy's existence does not depend on the name).
- **Wisdom review:** simplest wise design — three functions sharing four tiny helpers, no class,
  no new port method (the port stays as accepted); `routes/auth.py` grew by delegation only, the
  legacy body moved verbatim (1360 → 1438 lines, pre-existing oversize, responsibility placed in
  the new module); tests assert rows, blob addresses, marker generations, wire bodies and rollback
  state; blast radius = an optional dataclass field, an optional store keyword, and one extra
  marker read per `start_oauth`; no secret in any log or exception (`error_message` is a fixed
  string, the 503 body names only the description); no `# type: ignore`, no bare `except` added;
  every new file ≤450 lines.
- **Commit:** NOT made — owner authorization required.

### S2'b3 — the Profile status/patch/refresh facades of a migrated pair: DONE (uncommitted, 2026-09-22)

- **Actual files (as planned):** NEW `core/provider_access/connection_facade.py` (183 lines:
  `FacadeTarget(document, connection).view`, `facade_target`, `patch_facade`, `refresh_facade`,
  `_mark_failed`); MOD `core/provider_access/__init__.py` (four exports); MOD `routes/auth.py`
  (`profile_status`, `patch_profile`, `refresh_profile` delegate; the legacy refresh body is
  unchanged behind `target.connection is None`); MOD `routes/admin.py` (`patch_account_profile`
  delegates; the now-unused `_index_store` helper and its `ProfileIndexStore` import dropped —
  the admin module no longer touches the index directly); NEW
  `tests/unit/core/provider_access/test_connection_backed_facades.py` (245 → 12 tests) and
  `test_connection_backed_refresh.py` (10 tests). No schema change; no prior test touched.
- **Item 0 (chat path):** closed by evidence + characterisation: `routes/chat.py` hands the
  port's `CredentialTarget` to `record_dispatch_failure`; a chat over a migrated pair sends the
  Profile-addressed credential and a rejected dispatch marks the effective Connection. The
  lossy `backing_rows` triple lives only in the A1 shim `routes/chat_credentials.py` (no route
  importer; its own suite kept append-only) — nothing changed there.
- **RED evidence:** 9 of 17 failed for the right reasons — `'authenticated' == 'error'` from the
  status/patch/admin-patch facades (the mirror was load-bearing), the failed refresh leaving the
  row `('active', 'default')` instead of `('error', 'error:<id>')`, and the errored/pending rows
  being refreshed (200 with a rewritten blob) instead of refused.
- **GREEN:** 21 new tests; prior `test_auth_routes.py` + `test_admin_profile_routes.py` +
  `test_chat_x_profile.py` + `test_profile_admin_shells.py` +
  `test_profile_resolution_characterisation.py` + `tests/unit/core/provider_access` = 546 passed
  unmodified; `uv run pyright` 0 errors; `uv run ruff check src tests` clean;
  `uv run ruff format --check .` clean.
- **Gates:** `uv run .claude/scripts/run_gates.py aigateway --base 99e2d4b2` (worktree root):
  ALL GATES GREEN (append-only ✓ ruff check ✓ ruff format --check ✓ pyright ✓ check_no_enterprise ✓ pytest --cov ✓; 2026-09-22). Full `uv run pytest -m "not live" -q`: 4836 passed, 42 skipped, 37 deselected in 133s (2026-09-22). PostgreSQL lane not
  exercised (no schema change; S2'c).
- **Decisions as planned (D-S2b3-1..5)**, with two clarifications from GREEN: the migrated
  refresh evicts the shared strategy and invalidates the session on BOTH branches (legacy did
  too); `_mark_failed` mirrors ERROR only when `mark_error` actually transitioned the row — a row
  revoked during the network window is not re-marked and the document keeps its state (test
  `test_a_failure_whose_row_was_revoked_in_the_window_marks_nothing`).
- **Coverage pass:** added the quarantined-pair status (legacy document, marker untouched), the
  patch conflict (`409 profile_conflict` when the document vanishes mid-patch), the missing
  strategy (`400 provider_does_not_use_oauth`, blob untouched) and the revoked-in-window failure.
  Not reachable today and left defensive: `_mark_failed`'s swallowed `ProfileTransitionConflict`
  (the S2'b1 delete revokes the row before the document could vanish alone; S2'b4/S4 may
  reach it).
- **Deviations, flagged for the owner (report):** (d) D-S2b3-5 — an effective row in `error` or
  `pending` answers `401 auth_required` (bare legacy `reauth_url`) without a network call; legacy
  `refresh_profile` ignored the document state and could revive an ERROR/PENDING document from
  whatever blob sat at the address. (e) Same guard-now scope as legacy H-1: a delete committing
  during the refresh network window wins for the row, the marker and the document
  (`409 profile_conflict`), but the strategy instance in flight has already rewritten the blob at
  the locator — the legacy `_profile_refresh_lifecycle` SCOPE note applies unchanged; a
  compensation delete was rejected (it could remove a key written by a newer flow).
- **Known asymmetry (not a defect after S2'b3):** op 5 (`record_dispatch_failure_migrated`) and
  authorize-time marking write the Connection only, not the mirror (S2'a predates D-S2b-2); with
  every facade READ now Connection-authoritative the mirror's `state` is not load-bearing, and a
  rolled-back (R1) legacy path re-marks the document on its own next 401. Left as is.
- **Wisdom review:** simplest wise design — one small dataclass + three functions; routes gain
  delegation only (`git diff -U0` checked: no body other than the fork moved); no new dependency;
  no secret in any log or body (the failure `message` is the strategy's sanitized text; the
  sentinel test proves the provider body does not leak); no fail-open path (a non-effective
  Connection is 404, never the document); blast radius = the four facade routes, all pinned by
  prior suites; card conventions honoured; no `# type: ignore`; new files ≤ 450 lines
  (`routes/auth.py` was already over — delegation only).
- **Commit:** NOT made — owner authorization required.


- **Actual files (design repository, PR https://github.com/OpenMined/screamingface-design/pull/23):**
  `solutions/README.md`, `solutions/screamingface/product/aigateway/component/provider-access/index.md`
  (v4), `solutions/screamingface/product/aigateway/protocol/provider-credential-admin/index.md`
  (v3), `solutions/screamingface/protocol/provider-access-availability/index.md` (v2) —
  4 files, 160 insertions, 8 deletions. Application repository: this ledger and the task mirror
  only; no application source changed.
- **Commits:** design `4f3593dc85a9d7074644cfd9df8293c3d64cfd29` —
  `docs(catalog): describe the Stage B backing transition behind provider access`
  (`Refs: OME-1208`; no `Co-Authored-By`), pushed to
  `origin/OME-1208-provider-access-backing-transition`; PR #23 opened against design `main`.
  Owner authorized commit, push and PR on 2026-09-22; merge is the owner's step. Nothing
  committed in the application repository.
- **Gates:** catalog validator `metaframework@0.5.1 check --dir ./solutions --since origin/main`
  — 0 errors, 3 pre-existing warnings, 113 entities, 3 entities changed with clean version bumps
  (run before staging). The design repository has no CI workflow; the validator is the gate.
  AIGateway gates not run (no application change).
- **Deviations:** none. The A4 sections were not refreshed (owner: Stage B scope only). The merged
  OME-1245 worktree could not be removed by the agent (permission classifier); owner step.
- **Status:** in_progress — design PR #23 merged; S1, S2'a, S2'b1, S2'b2 and S2'b3 done (uncommitted);
  S2'b3 (status/patch/refresh facades), S2'b4 (Connection-native routes slot-aware), S2'c
  (PostgreSQL), S4 (dry-run/apply tool) next under sdlc-python + tortoise-dev, RED first; no
  Stage C/D/E.

### S2'b4 — the Connection-native routes over a migrated pair's effective row: DONE (uncommitted, 2026-09-22)

- **Actual files (as planned, plus one import):**
  - NEW `apps/aigateway/src/aigateway/core/provider_access/connection_native.py` (123 lines):
    `credential_name_of`, `effective_pair_of`, `retire_effective`, `republish_effective_api_key`
    (+ private `_advance`, `_superseded`).
  - MOD `apps/aigateway/src/aigateway/core/provider_access/connection_admin.py` — `_mirror` →
    `api_key_mirror` (exported; the op 8 call site renamed). Nothing else.
  - MOD `apps/aigateway/src/aigateway/core/provider_access/__init__.py` — the four new names.
  - MOD `apps/aigateway/src/aigateway/routes/oauth_connections.py` (567 lines) — `refresh_connection`
    builds the shared cached strategy with `credential_strategy_for_connection` under the
    locator-derived name; `set_connection_api_key` derives its strategy name from the locator,
    evicts under it, and its publication boundary moved verbatim into `_replace_api_key`
    (marker/index via `republish_effective_api_key` → `reactivate` → blob) wrapped in
    `refusals_as_http()`; `delete_connection` likewise into `_delete_connection`
    (`retire_effective` → `mark_revoked` → blob) and evicts under the locator name. Imports:
    `OAuthConnection`, the three helpers, `credential_strategy_for_connection`, `refusals_as_http`.
  - MOD `apps/aigateway/src/aigateway/core/oauth/token_service.py` — the credential name comes
    from the row's locator (`getattr(connection, "credential_locator", None)` keeps the service's
    duck-typed fakes on the UUID name); new core→core import of `connection_locator` (the
    import-boundary suite stays green).
  - NEW `apps/aigateway/tests/unit/core/provider_access/test_connection_backed_native_routes.py`
    (449 lines, 17 tests) — explicit api-key validation double (`_AcceptingValidation`) as the
    unit conftest asks of non-frozen modules.
  - No schema change → no migration (S1 rule satisfied by construction).
- **RED evidence (2026-09-22):** first run 9 failed / 3 passed; four PUT tests failed for the
  WRONG reason (`422 api_key_invalid`: the unit conftest grants the compat validation success only
  to frozen modules) → explicit double installed → 8 failed / 4 passed for the RIGHT reasons:
  refresh/token `401 auth_required "No tokens for anthropic profile '<account>:<uuid>'"` (the
  UUID address), the new key written to the UUID blob while the Profile blob kept the old key,
  marker `('migrated', <effective>, 1)` unchanged after DELETE, `204`/`200` where a lost fence
  must answer `409`, eviction under the UUID name. The four guard tests (stray-row delete, label
  patch, second-Connection start, stray-row key replacement) passed before and after.
- **GREEN:** 12 → coverage pass +5 (token refresh window success/failure over the locator blob,
  documentless-pair delete, document vanished during key replacement → 409 with the marker
  rolled back, legacy op 8 starts over after a native delete) = 17 passed. Prior Connection-native
  suites (8 modules) 89 passed UNMODIFIED; `tests/unit/core/provider_access` + S1–S2'b3 route
  suites 562 passed.
- **Gates:** first `run_gates.py aigateway` run FAILED on one E501 (a 102-char test docstring;
  attempt 1 of 10) → rewrapped → `uv run .claude/scripts/run_gates.py aigateway` ALL GATES GREEN (append-only ✓ ruff check ✓
  ruff format --check ✓ pyright ✓ check_no_enterprise ✓ pytest --cov ✓; attempt 2 of 10, 2026-09-22).
  Full `uv run pytest -m "not live" -q` on the final tree: 4853 passed, 42 skipped, 37 deselected in
  134s (2026-09-22; +17 = the new suite).
  pyright 0 errors on the changed files; no `# type: ignore`, no bare `except`, no logger in the
  new module.
- **Decisions applied:** D-S2b4-1..6 as planned. Clarifications made while coding: the route
  needs `OAuthConnection` only as a return annotation of the two extracted helpers;
  `credential_strategy_for_connection` is imported from its module (the package does not export
  it — unchanged from S1); the second-Connection characterisation asserts
  `{"default", "second"}` labels + marker `(1, effective)`.
- **Deviation (f), flagged for the owner:** per the card the native refresh/token paths mark the
  ROW only — the compat document is not rewritten (no ERROR mirror, no `last_refreshed_at`),
  whereas S2'b3's Profile-facade refresh mirrors both. Visible effect: after a native refresh the
  legacy `GET …/status` still shows the document's `last_refreshed_at`. Candidate fix (not this
  slice): `legacy_view` renders `last_refreshed_at` from the Connection.
- **Owner decision pending (D-S2b4-6):** a second Connection on a migrated provider keeps
  today's behaviour (a stray, never-effective row; marker untouched) — pinned by
  `test_starting_a_second_connection_on_a_migrated_provider_moves_no_marker`. Options remain
  (i) refuse `409 connection_conflict`, (ii) keep as is, (iii) treat as the pair's in-place
  re-auth. Nothing is guessed; no selectable multi-account was introduced.
- **Wisdom review:** simplest design that removes the defect class (derive the name from the
  locator everywhere; four small functions, no new policy); YAGNI honoured (no second-Connection
  policy, no `legacy_view` change); duplication: op 8/op 9 and the native helpers share the store
  primitives and `api_key_mirror` but keep separate bodies — their preconditions and refusal
  vocabularies differ (documented, not merged). Tests assert addresses, marker generation /
  effective id, document state, HTTP bodies and eviction names — never "it ran". Blast radius:
  native HTTP contracts unchanged for plain rows (89 prior tests unmodified), `__all__` grew,
  one new core→core import edge. Security: `raw_api_key` reaches only the strategy persist and the
  masked `account_label` (last 4), failure bodies keep the sanitized messages (SENTINEL tests),
  every lost fence fails closed (409, transaction rolled back). Card conventions: anchors present;
  `routes/oauth_connections.py` was ALREADY over the 450-line limit at HEAD (521 lines) and
  grew by delegation glue only — the new responsibility lives in `connection_native.py`; a split
  of the route module is a follow-up candidate, not done here to keep the diff reviewable.
- **Commit:** NOT made — owner authorization required (see the commit/PR shape above).

### S2'c — outcome (2026-09-22): PostgreSQL coexistence and race tests for the Connection side

- **Actual files (planned = actual):** `apps/aigateway/tests/integration/test_provider_access_backing_postgres.py`
  (NEW, 427 lines, 5 tests, `pytestmark = pytest.mark.needs_postgres`). No production code changed —
  D-S2c-3 verification tests: the first PostgreSQL run passed 5/5, so no defect surfaced.
- **Lane reuse (D-S2c-1):** the fixtures `postgres_database_url` (module scope; one `postgres:16-alpine`
  container migrated to head by the `tortoise` CLI subprocess) and `pg_client` are BOUND from
  `tests/integration/test_lifecycle_postgres_races.py` (`import test_lifecycle_postgres_races as lane;
  postgres_database_url = lane.postgres_database_url`) — pytest registers any fixture found in the module
  namespace, the prior module is not modified, and no own `testcontainers` import is needed (so no
  `# type: ignore`).
- **Seeding helper:** `_reset_pair` (the lane shares ONE admin account, so each test first deletes that
  account's anthropic marker row, Connections and documents) + `_seed_migrated_pair` (Profile blob at
  `credential_service_for(credential_name_for(account, name))`, AUTHENTICATED document,
  `create_pending(..., credential_locator=credential_locator_for("anthropic", account, name))` →
  `complete` → optional `set_auth_type("api_key")` → `PairAuthorityStore.advance(migrated, effective=id)`),
  both executed through `client.portal.call`.
- **Race technique (D-S2c-2):** `_MarkerHold` monkeypatches `PairAuthorityStore.advance` at CLASS level
  (every production site constructs a fresh store or binds an instance) with a wrapper that performs the
  REAL advance for the call the `holds` predicate names, sets `held`, then waits inside the still-open
  transaction — the marker row stays locked — while the other writer sets `attempted` before its own
  advance blocks on that row; `release` → the holder commits → the blocked
  `UPDATE … WHERE generation = <stale>` matches 0 rows → `PairAuthorityConflict` → 409 `connection_conflict`.
- **Tests (5):**
  1. `test_pair_marker_compare_and_set_is_fenced_on_postgres` — `advance(expected=0)` creates gen 1; a
     second creator at expected 0 → `PairAuthorityConflict` (unique pair; the aborted transaction rolls
     back); a stale `expected=5` → conflict; `expected=1` → gen 2 with the note cleared.
  2. `test_a_migrated_pair_reads_through_its_locator_on_postgres` — the JSONB locator comes back as a
     mapping whose service ends in `:<account>:<name>`; the legacy status renders authenticated/oauth
     from the Connection; native `GET /v1/oauth/connections/{id}/token` serves the Profile blob's token.
  3. `test_native_delete_holding_the_marker_makes_the_legacy_key_route_lose_on_postgres` — scenario (a):
     DELETE 204, legacy op 8 PUT 409 `connection_conflict`; final marker (migrated, None, 2), row revoked,
     no document, no blob; the retried op 8 starts over (gen 3, a NEW effective id, blob = the key).
  4. `test_legacy_key_route_holding_the_marker_makes_the_native_delete_lose_on_postgres` — scenario (b):
     PUT 200, native DELETE 409; row active/api_key, gen 2 with the same effective id, blob = the key,
     document api_key; the retried DELETE 204 → gen 3, row revoked, no blob, no document.
  5. `test_oauth_callback_holding_the_marker_makes_the_native_key_route_lose_on_postgres` — scenario (c):
     an api_key-migrated pair, legacy OAuth start (the S2'b2 in-place re-auth advances the marker at
     start), the callback holds after ITS advance (the first advance once the hold is installed), the
     native PUT api-key on the effective row reads the committed generation and blocks → callback 200,
     PUT 409; row active/oauth, marker gen = start + 1 with the same effective id, the blob holds the
     OAuth tokens and never the replacement key, document oauth.
- **Evidence:** default lane (no `AIGW_TEST_PG`):
  `uv run pytest tests/integration/test_provider_access_backing_postgres.py -q` → 5 skipped in 2.24s.
  PostgreSQL lane: `AIGW_TEST_PG=1 uv run pytest tests/integration/test_provider_access_backing_postgres.py -q`
  → 5 passed in 4.31s (first run; Docker 29.6.1, `postgres:16-alpine`). Both PostgreSQL modules together:
  `AIGW_TEST_PG=1 uv run pytest tests/integration/test_lifecycle_postgres_races.py tests/integration/test_provider_access_backing_postgres.py -q`
  → 11 passed in 7.10s (two containers, one per module). File-level `uv run ruff check`, `uv run ruff
  format --check` and `uv run pyright` on the new module: clean.
- **No deadlock by construction:** all three writer pairs take the marker row FIRST (marker → index →
  connection row → blob), so the loser blocks on the marker before it touches any other row — which is
  exactly why the D14 lock order is a single order and not "whatever the route reaches first".
- **Not covered here (deliberate):** the create race of the FIRST marker (two writers at gen 0 on one
  pair) belongs to S4's apply path and is tested in S4's PostgreSQL lane; the legacy-only PostgreSQL
  races stay in the prior module unchanged.
- **Gates:** `uv run .claude/scripts/run_gates.py aigateway` (worktree root) ALL GATES GREEN — append-only
  test check (vs HEAD) ✓, `uv run ruff check` ✓, `uv run ruff format --check` ✓, `uv run pyright` ✓,
  `uv run python scripts/check_no_enterprise.py` ✓, `uv run pytest --cov=aigateway --cov-fail-under=80 -q` ✓
  (attempt 1 of 10, 2026-09-22; the new module is skipped in that lane, as intended — it runs under
  `AIGW_TEST_PG=1`, see Evidence above). Prompt gate "SQLite and PostgreSQL migration/coexistence tests":
  SQLite is covered by the S1–S2'b4 unit suites (the `authenticated_client` app on SQLite), PostgreSQL by
  this module plus the S1 migration smoke; the PostgreSQL lane IS locally feasible (Docker), so no CI-only
  waiver is claimed.
- **Wisdom review:** no production code touched; the tests assert final rows, marker generations, blob
  contents and HTTP bodies, not "it ran"; secrets never appear in assertions beyond the fixed test key;
  the prior PostgreSQL module is imported, not edited (append-only ✓); 427 lines ≤ 450.
- **Commit:** NOT made — owner authorization required (see the commit/PR shape above).

### S4 — the secret-aware backfill tool (`python -m aigateway.migrate_profiles`): DONE (uncommitted, 2026-09-22)

- **Actual files vs planned:**
  - `apps/aigateway/src/aigateway/core/provider_access/backfill_classify.py` (253 lines): `Disposition`, `Action`,
    `BackfillContext` (`from_app`, plus `from_stores(credential_store, providers)` — see D-S4-10), `PairPlan`,
    `classify_account`. `classify_pair` was NOT implemented (a per-pair answer is a filter over
    `classify_account`; YAGNI).
  - `apps/aigateway/src/aigateway/core/provider_access/backfill_apply.py` (270): `Mode`/`MODES`, `PairRecord`,
    `AccountResult`, `BackfillReport` (`counts()`, `to_dict()` — the CLI prints `json.dumps(..., indent=2,
    sort_keys=True)`; the planned `to_json` name became `to_dict`), `all_account_ids`, `run_backfill`,
    `plan_account`, `apply_account`, `rollback_account`.
  - `apps/aigateway/src/aigateway/migrate_profiles.py` (138): `parse_args` (exclusive modes
    `--dry-run|--apply|--rollback`, exclusive scope `--account <id>|--all`, optional `--journal PATH`), `run`,
    `main` (exit 0 ok, 2 usage/refused, 3 conflicts → retry), `__main__` guard.
  - `apps/aigateway/src/aigateway/core/provider_access/__init__.py`: exports `BackfillContext`, `BackfillReport`,
    `PairPlan`, `all_account_ids`, `classify_account`, `run_backfill`.
  - Tests (NEW): `tests/unit/core/provider_access/backfill_probes.py` (223, helpers),
    `test_backfill_classify.py` (257; 27 tests), `test_backfill_apply.py` (336; 13),
    `tests/unit/test_migrate_profiles_cli.py` (214; 11, incl. a real `python -m` subprocess dry run),
    `tests/integration/test_provider_access_backfill_postgres.py` (176; 2, `needs_postgres`, fixtures bound from
    the S2'c module) — 53 new tests. No prior test modified.
  - No schema change, no migration (S1 satisfied trivially).
- **Decisions added during implementation (beyond D-S4-1..8):**
  - **D-S4-9 — master key refusal.** With `AIGATEWAY_SECRET_PROVIDER=local`, no `AIGATEWAY_SECRET_KEY` and no
    persisted `secret_master_keys` row, the CLI exits 2 with `refused: …` on stderr BEFORE opening a secret
    store: `get_or_create_master_key` would otherwise MINT and persist a key — a write during a dry run, and a
    key nobody holds (every existing blob would then read as undecodable). Test asserts the table stays empty.
  - **D-S4-10 — the CLI reaches the legacy index only through the port package.** The first CLI draft imported
    `ProfileIndexStore` directly and the A2 import-boundary test
    (`test_no_module_outside_the_documented_owners_imports_a_legacy_profile_row`, PR #981) went RED — correctly.
    Fixed by design, not exemption: `BackfillContext.from_stores` constructs the index store inside
    `core/provider_access` (an owner); the prior test is untouched and green.
  - **D-S4-11 — no `--dry-run --rollback` combination.** `--dry-run` reports `alias_documents` for every
    `already_migrated` pair, which is the information a rollback decision needs; the argparse mode group keeps
    the three modes exclusive (the plan text above implied the combination — superseded).
  - **D-S4-12 — `--all` enumerates `Account` rows.** Legacy-index documents whose account has no row are out of
    scope (unreachable through the app anyway); recorded, not solved.
- **Evidence RED→GREEN:** RED = `ModuleNotFoundError` at collection for the three new unit modules (the production
  modules did not exist), then the `from_stores` test failed with `AttributeError` before the factory existed.
  GREEN: classify 27 + apply 13 = 40; CLI 11; PostgreSQL 2. The PostgreSQL apply test failed ONCE on its first
  run because the hand-rolled seed blob lacked `expires_at_ms` (the token route refuses such a blob) — a test
  seeding defect, fixed by reusing the S2'c `_oauth_blob` helper; no production change.
  - `uv run pytest tests/unit/core/provider_access tests/unit/test_oauth_connections_routes.py tests/unit/test_migrate_profiles_cli.py -q -p no:cacheprovider`
    → 470 passed (before D-S4-10: 1 failed / 469 passed — the A2 boundary test named above).
  - `AIGW_TEST_PG=1 uv run pytest tests/integration/test_provider_access_backfill_postgres.py -q -p no:cacheprovider`
    → 2 passed in 4.44s; all three PostgreSQL modules together (`test_lifecycle_postgres_races.py`,
    `test_provider_access_backing_postgres.py`, `test_provider_access_backfill_postgres.py`) → 13 passed in 9.21s
    (Docker 29.6.1, `postgres:16-alpine`).
  - `uv run pyright` on every new module → 0 errors; `uv run ruff check` / `uv run ruff format --check` clean.
- **PostgreSQL FIRST-marker race (the case S2'c deferred here):** two `apply_account` runs on one Profile-only
  pair. The first performs its real `advance` (Connection row + marker inserted, uncommitted) and holds; the
  second classifies with no marker visible (READ COMMITTED), reaches `create_pending` and blocks on the
  `(account_id, provider, label)` unique index; release → the first commits → the second's INSERT raises
  `IntegrityError` → its whole account transaction rolls back → `conflict=True`, `applied=False`; exactly one
  Connection, marker generation 1; the re-run classifies the pair `already_migrated` and writes nothing.
- **Dry-run leak scan caveat (operator note):** the ORM's `tortoise.db_client` / `aiosqlite` DEBUG channel echoes
  SQL parameters (blob addresses, account ids, document names) for every query — a deployment logging property,
  not a tool write. The test scopes its scan to the `aigateway` logger tree; the tool itself logs nothing. Run
  the tool with the ORM loggers at INFO or above.
- **Not offered / to report:** no owner-mapping flag (stop-and-ask territory — the quarantine report is the
  owner's input); `classify_pair` not implemented; `to_json` → `to_dict`; no `--dry-run --rollback`; the
  master-key refusal (D-S4-9); the `--rollback` mechanism choice (D-S4-7); legacy-index orphans (D-S4-12).
- **Docs on branch:** `docs/spec/2026-09-09-OME-1138-converge-connections.md` §8 rows D11, D14, D16 marked
  decided (owner, 2026-09-22; design PR #23) and D12 given its decided Stage B rule (itself still open for
  Stage D); the intro sentence (D11 "open") and the register preamble aligned. 8 insertions / 7 deletions.
- **Gates:** `uv run .claude/scripts/run_gates.py aigateway` (worktree root) ALL GATES GREEN — append-only test
  check (vs HEAD) ✓, `uv run ruff check` ✓, `uv run ruff format --check` ✓, `uv run pyright` ✓,
  `uv run python scripts/check_no_enterprise.py` ✓, `uv run pytest --cov=aigateway --cov-fail-under=80 -q` ✓
  (attempt 1 of 10, 2026-09-22 — the A2 boundary failure of D-S4-10 surfaced in a focused run BEFORE the gate
  runner and was fixed first). Prompt gates "SQLite and PostgreSQL migration/coexistence tests", "Dry-run writes
  nothing and leaks no secrets" and "Apply path is idempotent and crash/retry safe": each has a named test above
  (SQLite: `test_backfill_apply.py`; PostgreSQL: `test_provider_access_backfill_postgres.py`; the PostgreSQL lane
  IS locally feasible, so no CI-only waiver is claimed). Full suite, the prompt's own command:
  `uv run pytest -m "not live" -q` → 4904 passed, 49 skipped, 37 deselected in 158.58s (exit 0; the S2'b4
  baseline was 4853 / 42 — the difference is the 51 new SQLite-lane tests plus the 7 PostgreSQL-lane tests of
  S2'c and S4 that skip without `AIGW_TEST_PG`).
- **Wisdom review:** the tool writes only `migrated`/`quarantined` marker rows and, for `profile_only`, ONE
  Connection at the Profile's own blob address — it never decrypts a credential for transfer, never calls a
  provider, never deletes, never mints a master key (D-S4-9); every conflict path is a whole-account rollback and
  a report line, never a guess (D3); the report and journal carry opaque identifiers only (D-S4-6, asserted by the
  needle scan); tests assert rows, marker generations, blob bytes, HTTP bodies and exit codes, not "it ran"; the
  A2 import boundary held and shaped the CLI (D-S4-10); no `# type: ignore`; specific exceptions only
  (`PairAuthorityConflict`, `IntegrityError`, `SecretDecryptionError`, `json.JSONDecodeError`); all new files
  ≤ 336 lines; prior tests untouched (append-only ✓ in the gate runner). Blast radius: one new CLI entry point,
  one package export set; no public HTTP contract or schema touched. Speculative generality avoided:
  `classify_pair`, an owner-mapping flag and a `--dry-run --rollback` combo were all left out.
- **Commit:** NOT made — owner authorization required (see the commit/PR shape above; never stage `.codegraph/`,
  Markdown paths only with exact-path approval).

### R1 — PR #1029 review fixes (planned 2026-09-23, before RED)

**Intent.** Three review findings on PR #1029, each confirmed by a code path (none yet reproduced by a test):
1. **High — native delete destroys a shared blob.** `DELETE /v1/oauth/connections/{id}` deletes the blob at the
   row's locator with no owner check. Since Stage B several rows can address ONE Profile blob (a superseded
   `error` row beside the fresh row a re-auth opened; the backfill's row beside the legacy Profile after an R1
   rollback), deleting a non-effective or rolled-back row destroys a credential another owner serves.
2. **Medium — api_key → OAuth under one name regresses on a migrated pair.** `begin_connection_oauth` opens a
   fresh pending row labelled with the requested name while the superseded `error` row still holds that label
   (`mark_error` keeps an api_key row's label, SF-291 RF2-1; the backfill labels its row with the Profile name)
   → `IntegrityError` → 409 `profile_auth_conflict`. The legacy path allows the switch (SF-244).
3. **Medium/low — op 8 reuse leaves the key's own document saying `oauth`.** Reusing the effective row writes the
   key at the row's locator but mirrors only the requested name's document; after an R1 rollback the document at
   the key's address (e.g. `default`) still says `oauth`, so the legacy path is incoherent.

**Decisions.**
- **D-R1-1 (finding 2).** At start, a non-reusable, non-revoked effective row (status `error`) is REVOKED in the
  same transaction, BEFORE `create_pending`: the label is freed, the zombie leaves listings, its blob is untouched
  (the new row addresses the same Profile blob and the callback overwrites it, exactly as before). "An error row
  is never revived" holds — it is retired, not revived. The marker fence still protects: a concurrent in-place
  re-key advances the marker → our advance conflicts → the whole transaction, revoke included, rolls back.
- **D-R1-2 (finding 1).** `_delete_connection` keeps the blob when another owner addresses the locator: (i) any
  other non-revoked row of the account+provider with an equal locator; (ii) when the pair is NOT `migrated`
  (`none`/`quarantined` — the legacy Profile owns it), a legacy document whose Profile address equals the
  locator. Helper `credential_has_other_owner(app, connection)` in `connection_native.py`. The row is still
  revoked and the cache evicted. A blob is deleted when its LAST live addresser goes — conservative (D11): never
  destroy what another live row addresses; a blob lingering behind a zombie `error` row (pre-fix data) goes when
  that row is deleted.
- **D-R1-3 (finding 3).** Op 8 on a migrated pair mirrors EVERY document of the pair as api_key
  (`require_present`), not only the requested name — the rule `republish_effective_api_key` already applies on
  the native key route (S2'b4); the document at the key's address is then rollback-coherent. Alias documents
  (address ≠ effective locator) stay rollback-fragile BY DESIGN of one-credential-per-pair and are reported by
  `migrate_profiles --dry-run` (`alias_documents`). The committed test
  `test_an_alias_name_writes_the_pairs_single_credential` pins today's alias contract, so REFUSING alias names
  (the reviewer's alternative) is a contract change needing owner approval → surfaced, not done here.
- No schema change (S1 trivially satisfied).

**Planned files.** `core/provider_access/connection_oauth.py` (revoke the superseded error row),
`core/provider_access/connection_native.py` (+ `credential_has_other_owner`), `routes/oauth_connections.py`
(`_delete_connection` guard), `core/provider_access/connection_admin.py` (sibling mirrors). Tests: NEW module
`tests/unit/core/provider_access/test_connection_backed_shared_addresses.py` (the native-routes module is at
449 lines; the new tests share one subject — several addressers of one blob).

**Test plan (RED first).** (a) api_key migrated pair in `error` → legacy OAuth start 201, new pending row
labelled `default`, old row revoked, callback publishes, the pair authenticates; (b) oauth errored effective →
start revokes it, one live row remains; (c) delete a non-effective sibling at the effective's address → 204, blob
kept, the effective still serves its token, marker unchanged; then deleting the effective (last addresser)
deletes the blob; (d) rolled-back pair: delete the leftover Connection → 204, the legacy Profile's blob kept,
legacy status authenticated, legacy resolve serves; (e) alias key write mirrors `default` as api_key; after a
marker reset the legacy status of `default` reads api_key/authenticated.

**Acceptance.** New tests green; every prior test unmodified and green; `run_gates.py aigateway` ALL GREEN;
ledger outcome; PR replies drafted; NO commit/push without authorization.

### R1 — PR #1029 review fixes: DONE (uncommitted on top of `2c39a949`, 2026-09-23)

- **Actual files (4 production + 1 new test module, no schema change):**
  - `core/provider_access/connection_oauth.py` (301 lines): in `begin_connection_oauth`, when no row is
    reusable and the effective row is not already revoked, `mark_revoked(current, f"superseded:{fresh}")`
    runs INSIDE the flow transaction before `create_pending(connection_id=fresh)`. The module INVARIANT
    now states the retirement.
  - `core/provider_access/connection_native.py` (155): new `credential_has_other_owner(app, connection)`.
  - `routes/oauth_connections.py` (572, pre-existing oversize; only a call site was added, the new
    responsibility lives in `connection_native.py`): `_delete_connection` computes `keep_blob` after
    `retire_effective` and skips `_delete_credentials` when another owner addresses the locator.
  - `core/provider_access/connection_admin.py` (342): `_mirror_siblings` mirrors EVERY other document of
    a migrated pair as `api_key` inside op 8's transaction — the rule `republish_effective_api_key`
    already applied on the native key route.
  - `core/provider_access/__init__.py`: exports `credential_has_other_owner` (the route imports from the
    package, so the first GREEN run failed at app construction until the export was added).
  - `tests/unit/core/provider_access/test_connection_backed_shared_addresses.py` (NEW, 195 lines, 5 tests).
- **RED → GREEN.** RED: all 5 new tests failed for the right reasons —
  (1) legacy OAuth start on a migrated api_key pair in `error` answered **409 `connection_conflict`**
  (not `profile_auth_conflict` as the review predicted: the `IntegrityError` becomes
  `WriteConflict(superseded, subject="connection")` and `provider_access_http._write_conflict` maps that
  subject to `connection_conflict`; the mechanism the reviewer described is exactly right, the surfaced
  code differs); (2) the superseded row stayed `error` instead of `revoked`; (3) and (4) the blob was
  `None` after deleting a non-effective sibling / a rolled-back Connection — the reported data loss,
  reproduced; (5) the document at the key's address still read `oauth`. GREEN: 5 passed.
- **Evidence.**
  - `uv run pytest tests/unit/core/provider_access tests/unit/test_oauth_connections_routes.py
    tests/unit/test_auth_routes.py tests/unit/test_api_key_routes.py -q -p no:cacheprovider` → **595 passed**
    (every prior test unmodified).
  - `uv run .claude/scripts/run_gates.py aigateway` (worktree root) → **ALL GATES GREEN**, exit 0, attempt 1
    of 10: append-only test check ✓, ruff check ✓, ruff format --check ✓, pyright ✓, check_no_enterprise ✓,
    `pytest --cov=aigateway --cov-fail-under=80 -q` ✓.
  - `AIGW_TEST_PG=1 uv run pytest tests/integration/test_lifecycle_postgres_races.py
    tests/integration/test_provider_access_backing_postgres.py
    tests/integration/test_provider_access_backfill_postgres.py -q` → **13 passed**, exit 0.
- **Wisdom review.** The three fixes are subtractive, not new policy: one revoke of a row that was already
  superseded, one guard before an existing delete, one loop that applies an existing rule to the sibling
  documents. No new module, no new HTTP shape, no schema change, no `# type: ignore`, no secret in a log or
  message (`superseded:<uuid>` is opaque). Blast radius: `DELETE /v1/oauth/connections/{id}` now keeps a
  blob it used to delete — strictly less destructive; `POST /v1/auth/{p}/profiles` revokes a row that was
  already unusable; op 8 writes sibling documents it used to leave stale. Every affected prior test stayed
  green, including the delete tests that assert the blob IS removed when the effective row is the last
  addresser. Files: 155/301/342 ≤ 450; the route module stays at its pre-existing 572 (split still a
  follow-up candidate).
- **Deliberately NOT done (owner decision).** The reviewer's alternative for finding 3 — refuse a
  `legacy_name` that does not match the effective row's locator — is a contract change: the committed test
  `test_an_alias_name_writes_the_pairs_single_credential` pins today's behaviour (an alias name writes the
  pair's single credential). Alias documents stay rollback-fragile by design of one-credential-per-pair and
  are reported by `migrate_profiles --dry-run` as `alias_documents`. Surfaced, not decided here.
- **Commit:** NOT made — owner authorization required. PR replies drafted, NOT posted.
- **R1 addendum (2026-09-23) — lock-order defect in the first D-R1-1 cut, found in diff review.** The first
  cut revoked the superseded `error` row BEFORE the marker advance. Every other authority writer (native key
  replacement, native delete, op 8) takes the marker first and the row second, so the start inverted the
  D14 lock order. SQLite cannot show it; a NEW PostgreSQL test reproduced it RED —
  `asyncpg.exceptions.DeadlockDetectedError: deadlock detected` between a native `PUT …/api-key` holding the
  marker and a legacy OAuth start on the same errored row. Fix: on the retirement path the start first
  advances the marker to `migrated` with NO effective Connection (the fence — a stale start loses there,
  before touching any row), then revokes the row, creates the fresh pending row and advances again to name
  it. Cost: two generation steps on that path only; every other path is unchanged.
  - `tests/integration/test_provider_access_shared_addresses_postgres.py` (NEW, 1 test, `needs_postgres`,
    fixtures and helpers bound from the S2'c module): the key replacement answers 200, the start 409
    `connection_conflict`, the errored row is NOT retired (the loser rolled back), one live row, marker
    generation +1, the blob holds the replacement key.
  - Evidence: `AIGW_TEST_PG=1 uv run pytest` over all four PostgreSQL modules → 14 passed; the SQLite focused
    suites → 595 passed (unmodified); `connection_oauth.py` 312 lines.
  - Gates after the addendum: `uv run .claude/scripts/run_gates.py aigateway` (worktree root) — attempt 1 RED on
    pyright (the new PostgreSQL test annotated a connection id as `object`; fixed to `UUID`), attempt 2 ALL GATES
    GREEN, exit 0 (append-only ✓, ruff ✓, format ✓, pyright ✓, check_no_enterprise ✓, pytest --cov ≥ 80 ✓).
  - Commit: still NOT made; PR replies drafted, NOT posted.

### R2 — owner review of R1 (2026-09-23): concurrent delete + rollback after an alias write

Owner review of the R1 cut: finding 2 (api_key → OAuth) accepted; finding 1 (shared-blob delete) only
proven for sequential deletes; finding 3 (rollback coherence) NOT solved — mirroring `auth_type` onto sibling
documents does not put a key at a sibling document's address. Owner direction: keep the alias-write
behaviour (pinned by `test_an_alias_name_writes_the_pairs_single_credential`) and make the rollback of such a
pair an explicit, reported refusal (or a real reverse mapping); tests first.

- **R2-A — two concurrent deletes of rows sharing one blob.** Defect: the owner check read the pair's rows
  BEFORE revoking its own, without locks — two overlapping deletes each saw the other live and both kept the
  blob (orphaned credential). Fix: every deleter locks the pair's live rows in ONE ascending id order —
  `lock_lower_addressers` (rows below it) before `mark_revoked`, its own row in `mark_revoked`, the rows
  above it inside `credential_has_other_owner`, which now runs AFTER the revoke. One global order cannot
  deadlock; the later deleter waits for the earlier commit and PostgreSQL's re-check drops the revoked row.
  A first cut that locked ALL live rows (own included) before the revoke broke the prior race test
  `test_connection_absent_credential_delete_set_commit_orders_on_postgres` (the delete then waited on the
  key-set's row lock before reaching `mark_revoked`, where that test observes it); the prior test was NOT
  touched — the lock order was changed instead.
  - Test (NEW, PostgreSQL, parametrized lower-id-first / higher-id-first):
    `test_two_concurrent_deletes_of_rows_sharing_a_blob_leave_no_orphan_on_postgres` — the first delete is
    held after its owner check; the second overlaps it (reaches its check or parks on a row lock); both
    answer 204, both rows revoked, the blob is gone.
  - RED evidence: with the pre-R2 delete code temporarily restored, both parametrizations fail
    (`assert '{"auth_type": "api_key", …}' is None` — the blob survives); with the fix, green.
- **R2-B — rollback of a pair whose documents do not live at the effective row's address.** Decision
  (owner option 1): `rollback_account` does NOT reset such a pair (`alias_documents > 0`); it records
  `disposition=migrated`, `category=rollback_refused_alias_documents`, `action=skip`, `applied=false` and the
  alias count, while the account's other pairs still roll back. `migrate_profiles` gains `EXIT_REFUSED = 4`
  via `exit_code_for(report)` (conflicts still win with `EXIT_RETRY`). The pinned `counts()` dict is
  unchanged. Rejected: reverse mapping by copying the secret between addresses (decrypts for transfer).
  - Tests (NEW, SQLite): a `work` alias write → rollback refused, marker stays migrated with the same
    generation/effective row, and access THROUGH `work` (`resolve` with selector `work` and the `work`
    status) still reaches the key; a UUID-addressed Connection that gained a document → refused; a pair with
    no alias documents still resets to `none` with `EXIT_OK`.
  - RED evidence: 3 failed (two rolled back to `none`, one `AttributeError: exit_code_for`), then green.
- **Evidence (actually run, 2026-09-23):** all four PostgreSQL modules `AIGW_TEST_PG=1` → 16 passed; SQLite
  focused suites → 598 passed; `uv run .claude/scripts/run_gates.py aigateway` (worktree root) → ALL GATES
  GREEN (append-only ✓, ruff ✓, format ✓, pyright ✓, check_no_enterprise ✓, pytest --cov ≥ 80 ✓);
  `git diff --check` clean.
- **Files:** `connection_native.py` (lock helpers, post-revoke owner check), `routes/oauth_connections.py`
  (575 lines — pre-existing over-limit module, +3; split remains a follow-up), `provider_access/__init__.py`,
  `backfill_apply.py` (refusal, `ROLLBACK_REFUSED`), `migrate_profiles.py` (`EXIT_REFUSED`, `exit_code_for`),
  the two new test modules. All touched modules except the route ≤ 450 lines.
- **Residual (surfaced):** an alias pair can never be rolled back by the tool — the operator must remove or
  re-key the alias documents first. SQLite relies on its single writer for the delete serialization.
- **Commit:** NOT made; PR replies revised as drafts, NOT posted.
