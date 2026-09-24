---
id: OME-1208
linear_url: https://linear.app/openmined/issue/OME-1208/aigateway-migrate-provider-access-backing-from-profiles-toward
status: in_progress   # design PR #23 merged 2026-09-22; app implementation S1 in the unit worktree
type: task
priority: high
labels: [aigateway, agentic, autonomous]
parent: OME-1138
blocked_by: [OME-1207, OME-1210]
created: 2026-09-15
closed:
---

# AIGateway: migrate provider-access backing from Profiles toward Connections

Stage B of `OME-1138` (plan units S1, S2', S4). Behind the existing provider-access boundary the
backing moves from the legacy Profile to canonical Connections for every safely migrated
`(account, provider)` pair: one deterministic effective credential per pair (D11), no secret
re-entry, OAuth and API-key preserved, tenant isolation / encryption at rest / cache
invalidation / lifecycle fencing / delete-wins and stale-callback protections preserved,
ambiguous Profile/Connection collisions quarantined and reported (D3), legacy Profile routes
kept as compatibility facades over the new backing, no Profile storage deleted (expand-only,
rehearsed R1 rollback), SQLite and PostgreSQL covered. Out of scope: multiple selectable
accounts per provider, Admin UI redesign, SDK DTO change, defaults cutover, `X-Profile` sunset,
legacy route/schema/storage deletion, any live migration run.

Ledger: `docs/work/2026-09-22-OME-1208-provider-access-backing-transition.md`.
Spec: `docs/spec/2026-09-09-OME-1138-converge-connections.md` §3.8, §6.1, §7, §8, §11.
Plan: `docs/plan/2026-09-09-OME-1138-converge-connections.md` §2 S1/S2'/S4, §3 B, §4 G4.

- 2026-09-15: filed by the owner as architecture debt under `OME-1138`, blocked by `OME-1207`
  and `OME-1210` (both since Done). **Gate:** Backlog.
- 2026-09-22: D11 recorded by the owner on the issue — conservative path, one deterministic
  effective credential per pair, no multi-account expansion.
- 2026-09-22: unit started from `main` `99e2d4b2` (Stage A4 merged: PR #1006, PR #1007) on branch
  `OME-1208-aigateway-migrate-provider-access-backing-from-profiles`; labels completed with
  `agentic` + `autonomous`. Metamodel gate against design `main` (PR #22 merge): vocabulary and
  Stage D/E boundaries recorded, but one-credential-per-pair, facades-over-Connection write
  ownership (D14 still open on the admin card), Connection-backed authority after migration,
  quarantine and the expand-only rollback rule are absent → design revision first, application
  code blocked until it merges. Ledger created. **Gate:** In Progress.
- 2026-09-22: design revision drafted on a branch of the design repository (provider-access
  component v4 with the Stage B Target section; provider-credential-admin v3;
  provider-access-availability v2; catalog README note); catalog validator 0 errors, 3 baseline
  warnings, 3 entities bumped cleanly. Five questions posted for the owner (design PR
  authorization; D14 reading; D16 option a vs b; D12 multi-Connection pairs stay unmigrated; A4
  refresh scope). No application code. **Gate:** Needs Owner.
- 2026-09-22: owner decided D14 (per-pair authority marker), D16 option (a), the D12 Stage B
  rule (multi-Connection pairs stay unmigrated) and the PR scope (Stage B only, no A4 refresh),
  and authorized commit, push and PR. Cards updated to record the decisions; validator clean;
  design commit `4f3593dc` pushed; design PR #23 opened
  (https://github.com/OpenMined/screamingface-design/pull/23). Merge is the owner's step; app
  implementation starts after it. **Gate:** Needs Owner (merge).
- 2026-09-22: design PR #23 merged (design `main` `12d1bbe3`). Linear → In Progress with a
  start comment. App implementation begins in the unit worktree on `99e2d4b2`: S1 slot store +
  locator-authoritative strategy factory (RED tests first), then S2', then S4. No commit, push
  or PR before owner authorization.
- 2026-09-22: S1 done in the unit worktree (uncommitted): `provider_credential_slots` model +
  migration 0012, `PairAuthorityStore` (generation-fenced CAS), locator-authoritative credential
  addressing; 34 new tests; all card gates green vs `99e2d4b2`; PostgreSQL migration smoke green.
  Finding: pre-existing autodetector drift on `OAuthConnection.account` (0002) — owner decision.
  Next: S2' pair-authority routing + Connection-backed provider access/admin.
- 2026-09-22: S2'a done in the unit worktree (uncommitted): `ConnectionBackedProviderAccess`
  wired at the app's provider-access slot — a `migrated` pair resolves/authorizes from its
  effective Connection (locator-authoritative blob address, Profile rules applied to the
  Connection row), `none`/`quarantined` pairs keep the legacy path unchanged; both contract suites
  re-run green over a migrated seam; 58 new tests; full suite 4759 passed; all card gates green vs
  `99e2d4b2`. Next: S2'b — admin/facade/OAuth-callback writes for migrated pairs through the
  Connection authority.
- 2026-09-22: S2'b1 done in the unit worktree (uncommitted): `ConnectionBackedCredentialAdmin`
  wired at the app's admin slot — for a `migrated` pair `set_api_key`/`delete` write the effective
  Connection (marker fence → index mirror → Connection row → one blob, one transaction) and `list`
  renders the pair from it; `none`/`quarantined` unchanged; the admin contract re-runs green over
  a migrated seam; 37 new tests; full suite 4795 passed; all card gates green vs `99e2d4b2`.
  Next: S2'b2 — OAuth callback + `start_oauth`/`profile_status`/`patch_profile`/`refresh_profile`
  for migrated pairs through the Connection authority.
- 2026-09-22: S2'b2 done in the unit worktree (uncommitted): a `migrated` pair's Profile-facade
  OAuth flow (`POST /v1/auth/{provider}/profiles` → callback / exchange-code) publishes the pair's
  effective Connection and the blob its locator names, fenced by the pair marker's generation
  (stale callback, delete-wins and API-key-wins all answer today's `409 profile_auth_conflict`);
  no shadow Connection, no UUID blob; unmigrated/quarantined pairs unchanged. 19 new tests; all
  card gates green vs `99e2d4b2`. Next: S2'b3 (status/patch/refresh facades) and S2'b4
  (Connection-native routes consult the marker).
- 2026-09-22: S2'b3 done in the unit worktree (uncommitted): the Profile status/patch/admin-patch
  facades render a `migrated` pair from its effective Connection (agreeing with the list and with
  dispatch-failure marking) while `defaults`/`account_label` stay on the compatibility document;
  the refresh of a migrated pair runs through the Connection (row touched or marked, document
  mirrored, legacy 401/409 bodies unchanged; errored/pending rows are refused without a network
  call — flagged). The chat route was confirmed to speak to the port already. 21 new tests; all
  card gates green vs `99e2d4b2`. Next: S2'b4 (Connection-native routes consult the marker),
  S2'c (PostgreSQL), S4 (dry-run/apply tool).
- 2026-09-22: S2'b4 done in the unit worktree (uncommitted): the Connection-native routes (`…/connections/{id}/refresh`,
  `…/token`, `…/api-key`, `DELETE …/{id}`) address a migrated pair's effective row at its
  `credential_locator` (the Profile blob) and evict under that name; deleting the effective row
  retires the pair (marker effective → None, compat document removed, op 9 shape); replacing its
  key fences the pair generation and mirrors the compat document (op 8 shape); a lost fence is
  `409 connection_conflict`. New core module `connection_native.py`; `token_service` derives
  its name from the locator. 17 new tests; prior Connection-native suites 89 passed unmodified;
  full non-live suite 4853 passed / 42 skipped / 37 deselected; `run_gates.py aigateway` ALL
  GATES GREEN. Flagged: deviation (f) (native refresh/token mark the row only — the legacy
  status keeps the document's `last_refreshed_at`), D-S2b4-6 second-Connection policy (today's
  behaviour kept, owner to choose). Next: S2'c PostgreSQL coexistence tests, then S4 dry-run/apply.
- 2026-09-22: S2'c done in the unit worktree (uncommitted): PostgreSQL coexistence and race tests for
  the Connection side — `apps/aigateway/tests/integration/test_provider_access_backing_postgres.py`
  (5 tests, `needs_postgres`, fixtures bound from the prior PostgreSQL lane; no production code changed):
  marker compare-and-set fencing under real row locks, the JSONB locator round trip on a migrated pair,
  and three two-writer races (native delete vs legacy op 8, legacy op 8 vs native delete, Profile-facade
  OAuth callback vs native key replacement) — every loser answers 409 `connection_conflict` and the
  retried writer converges. `AIGW_TEST_PG=1` lane 5 passed first run (both PostgreSQL modules together:
  11 passed); default lane 5 skipped; `run_gates.py aigateway` ALL GATES GREEN. Next: S4 dry-run/apply
  tool (`python -m aigateway.migrate_profiles`).
- 2026-09-22: S4 done in the unit worktree (uncommitted): the secret-aware backfill tool
  `python -m aigateway.migrate_profiles --dry-run|--apply|--rollback (--account <id>|--all) [--journal PATH]` —
  `core/provider_access/backfill_classify.py` (read-only classification of every `(account, provider)` pair from
  the legacy index, the non-revoked Connections and the pair marker; "proven the same" = equal decrypted credential
  documents; anything unprovable is quarantined, never guessed), `core/provider_access/backfill_apply.py` (one
  transaction per account; `profile_only` creates a Connection at the Profile's own blob address without secret
  re-entry; conflicts roll the account back and are reported; idempotent by the marker; `--rollback` is the R1
  rehearsal, blobs kept) and the CLI shell (refuses to run without a master key rather than minting one; opaque
  identifiers only in report and journal). 53 new tests across SQLite unit suites, a real subprocess dry run and a
  PostgreSQL lane that proves the FIRST-marker race between two apply runs leaves exactly one Connection.
  `run_gates.py aigateway` ALL GATES GREEN; `AIGW_TEST_PG=1` lane 2 passed (all three PostgreSQL modules 13 passed).
  Spec §8 rows D11, D14, D16 marked decided and D12 given its Stage B rule (owner, 2026-09-22; design PR #23).
  Flagged for the owner: no owner-mapping flag, master-key refusal, the `--rollback` mechanism, legacy-index
  orphan documents out of scope, ORM DEBUG SQL logging echoes parameters (deployment concern). Next: owner review
  and authorization to stage/commit/push/PR (Stage B is complete; no Stage C/D/E work started).
- 2026-09-23: PR #1029 review round 1 addressed in the unit worktree (uncommitted, on top of the pushed
  commit): the blocking finding (deleting a Connection could destroy a credential blob another live owner
  still serves — a superseded row's sibling, or the legacy Profile after an R1 rollback) is fixed by a
  last-addresser guard before the blob delete; the api-key-to-OAuth regression under one name is fixed by
  retiring the superseded errored row inside the flow transaction; the incoherent rollback is fixed by
  mirroring every document of a migrated pair when a key is written. Five new tests reproduce all three
  reported scenarios (all RED first), 595 prior tests unmodified and green, gate runner ALL GREEN,
  PostgreSQL lanes 13 passed. The reviewer's alternative fix for the third finding (refusing an alias
  name) is a contract change and was surfaced to the owner rather than applied.
- 2026-09-23: R1 addendum — the first cut of the "retire the superseded errored row" fix took the row lock
  before the pair marker, inverting the single lock order; a new PostgreSQL test reproduced a deadlock
  against a concurrent key replacement. The start now advances the marker first, then retires the row.
  PostgreSQL lanes 14 passed; SQLite focused suites 595 passed. Still uncommitted, awaiting authorization.
- 2026-09-23 R2 (owner review of R1): concurrent deletes of rows sharing one blob now serialize on the pair's
  live rows in ascending id order (PostgreSQL race test, both orders); a rollback of a pair with alias
  documents is refused and reported (`rollback_refused_alias_documents`, exit 4) instead of leaving a
  document with no key at its address. Gates green; not committed.
