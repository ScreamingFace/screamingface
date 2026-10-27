---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: aigateway
status: in_progress   # planned | in_progress | done | blocked
started: 2026-10-22
finished:
---

# e5b-history-purge — the offline command that purges the retired Profile storage (Stage E history cleanup, E5b)

## Intent

Stage E ended Profile authority, but the storage it used is still in `credential_blobs`: the
Profile index documents and the provider-credential blobs no Connection addresses. This unit adds
the owner-run command that deletes them under the contract of
`docs/spec/2026-10-21-OME-1715-e5-history-cleanup.md` §3 (C1-C7): one transaction per account,
fenced by `SELECT … FOR UPDATE` on the `accounts` row, failing closed per account, dry run first,
reporting counts and account ids only. Plan `docs/plan/2026-10-21-OME-1715-e5-history-cleanup.md`
§3 E5b. E5a (`OME-1715`, #1541) is merged, which is this landing's precondition. No data changes
on merge; the owner runs the command per environment.

## Planned changes

- `apps/aigateway/src/aigateway/core/provider_access/history_purge.py`: classification and the
  per-account transaction (split in two, like `backfill_classify` / `backfill_apply`, if it passes
  450 lines).
- `apps/aigateway/src/aigateway/purge_profile_history.py`: the CLI, built like
  `migrate_profiles.py` (own provider registry and stores, the encryption-at-rest provider
  installed the same way, `--dry-run|--apply`, `--account <id>|--all`, `--journal PATH`, non-zero
  exit when an account is skipped).
- `apps/aigateway/src/aigateway/core/provider_access/connection_locator.py`: a public
  `locator_credential_name` that answers `None` for a malformed locator;
  `credential_name_from_locator` keeps its UUID fallback on top of it (behaviour unchanged). The
  purge needs "malformed" as an answer, because C4 skips such an account instead of falling back.
- `apps/aigateway/src/aigateway/core/profile_index.py`: the legacy row's account and the
  per-account row naming become public names (`LEGACY_INDEX_ACCOUNT`, `index_account_for`), so the
  purge addresses the index rows without restating their format. Behaviour unchanged.
- `apps/aigateway/src/aigateway/migrate_profiles.py`: the master-key refusal becomes a public
  `refuse_without_a_key`, so both offline tools refuse a keyless database by one rule.
- New tests: a SQLite classification suite, a CLI suite, a configured-endpoint case and a
  PostgreSQL fence suite (names fixed at RED).
- No schema change, no migration.
- Review round (2026-10-23), on the same branch: a live account's purge keeps a blob any
  account's Connection resolves to, and is skipped when an unresolvable Connection of another
  account names it (C2/C4); the deleted-account sweep compares the whole `(service, account)`
  address (C1). New suite `tests/unit/core/provider_access/test_history_purge_references.py`.
- Review round 2 (2026-10-27), on the same branch: `--all` lists the anonymous account when it
  holds rows without an `accounts` row and skips it (`anonymous_account_unmaterialised`); an
  account whose resolved address has no row while another row sits under that service is skipped
  (`address_unproven`), and the sweep keeps that service whole; `--help` names the conditions of a
  run. New suite `tests/unit/core/provider_access/test_history_purge_anonymous.py`.
- Review round 3 (2026-10-27), on the same branch: rows the sweep keeps under an unproven address
  are counted (`kept_unproven_rows`) and refuse the run; `--all` journals the sweep's result as
  soon as it commits, before the legacy phase. New suite
  `tests/unit/core/provider_access/test_history_purge_journal.py`.
- One prior test changes: `tests/unit/test_profile_index_offline_only.py` adds
  `core/provider_access/history_purge.py` to `_OFFLINE_READERS` (the guard pins the exact set of
  modules that may read the index). Owner approval 2026-10-22, recorded in a test-change manifest
  for this unit's issue at PR-open.

## Test plan

- RED first, SQLite (spec §5 / plan §4): index rows go; blobs addressed by an `active`, `error`,
  `pending` or `revoked` Connection stay; a migrated Connection whose locator names its Profile's
  blob keeps it; orphan name-shaped, orphan uuid-shaped and deleted-account blobs go;
  `aigateway:jwt-secret` and rows outside a loaded provider's namespace stay; a `quarantined`
  marker, an unresolvable Connection, or an unmigrated document (per-account or legacy global row)
  skips the account whole; a configured physical account (Anthropic `keychain_account`) resolves
  through the strategy and stays; the global index row stays while a listed account is skipped;
  `--dry-run` leaves every table byte-equal; `--apply` deletes exactly the reported set; a second
  `--apply` reports zero; report and journal contain no service string.
- RED first, PostgreSQL: both commit orders of a Connection insert against the purge's account
  lock, and a backfill that classified before the purge and inserts after it; no key is lost.
- Then the full suite and the PostgreSQL lane.

## Acceptance

- New tests green; the only prior-test change is the approved `_OFFLINE_READERS` entry.
- `run_gates.py aigateway --base origin/main` green; PostgreSQL lane green for the new fence suite.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
  - New: `src/aigateway/core/provider_access/history_purge.py`,
    `src/aigateway/core/provider_access/history_references.py` (what every Connection row
    addresses, split out in the review round when the purge module passed 450 lines),
    `src/aigateway/purge_profile_history.py`.
  - Changed: `core/provider_access/connection_locator.py` (`locator_credential_name`),
    `core/profile_index.py` (`LEGACY_INDEX_ACCOUNT`, `index_account_for`), `migrate_profiles.py`
    (`refuse_without_a_key`), `tests/unit/test_profile_index_offline_only.py` (the approved
    `_OFFLINE_READERS` entry).
  - New tests: `tests/unit/core/provider_access/test_history_purge.py` (35) with its probes
    `history_purge_probes.py`, `tests/unit/core/provider_access/test_history_purge_references.py`
    (12), `tests/unit/core/provider_access/test_history_purge_anonymous.py` (4),
    `tests/unit/core/provider_access/test_history_purge_journal.py` (1),
    `tests/unit/test_purge_profile_history_cli.py` (16),
    `tests/unit/remote_endpoint/test_history_purge_endpoints.py` (1),
    `tests/integration/test_history_purge_postgres.py` (3, `needs_postgres`).
  - No schema change, no migration.
- **Commits:** `feat(aigateway): add the offline purge of retired Profile storage` (sha recorded
  at PR-open).
- **Gates:**
  - `run_gates.py aigateway --base origin/main`: all green (approved test transition, append-only
    check, ruff check, ruff format, pyright, no-enterprise, pytest with coverage).
  - Full suite: 6750 passed, 112 skipped; coverage 94% total, `history_purge.py` 100%,
    `purge_profile_history.py` 98%.
  - PostgreSQL lane (`AIGW_TEST_PG=1`): the fence suite 3/3 green.
  - Mutation checks on the PostgreSQL suite: with the account `FOR UPDATE` removed both
    commit-order tests fail (2 failed, 1 passed); with the unmigrated-document refusal removed the
    backfill-race test fails (1 failed, 2 passed). The module was restored byte-equal after each.
  - Review round: the four RED tests of the cross-account and whole-address cases and the three
    journal tests failed before the fix. `run_gates.py aigateway --base fade16614` (the merge
    base; `origin/main` had moved on in files this unit does not touch) all green; PostgreSQL
    fence suite 3/3 green.
  - Review round 2: the three anonymous-account tests, the two unproven-address tests and the
    `--help` test failed before the fix (the anonymous account's blob, index row and legacy row
    were deleted; the live key at the physical address was deleted). `run_gates.py aigateway
    --base fade16614` all green; PostgreSQL fence suite 3/3 green; coverage `history_purge.py`
    100%, `history_references.py` 100%, `purge_profile_history.py` 99% (the `__main__` line,
    which runs in a subprocess).
  - Review round 3: the counted-refusal test and the sweep-journal test failed before the fix
    (no counter; the journal ended on an account line). `run_gates.py aigateway --base fade16614`
    all green with the `_OFFLINE_READERS` manifest in place (without it the append-only check
    stops on that approved change, as recorded under Process); PostgreSQL fence suite 3/3 green;
    coverage `history_purge.py` 100%, `history_references.py` 100%.
- **Deviations:**
  - The CLI also composes the configured remote endpoints (`compose_providers`, as `main.py`
    does). The plan names only "own provider registry"; with `load_plugins` alone every
    configured endpoint's Connection is unresolvable and its account would be skipped.
  - The deleted-account sweep, the kept-unrecognised count and the legacy global index row run
    only with `--all`: they are not one account's rows, and the legacy row may go only once every
    account it lists is done.
  - An unmigrated document whose blob does not exist does not skip its account: C4 protects a
    blob a backfill would adopt, and there is none.
  - Checked on the installed Tortoise 1.1.8: on SQLite `select_for_update()` emits no `FOR
    UPDATE` and raises nothing, so C7's "no-op" assumption holds.
  - Review round (2026-10-23):
    - Fixed: one account's purge kept only the addresses of that account's own Connection rows;
      C2 keeps a blob any Connection addresses, and the sweep already did. It now resolves every
      account's rows, and an unresolvable row of another account whose locator names this one
      skips it (`connection_unresolvable`). Only the purged account's rows are fenced by its
      lock; after E5a no path creates a reference across accounts.
    - Fixed: the deleted-account sweep compared services only, so one addressed row kept every
      sibling row under its service; it now compares the whole `(service, account)` address, and
      an unresolvable row still keeps every row under the service its locator names (its own
      account is skipped, so the run reports a refusal).
    - Kept by design (owner decision 2026-10-27): the C4 unmigrated-document refusal compares
      services. The backfill reads a document at the locator's logical account and its
      Connection reads the strategy's physical one; every strategy keeps the service, so the
      service covers both. A spare refusal at worst, never a lost key; pinned by a test with a
      configured physical account.
    - Spec deviation (owner decision 2026-10-23): `--apply` requires `--journal`, and every
      journal line is flushed as it is written. Spec C5 lists the journal as optional; an apply
      commits account by account, and a run that stops part-way prints no report.
    - Not changed (owner decision 2026-10-27): `migrate_profiles --rollback` after a purge. No
      key is lost: since E4a the runtime reads no Profile document, a `none` pair resolves by
      label over its Connection rows, and the purge keeps every blob a Connection addresses. A
      pair rolled back after the purge is a `connection_only` pair, which R1 rolls back by design
      and a later backfill apply names again. A refusal "no document left" would also refuse that
      legitimate case.
    - Process: the test-change manifest for `_OFFLINE_READERS` is created at PR-open, after the
      issue is filed (as for E5a); `Refs: OME-N` goes in the PR body, not in commits.
  - Review round 2 (2026-10-27):
    - Fixed: in `auth_mode=disabled` the anonymous account's row appears only with its first
      Connection or pair marker, so `--all` (which lists accounts from their rows) swept a
      Profile-only install's anonymous rows as a deleted account's, and the legacy row with them.
      It is now listed when it holds rows and skipped, since no lock can fence an account without
      a row; the sweep never treats its rows as a deleted account's. `--account` on it reports
      the same reason. The backfill's `--all` lists accounts the same way; that is outside this
      unit.
    - Fixed: the purge resolves a physical account from its own environment (Anthropic
      `keychain_account`). A run whose environment differed from the gateway's deleted the live
      key. An account whose resolved address has no row while another row sits under that service
      is now skipped (`address_unproven`), and the sweep keeps that service whole. A `pending`
      row whose service holds no row at all still skips nothing.
    - Added: `--help` names the conditions of a run (the gateway's own environment, a backup
      first, the gateway stopped on SQLite, what exit 4 and `kept_unrecognised_rows` mean).
    - Added: a `none` marker with a document whose blob exists is an unmigrated document
      (`unmigrated_document`); this already held and is now pinned.
    - Kept by design (owner decision 2026-10-27): a Connection of a loaded provider with no
      credential strategy (Ollama, whose only mode is `none`) resolves to no address, so its
      account is skipped (`connection_unresolvable`). No key is lost. A persisted `auth_type` is
      only `oauth` or `api_key`, so no row proves it addresses nothing, and the one path that
      mints such a row (a backfill of a Profile whose blob is readable) names a real blob. The
      Connection DELETE route revokes the row and keeps it, and the purge counts rows of every
      status; `--help` says so. The dry run in each environment shows whether any account is
      affected, and the owner decides on that data. Prior art agrees on keeping and reporting:
      Terraform refuses a plan whose provider configuration is missing, and the Kubernetes
      garbage collector keeps an object whose owner reference does not resolve and reports it.
  - Review round 3 (2026-10-27):
    - Fixed: when a Connection of a live account names a deleted account's service and its
      resolved address has no row, the sweep kept the sibling row (right) but the live account's
      pass sees none of those rows, so the run reported zero everywhere and exited 0. The sweep
      now counts such rows (`kept_unproven_rows`) and they refuse the run (exit 4). The keeping
      rule is unchanged.
    - Fixed: `--all` wrote the sweep's counts only in the summary, after the legacy phase; a
      failure there left a committed sweep with no journal line. The sweep's line is now written
      and flushed as soon as it commits. No atomicity between the database and the file is
      claimed.
    - Test change inside this unit: the journal-shape assertion of
      `test_report_and_journal_carry_account_ids_and_counts_only` (added in this unit's first
      commit) expects the sweep's line as well and checks its content; `zero_counts` in the
      probes gains the new counter.
