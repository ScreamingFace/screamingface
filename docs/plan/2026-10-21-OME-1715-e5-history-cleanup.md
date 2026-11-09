---
ticket: OME-1715  # E5a; one leaf per landing under OME-1138
parent: OME-1138
status: accepted  # owner approval 2026-10-22: one E5a PR, then the purge, as planned
created: 2026-10-21
base: origin/main b0ce28150 (E5a rebased onto ae1292505)
spec: docs/spec/2026-10-21-OME-1715-e5-history-cleanup.md
---

# E5 — purge the retired Profile storage (plan)

The contract and the owner decisions are in the spec (§3 C1-C7, §7). This plan holds the sequence,
the evidence that shaped it and the tests per landing. It decides nothing the spec does not, except
where §6 below says so.

## 1. Evidence on the base

Paths are relative to `apps/aigateway/src/aigateway` unless stated.

| Fact | Source |
| --- | --- |
| A D18 PUT on a pair with no reusable row mints its row at the `default` Profile address | `core/provider_access/connection_admin.py:64-68`; `pair_admin_writes.py:103` |
| The store already defaults a new API-key row's locator to `<account_id>:<connection id>` | `core/oauth/store.py:85` |
| `PairMutation.profile_names` only feeds the pending-flow drop, and that drop is cleanup, not correctness: a stale callback loses its pair fence | `pair_admin_writes.py:59-64`; `routes/admin_connections.py:195-199`; `core/pending_auth.py:53-57` |
| Every native OAuth flow creates its pending row before it registers the flow | `routes/oauth_connections.py:150-175` |
| `ProfileBackedCredentialAdmin` is only the base of `ConnectionBackedCredentialAdmin`; `persist_credentials_or_refuse` has one caller | `core/provider_access/profile_admin.py:53`; `connection_admin.py:36`, `:107` |
| Only `ProfileIndexStore` calls `ORMStore.mutate`, so `CredentialBlobMutationConflict` cannot reach a request | `git grep "\.mutate("` over `src` |
| All 12 `WriteConflict` raise sites pass `"superseded"` and `subject="connection"` | `git grep "WriteConflict("` over `src` |
| The UI decodes `profile_index_conflict` and `credential_write_conflict`; no OpenAPI schema names either | `apps/aigateway-ui/src/lib/aigateway/errors.ts:76-77`; OpenAPI export |
| An account without its own index row reads the legacy global row's entries for it | `core/profile_index.py:58-72` |
| The backfill CLI builds its own provider registry and stores; it has no app | `migrate_profiles.py:106-126` |
| A Connection's physical blob address comes from its strategy, which needs only `state.credential_store` and the provider's HTTP factory | `core/provider_access/connection_locator.py:56-110` |
| `credential_blobs` carries per-blob dispatch metadata (`credential_revision`, sequences, last outcome); nothing reads it for a blob no Connection addresses | `core/credential_blob/model.py:29-34` |
| Tortoise is 1.1.8 | `uv pip show tortoise-orm` in `apps/aigateway` |

## 2. Sequence

```
E5a trim + dead arms ─▶ E5b purge command ─▶ owner: dry run → backup → apply (dev, stage, prod) ─▶ E5c vocabulary
```

Each landing is one PR and one leaf under `OME-1138`. E5b starts after E5a is merged. The owner's
`--apply` in an environment needs E5a or later on every replica there (§6). E5c starts after the
owner reports the apply in every environment.

## 3. Landings

### E5a — the PUT mints a Connection address; dead conflict arms go

- `ConnectionBackedCredentialAdmin.publish_api_key` loses its `name` parameter. A new row's
  locator is `credential_locator_for(credential_provider, account_id, connection_id)`, the same
  address the store gives a native API-key row. A reused row keeps its locator, so a migrated
  Connection that reads its Profile's blob is unchanged.
- `PairMutation.profile_names`, `DEFAULT_LEGACY_NAME` and the `profile_names` parameter of
  `PendingAuthTable.pop_for_pair` go. The drop matches the captured Connection ids only.
- Collapse: `ConnectionBackedCredentialAdmin` owns `_strategy` and `_invalidate`;
  `persist_credentials_or_refuse` moves into `connection_admin.py`; `profile_admin.py` is deleted.
  The refresh-guard inventory entry is renamed to `ConnectionBackedCredentialAdmin._strategy`.
- Dead arms removed: `main._profile_index_conflict` and its registration; the
  `CredentialBlobMutationConflict` arm of `chat._error_view`; the `retry_exhausted` and
  `profile_conflict` arms of `_write_conflict`; the `retry_exhausted` arm of
  `_successor_write_conflict`, with `_INDEX_CONFLICT_MESSAGE` and `_WRITE_CONFLICT_MESSAGE`.
  `WriteConflictKind` keeps only `"superseded"` and `WriteSubject` only `"connection"`; the
  parameters stay, so no raise site changes.
- Rollback: the note "the new Connection addresses the Profile blob, so a rollback still finds
  it" (`test_connection_backed_admin.py:177`) stops holding. Beside a leftover document the R1
  tool refuses such a pair loudly (`backfill_apply.py:140-170`), as it already does for a native
  repair (Stage E spec §7 Q7).
- Prior tests: the E5a test map lists the 21 tests in 11 files the change moves (found by running
  the suite against a throwaway draft of the change, then reverting it). The owner approved it on
  2026-10-22, before any test was edited; it is pinned as the manifest
  `.claude/test-change-approvals/OME-1715.json`.

### E5b — the purge command

- `core/provider_access/history_purge.py` (classification and the per-account transaction; split
  in two like `backfill_classify`/`backfill_apply` if it passes 450 lines) and the CLI
  `purge_profile_history.py`, built like `migrate_profiles.py`: own provider registry and stores,
  the encryption-at-rest provider installed the same way, `--dry-run|--apply`,
  `--account <id>|--all`, `--journal PATH`, exit code non-zero when an account is skipped.
- Per account, in one transaction (C3): `Account.select_for_update()`; read the marker rows and the
  account's documents through `ProfileIndexStore.read(account_id)`, which falls back to the legacy
  global row as the backfill does; apply C4; read every Connection row of the account and resolve
  each through `credential_blob_address` with a minimal state (the CLI's credential store and
  registry); select the account's candidate rows (`service` under `aigateway:<cp>:<account_id>:`
  for every loaded credential provider, and the index row) `FOR UPDATE`, reading `id`, `service`
  and `account` only, never `value`; delete those no resolved address names.
- Deleted accounts: a third service segment that is a UUID with no `accounts` row. No reference
  can be created to such a blob after E5a: the PUT mints a fresh address and the backfill's
  Connection insert needs the account. Their rows go in their own step, re-checked against every
  Connection row in the same transaction.
- The legacy global index row goes last, and only when no account it lists was skipped.
- Report and journal: counts per kind (index row, name-shaped blob, uuid-shaped blob,
  deleted-account blob, kept-unrecognised row, skipped account with reason) and account ids; never
  a service string, credential name, value or ciphertext.
- To check during E5b against the installed Tortoise 1.1.8: what `select_for_update()` emits on
  SQLite (C7 assumes it is a no-op, not an error).

### Owner apply, per environment

`--dry-run --all`, review the report, back up the database, `--apply --all`, then `--dry-run --all`
again, which reports zero. The owner reports each environment; only the owner reads stage or prod
data.

### E5c — retire the Profile vocabulary

`core/profile_index.py`, `core/profile_models.py`, `core/provider_access/backfill_classify.py`,
`backfill_apply.py`, `migrate_profiles.py`, `credential_names.profile_id_for`, the purge command
(Q5), and the tests that only seed or read Profile documents (their own test map and manifest).
The import-boundary test changes from "only the offline tools import `profile_index`" to "nothing
does". If the external design catalog's exporter imports a retired class, that change ships with
E5c (spec §6).

## 4. Tests

| Landing | Mandatory cases (written first) |
| --- | --- |
| E5a | a PUT on an empty pair stores the key at `<account_id>:<row id>`, and the row's locator names it; beside a leftover blob at the `default` address, that blob is neither read nor changed nor adopted; a PUT that reuses a migrated row still writes its legacy-addressed blob; the drop ends a pending flow of the captured Connection and leaves one of another Connection; no module under `src` outside `core/profile_index.py` calls `.mutate(`; `profile_admin` is gone; the conflict renderers produce only their live bodies; PostgreSQL lane green for the pair-mutation suites |
| E5b, SQLite | index rows go; blobs of `active`, `error`, `pending` and `revoked` rows stay; the migrated-Connection-on-a-legacy-blob fixture keeps its blob; orphan name-shaped, orphan uuid-shaped and deleted-account blobs go; `aigateway:jwt-secret` and unrecognised rows stay; a `quarantined` marker, an unresolvable Connection, or an unmigrated document (per-account row or legacy global row) skips the account whole; a configured physical account (Anthropic `keychain_account`) resolves through the strategy and stays; the global row stays while a listed account is skipped; `--dry-run` leaves every table byte-equal; `--apply` deletes exactly the reported set; a second `--apply` reports zero; report and journal contain no service string |
| E5b, PostgreSQL | two sessions, both commit orders: (1) the purge holds the account lock, the other session inserts a Connection naming a candidate blob, blocks, then writes its key after the purge commits, and the key reads back; (2) the other session inserted first and has not committed, the purge blocks on the account row, then keeps the blob; (3) a backfill that classified a pair before the purge inserts its Connection after it and still reads its key, because the purge skipped that account |
| E5c | no module under `src/aigateway` imports `profile_index` or `profile_models`, and both are gone; full suite green with the retired tests listed in the manifest |

## 5. Gates

From the repository root, per landing:

```sh
uv run .claude/scripts/run_gates.py aigateway --base origin/main
# from apps/aigateway, E5a and E5b:
AIGW_TEST_PG=1 uv run pytest -m needs_postgres -v
```

## 6. Deviations from the spec

- `PairMutation.profile_names` and `DEFAULT_LEGACY_NAME` leave in E5a, not E5c: E5a makes both
  dead.
- `profile_admin.py` is deleted in E5a rather than left with one free helper.
- Spec §5 E5a named two prior assertions; the change moves 21 tests (the E5a test map).

The spec's §4 and §5 were updated to match these deviations.
- The precondition for `--apply` is E5a or later on every replica, not E4c: an older replica's PUT
  on a deleted account can adopt a leftover blob at the `default` address, and a deleted account
  has no row for the C3 lock.
