---
status: accepted   # owner approval 2026-10-21, §7 Q1-Q6 as proposed; §4/§5 E5a corrected by the plan
issue: OME-1715    # E5a, the first landing; E5 is separate from OME-1209 (its spec §7 Q4)
parent: OME-1138
date: 2026-10-21
base: origin/main b0ce28150
---

# E5 — purge the retired Profile storage (Stage E history cleanup)

## 1. Purpose

Stage E of `docs/spec/2026-09-09-OME-1138-converge-connections.md` (§5 row E, §6.2 "History",
D6) ended Profile authority in `OME-1209`: since E4a no runtime path reads a Profile document,
since E4b none writes one, and since E4c no plugin hook carries the Profile name. The storage that
authority used is still in `credential_blobs`: the per-account Profile index documents and the
credential blobs no Connection addresses. `OME-1209` deliberately deleted nothing (its R5) so that
a rollback to a pre-E4 build stayed safe.

E5 deletes that history, then the code that only existed to read it. The governing rule, from the
epic spec §6.2 and the Stage E spec R5 and §7 Q4: the reference check and the deletion share one
atomic boundary that also fences concurrent reference creation, with a fixture where a migrated
Connection still uses a legacy-addressed blob.

## 2. Verified as-is at b0ce28150

### 2.1 What `credential_blobs` holds

| Rows | `service` / `account` | Source | E5 |
|---|---|---|---|
| Profile index documents | `aigateway:index` / `account:<account_id>`, plus one legacy global row `default` from before the per-account split | `core/profile_index.py:14-16` | delete all |
| Provider credentials | `aigateway:<credential provider>:<account_id>:<suffix>` / the strategy's account (`default`, or a configured one: Anthropic `keychain_account`, `plugins/anthropic_provider/settings.py:84`) | each plugin's `credential_service_for`; `core/oauth/store.py:17-31` | delete those no Connection addresses |
| JWT signing secret | `aigateway:jwt-secret` | `core/auth/jwt_secret.py:10` | never touched |

There are no tombstone rows: a removed Profile left nothing behind in `credential_blobs` but its
blob. The in-memory pending-flow table names a Connection, never a blob.

The provider-credential `<suffix>` has two shapes, and the shape alone does not say who owns it:

- `<account_id>:<name>`: a Profile's blob, and also a row the D18 PUT mints on an empty pair, which
  takes the `default` name's Profile address (`DEFAULT_LEGACY_NAME`,
  `core/provider_access/profile_admin.py:28`; `pair_admin_writes.py:103`;
  `connection_admin.py:64-68`). A migrated Connection keeps reading the blob its Profile already
  addressed ("reads without re-entry", `connection_locator.py` module docstring).
- `<account_id>:<connection uuid>`: a Connection created natively.

Every plugin strategy reads and writes exactly one blob, at its `(credential_service(),
credential_account())` (`core/api_key_strategy.py`, `plugins/*/auth.py`). The core already
resolves a Connection's physical address through its strategy: `credential_blob_address`
(`core/provider_access/connection_locator.py:56`). The runtime ownership rule is
`credential_has_other_owner` (`connection_native.py:220`): a blob goes with its last live
addresser, and since E4b no Profile document counts as an addresser.

### 2.2 What can create a reference to an existing blob

| Path | Locator it stores | Can it name a blob E5 would delete? |
|---|---|---|
| Native API-key create, native OAuth start | `<account_id>:<new uuid>` | no |
| D18 PUT that reuses the pair's row | that row's locator | no, the blob is already addressed |
| D18 PUT on a pair with no reusable row | the `default` Profile address | **yes**: a blob left at `<account_id>:default` (for example by a `none` pair's DELETE, E4a ledger) is adopted |
| Backfill `--apply` (offline, `backfill_apply.py:240`) | the Profile document's address | **yes**, by design |
| Migration `0004_gemini_credential_locator` | rewrites stored locators | already applied |

Every one of these inserts a Connection row, which has a foreign key to `accounts`
(`oauth_connections.account_id`; the marker `provider_credential_slots.account_id` too), before it
writes the blob (the D18 PUT) or instead of writing one (the backfill). The backfill classifies a
pair outside its transaction and inserts the reference without re-reading the blob
(`backfill_apply.py:126-140`, `:223-240`), and it only migrates a pair that is not yet `migrated`
and has a Profile document whose blob no Connection addresses.

### 2.3 The lost-write hazard

`ORMStore.write` (`core/credential_blob/store.py:75-101`) reads the row, then `UPDATE`s it by id.
If a delete commits between the two, the `UPDATE` matches no row and `write` returns without an
error: the D18 PUT answers success and the key it was given is gone. An exact reference check
followed by a delete is therefore not safe on its own; the deletion must hold a lock every
reference creator also needs.

### 2.4 Code that waits for E5

From the E4b ledger (owner decision 2026-10-21) and the Stage E plan:

- `core/profile_index.py` (`ProfileIndexStore`, `lock_account_index`, `stamp_refreshed` with its
  PENDING branch) and `core/profile_models.py` (`Profile`, `ProfileIndex`, `ProfileState`,
  `ProfileDefaults`). No runtime module imports them; the backfill tools do.
- The backfill tools: `core/provider_access/backfill_classify.py`, `backfill_apply.py`,
  `migrate_profiles.py` (dry-run, apply, and the R1 `--rollback`, which needs the documents).
- `credential_names.profile_id_for` (no caller in `src`; three PostgreSQL tests seed with it).
- `ProfileBackedCredentialAdmin` (`profile_admin.py:53`), now only the base of
  `ConnectionBackedCredentialAdmin` (`connection_admin.py:36`).
- The dead conflict arms: `main._profile_index_conflict` and its handler registration
  (`main.py:290`, `:368`), the `CredentialBlobMutationConflict` arm of `chat._error_view`
  (`routes/chat.py:278-292`), the `retry_exhausted` and `profile_conflict` arms of
  `_write_conflict` and the `retry_exhausted` arm of `_successor_write_conflict`
  (`routes/provider_access_http.py:78-93`, `:237`), and `WriteConflictKind` `"retry_exhausted"`
  with `WriteSubject` `"profile"` (`core/provider_access/types.py:169-170`). Only
  `ProfileIndexStore` calls `ORMStore.mutate`, and every remaining `WriteConflict` is raised as
  `"superseded"` with `subject="connection"`, so none of them can fire at runtime.
- `DEFAULT_LEGACY_NAME` and `PairMutation.profile_names` (`pair_admin_writes.py:59-64`, consumed
  by `routes/admin_connections.py:198` to drop pending flows by name).

### 2.5 Environments (owner-reported, not re-read for this draft)

- **dev** (tracks `main`), census 2026-10-20: 26 pairs, all `migrated`; 50 credential blobs and
  24 Profile index blobs (census wording). The Stage B backfill pointed each migrated Connection
  at its Profile's blob; how many still do is what the dry run reports.
- **stage**, census 2026-10-20: no credential of any kind; its build predates E3.
- **prod**: a copy of dev taken after the migration (owner, 2026-10-05); not read for this spec.

## 3. Contract

- **C1 — what goes.** Every `aigateway:index` row; every provider-credential blob that no
  Connection row of any status addresses, with the address resolved through the Connection's
  strategy (`credential_blob_address`), never assembled from a string; every provider-credential
  blob of an account that no longer exists.
- **C2 — what never goes.** A blob any Connection row addresses, including a migrated Connection
  that reads a legacy-addressed blob, a `revoked` row (Q3), and a `pending` row whose OAuth flow
  has not called back yet (the row names its blob before the callback writes it);
  `aigateway:jwt-secret`; any row outside a loaded provider's credential namespace.
- **C3 — one fence per account.** One transaction per account: first `SELECT … FOR UPDATE` on the
  `accounts` row; then the refusals of C4; then read every Connection row of the account and
  resolve its address; then lock the candidate blob rows `FOR UPDATE` and delete those no address
  names, and the account's index row; commit. PostgreSQL takes `FOR KEY SHARE` on the parent row
  for every insert that references it, and that conflicts with `FOR UPDATE`. So a reference
  creator that inserted first holds the purge until it commits, and the purge then sees its row;
  one that comes later waits until the purge commits, and then writes its blob into a fresh row.
  The legacy global index row goes last, once every account it lists is done.
- **C4 — fail closed.** An account is skipped with a reason, never partly purged, when it has a
  `quarantined` marker, a Connection whose address cannot be resolved (plugin not loaded,
  malformed locator), or a Profile document naming a blob that no Connection addresses on a pair
  that is not `migrated` (Q4). The last rule also closes the backfill's gap (§2.2): the backfill
  only migrates such a pair, so a concurrent backfill and purge never target the same blob. There
  is deliberately no flag to override it.
- **C5 — an owner action, dry run first.** A command line like the backfill's:
  `python -m aigateway.purge_profile_history --dry-run|--apply --account <id>|--all [--journal PATH]`.
  It installs the encryption-at-rest provider the same way, never decrypts a value it does not need
  (the purge reads no secret), is never a Helm hook, and reports counts per kind (index row,
  name-shaped blob, uuid-shaped blob, deleted-account blob, skipped account and reason). The report
  and journal carry account ids and counts only, never a service string, credential name, value or
  ciphertext. A second `--apply` reports zero.
- **C6 — the rollback floor moves.** After `--apply` in an environment, no build older than E4b may
  run there: a pre-E4a build reads documents that are gone, and a pre-E4b build writes documents
  again. The owner takes a database backup before `--apply`; it is the only way back for the data.
- **C7 — SQLite.** SQLite has no row locks. On a SQLite database (local, single worker) the purge
  runs with the gateway stopped; the C3 fence is a PostgreSQL guarantee (Q6).

## 4. Landings

| Landing | Change | Data change | Precondition |
|---|---|---|---|
| E5a | Trim the race at its source: a D18 PUT on a pair with no reusable row mints `<account_id>:<uuid>` like the native create, instead of the `default` Profile address; with it `DEFAULT_LEGACY_NAME` and `PairMutation.profile_names` go. Collapse `ProfileBackedCredentialAdmin` into `ConnectionBackedCredentialAdmin` and delete `profile_admin.py`. Delete the dead conflict arms of §2.4. | none | none |
| E5b | The purge command of C1–C7 (dry run and apply). | none on merge | E5a merged |
| — | Owner runs `--dry-run`, reviews, takes a backup, runs `--apply`, per environment | yes | E5a or later on every replica of that environment; 0 `quarantined` markers |
| E5c | Remove the Profile vocabulary: `profile_index.py`, `profile_models.py`, the backfill tools and `migrate_profiles.py`, `profile_id_for`, the tests that seed Profile documents (approval manifest), and the purge command (Q5). | none | the purge applied in dev, stage and prod |

Each landing is its own PR and leaf under `OME-1138`. After E5a no runtime path creates a
reference to a blob it did not just address; the C3 fence stays for the offline backfill and as a
guard should an older replica still run. The apply precondition is E5a, not E4c: an older
replica's PUT on a deleted account could adopt a leftover blob at the `default` address, and a
deleted account has no row for the C3 lock.

Like a native repair (Stage E spec §7 Q7), a pair a PUT minted after E5a has its effective row at
its own address; beside a leftover document, the R1 rollback tool refuses that pair loudly
(`rollback_refused_alias_documents`).

## 5. Tests (per landing, written first)

- **E5a.** A D18 PUT on an empty pair, and beside a leftover `default` blob, stores the key at a
  uuid address and leaves the leftover blob untouched. Every route that rendered a dead conflict
  arm keeps its live arms; a guard that nothing outside `profile_index` calls `ORMStore.mutate`.
  The change moves 21 prior tests in 11 files (the address a minted key lands at,
  `profile_names`, the dead arms): the E5a test map, approved as a manifest before any edit.
- **E5b, SQLite (classification).** Index rows go. Blobs addressed by an `active`, `error`,
  `pending` or `revoked` Connection stay. The Q4 fixture: a migrated Connection whose locator names
  its Profile's blob keeps it. An orphan name-shaped blob, an orphan uuid-shaped blob and a blob
  of a deleted account go. `aigateway:jwt-secret` stays. An account with a `quarantined` marker,
  with an unresolvable Connection, or with an unmigrated document (C4) is skipped whole. A
  configured physical account (Anthropic `keychain_account` not `default`) is resolved through
  the strategy and kept. `--dry-run` leaves every table byte-equal; `--apply` deletes exactly the
  reported set; a second `--apply` reports zero. Report and journal contain no service string.
- **E5b, PostgreSQL (the fence).** Two sessions, both commit orders, in the style of the E4b
  writer-race tests: (1) the purge holds the account lock; another session inserts a Connection
  whose locator names a candidate blob, blocks, then writes its key after the purge commits; the
  key is readable. (2) The other session inserts first and has not committed; the purge blocks on
  the account row, then sees the row and keeps the blob. In neither order is a key lost. (3) A
  backfill that classified a `none` pair before the purge and inserts its Connection after it
  still reads its key: the purge skipped that account (C4).
- **E5c.** Import guards: no module under `src/aigateway` imports `profile_index` or
  `profile_models`, and both modules are gone; the full suite stays green with the retired tests
  listed in the approval manifest.

## 6. Out of scope

Renaming the runtime error codes `profile_index_conflict` and `profile_conflict`, and their SDK and
UI decoders (Stage E R3; E5a only removes emitters that can no longer fire). Connection-side
retention: deleting `revoked` rows or the blobs they address. Rotating the master key. Any access to
stage or prod data other than the owner's. The external design catalog: if its exporter or
disappearance guard imports a retired class (epic spec §10), that change ships with E5c as one
change set.

## 7. Owner decisions (2026-10-21)

The owner accepted every proposal.

- **Q1 — the fence.** The account-row lock of C3, plus the E5a trim. Alternatives in §8.
- **Q2 — what counts as history.** Every provider-credential blob no Connection addresses, any
  shape, plus blobs of deleted accounts (C1), reported by kind. Rejected: only blobs a Profile
  document names, which misses blobs whose document a `none` pair's DELETE already removed (E4a
  ledger) and keeps the uuid-shaped orphans a failed Connection delete can leave.
- **Q3 — a `revoked` row protects its blob.** Yes. The runtime already deletes a blob with its last
  live addresser, so such blobs are rare, and deleting them is Connection retention, not Profile
  history; the dry run counts them.
- **Q4 — an unmigrated legacy credential** (a document names a blob no Connection addresses, on a
  pair not `migrated`). The account is always skipped and reported; the owner backfills it first or
  leaves it. No override flag: purging it is exactly the race with the backfill that C4 closes.
- **Q5 — the purge command retires with the Profile vocabulary in E5c.** An install that still
  holds Profile rows runs an E5b-era build first; rows it never purges are inert.
- **Q6 — SQLite.** The purge runs with the gateway stopped (C7), documented, not enforced.

## 8. Alternatives considered for the fence

- **Per-pair marker lock.** Every reference creator also touches `provider_credential_slots`, but
  an absent marker has no row to lock; locking it means inserting a `none` marker, a visible state
  change the purge should not make.
- **Fix `ORMStore.write` to detect a vanished row.** Closes §2.3 for every writer, but changes the
  encrypted store's write path under every credential and does not fence the backfill, which
  references a blob without writing it.
- **A maintenance window with every replica stopped.** Simple, but nothing in the code can verify
  it on a multi-replica deployment; kept only for SQLite (C7).
- **Only the trim (E5a), no lock.** Closes the runtime path, but not replicas still running an
  older build during a rollout, nor the offline backfill until E5c removes it.
