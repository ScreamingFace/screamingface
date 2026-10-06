---
ticket: OME-1497
stack: aigateway
status: in_progress   # planned | in_progress | done | blocked
started: 2026-10-06
finished:
---

# OME-1497-g0-writer-floor — fence the ownership-changing credential writers on the pair generation (G0, part 1 of 3)

## Intent

First release of the D18 Gateway landing (`docs/spec/2026-10-02-provider-credential-admin-contract.md`
§5.3, plan section B). Before the pair-addressed successor and its mutation-time bridge (G1) can
adopt a `none` pair, every writer that changes who owns a pair must lose to a concurrent ownership
change instead of overwriting it. G0 ships as three PRs under `OME-1497`, all merged before the G0
deployment:

1. **This unit:** the ownership-changing writers on `none` and `quarantined` pairs — legacy
   admin/tenant key set and delete, the legacy OAuth callback and its D14 shadow Connection, native
   OAuth start/callback, native API-key create/replace/delete, the Anthropic bootstrap.
2. OAuth refresh: split network fetch from a guarded publish in the four OAuth plugins.
3. Check-only guards for OAuth failure paths and error marks.

No new API, no schema migration, no data change in bulk.

### Owner decisions (2026-10-06, after the persistence inventory)

- Only real ownership changes advance the generation: key PUT/DELETE, OAuth callback completion,
  native create/start/key-replace/delete. OAuth begin, OAuth failure and error marks never advance;
  begin records the pair it observed so its callback can claim it.
- A native create or OAuth start on a `none` pair keeps `none` (no auto-promotion, D14); "a new
  create publishes `migrated`" applies to the G1 successor only.
- Legacy PUT and native key replacement capture the pair after provider key validation, as the
  migrated paths already do; the admin port and its shell stay unchanged.
- Three PRs, as listed above.

## Planned changes

All under `apps/aigateway/src/aigateway/` unless noted.

- `core/provider_access/writer_floor.py` (new): `claim_pair(observed)` re-publishes the observed
  authority (state, effective reference, note) at the next generation through
  `PairAuthorityStore.advance`, creating the anonymous account row first when the pair is unmarked
  (the marker's account foreign key); `hold_pair(observed)` locks an existing marker row and
  requires the observed generation without advancing; `fences_writer(pair)` is true for `none` and
  `quarantined` (migrated pairs keep their existing fences, non-effective native rows of a migrated
  pair stay unfenced as today).
- `core/oauth/store.py`: the anonymous-account helper becomes public for the floor.
- `core/provider_access/profile_admin.py` + `connection_admin.py`: the legacy body receives the pair
  the branch read observed and claims it as the first statement of its transaction; a lost claim is
  the existing 409 `profile_conflict`. Legacy delete keeps the blob when a live Connection addresses
  the same service/account (the R1 shape).
- `core/pending_auth.py`: `PendingAuthEntry.observed_pair` — the pair a legacy or native flow
  observed at start (the existing migrated-only `pair_generation` keeps its meaning).
- `core/provider_access/connection_oauth.py` + `routes/auth.py`: legacy begin returns the observed
  pair; the legacy callback claims it before `authenticate_pending` (lost claim: the existing 409
  `profile_auth_conflict`); the D14 shadow write and native callback activation run under the
  published pair (hold for the shadow, claim for a native flow), the native-callback document update
  and duplicate cleanup included.
- `routes/oauth_connections.py` + `core/provider_access/connection_native.py`: native start, API-key
  create, key replacement and delete claim a `none`/`quarantined` pair inside their transaction
  (marker → row → blob); a lost claim is the existing 409 `connection_conflict`.
- `main.py`: the startup bootstrap runs under the floor (claim on an unmarked or `none` pair, skip a
  `migrated` or `quarantined` one, roll back when the plugin imports nothing).
- `docs/spec/2026-10-02-provider-credential-admin-contract.md` §5.3: record the owner decisions.
- Tests under `apps/aigateway/tests/unit/core/provider_access/` and `tests/integration/`.

## Test plan

RED first:

- `claim_pair` keeps state, reference and note and moves the generation by one; a stale claim
  raises `PairAuthorityConflict`; an unmarked pair of the anonymous account claims without a false
  conflict; `hold_pair` refuses a moved generation and never advances.
- Legacy PUT/DELETE that read the pair before another writer moved it lose with 409
  `profile_conflict` and change no document, blob or marker; a quarantined pair keeps its state and
  note; legacy delete keeps a blob a live Connection still addresses.
- A legacy OAuth callback after an ownership change loses with 409 `profile_auth_conflict` and
  writes neither document nor blob nor shadow; a fresh callback advances `none` by one and keeps it
  `none`; a shadow is not written when the pair moved after the Profile publication.
- Native start/create/replace/delete on `none` advance by one and keep `none`; a stale native key
  replacement and a stale native callback lose with 409 and write nothing; a migrated pair's
  non-effective rows keep today's behaviour.
- PostgreSQL lane: a legacy writer and a native writer racing on one unmarked pair commit exactly
  one; two first-marker writers commit exactly one, no orphan.
- Bootstrap: imports on an empty unmarked pair, skips a migrated pair, leaves the marker untouched
  when nothing is imported.

Prior assertions that change are listed and approved byte-exactly before they are edited.

## Acceptance

- Every ownership-changing persistence path of the inventory in scope here is fenced or shown not
  to change ownership; guarding the routes alone does not pass.
- The falsifiers above pass on mixed legacy and native writers on their own (no G1 code).
- Full `aigateway` gates and the PostgreSQL lane green; prior tests unchanged unless approved.
- No new API, schema migration, feature flag, lock table, job or bulk data change.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** new `core/provider_access/writer_floor.py` (`fences_writer`, `claim_pair`,
  `claim_observed`, `hold_pair`, `bootstrap_under_the_floor`); changed `core/oauth/store.py`
  (`ensure_anonymous_account` public), `core/pending_auth.py` (`observed_pair`),
  `core/provider_access/{__init__,connection_admin,connection_native,connection_oauth,profile_admin}.py`
  (`claim_native_write`, `claim_for_connection`, `addressed_by_a_live_connection`, the
  `observed_pair` keyword on the admin bodies and the OAuth begin), `routes/auth.py` (legacy begin
  record, legacy and native callback claims, shadow hold, `_connection_conflict`),
  `routes/oauth_connections.py` (native start, create, replace, delete claims), `main.py` (startup
  bootstrap under the floor). New tests: `tests/unit/core/provider_access/test_writer_floor{,
  _legacy_admin,_legacy_oauth,_native,_bootstrap}.py`, `tests/integration/test_writer_floor_postgres.py`.
  Docs: spec §5.3 owner-decision paragraph and §9 row, the `OME-1497` mirror, the `OME-1375` mirror
  closed (done, 2026-10-06), this ledger. Approval manifest `.claude/test-change-approvals/OME-1497.json`.
- **Commits:** one commit, `feat(aigateway): fence ownership writers on the pair generation`,
  rebased onto `a502cb996` (upstream `#1153` and `#1240` landed meanwhile; the only shared file was
  the `core/provider_access/__init__.py` export list).
- **Gates:** `uv run .claude/scripts/run_gates.py aigateway --base origin/main` on `a502cb996` — ALL
  GATES GREEN (append-only with the five approved transitions, ruff check, ruff format, pyright 0
  errors, no-enterprise, pytest with coverage ≥ 80%); full suite 5219 passed, 97 skipped. PostgreSQL
  lane (`AIGW_TEST_PG=1 uv run pytest -m needs_postgres`): 55 passed, including the four new floor
  races; 5 failed in `test_cache_snapshot_upload_postgres.py` only because the local `pg_dump` 15
  refuses the 16-alpine test server — `request_cache` is untouched here.
- **Independent review (four lenses, each finding challenged by a separate skeptic):** 7 findings,
  3 survived.
  - Fixed: a native OAuth start claimed the pair before binding its loopback redirect, so a start
    that answered 503 `oauth_loopback_unavailable` still superseded the flow in flight. The redirect
    now binds before the claim, as the legacy start does (OME-307 Blocker 5), and the listener is
    closed when the claim or the row insert fails. Tests: a start that cannot bind leaves the flow
    in flight completable and writes no row; a start that lost its claim closes its listener.
  - Covered: a native callback that loses its claim leaves a same-named legacy Profile untouched.
  - Recorded, not changed here: the unchanged `migrate_profiles --apply` backfill inserts its
    Connection row before it advances the marker, while native writers now claim the marker
    first; on PostgreSQL a backfill and a native create/start with the same label on the same pair
    can deadlock, and PostgreSQL aborts one of the two transactions whole (no partial write).
  - Refuted (by design): the native callback's claim commits before the Connection activation, as
    the legacy flow does; the 409 body text is the existing `connection_conflict` message.
- **Deviations:**
  - The startup bootstrap claims `quarantined` as well as `none` (one `fences_writer` rule for every
    legacy writer) instead of skipping `quarantined`; it skips `migrated` and rolls back when the
    plugin imports nothing.
  - The native-callback duplicate cleanup is left unfenced: it only revokes the flow's own pending
    row and its never-written UUID blob, so it changes no owner.
  - Native API-key create captures the pair before its key validation (spec §5.3 literal); key
    replacement and delete capture inside the publication transaction, after validation.
  - Consequence accepted by the owner: concurrent ownership writers on one pair now conflict
    instead of serializing. Two overlapping native OAuth starts leave the earlier flow's callback
    with 409 `connection_conflict` (latest start wins); a delete that read the pair before a
    committed set, or the second of two first-marker deletes, answers 409 and is retried.
  - Prior tests changed with byte-exact owner approval (manifest above): marker generations in
    `test_connection_backed_admin.py` (2) and `test_connection_backed_oauth_flow.py` (2, one renamed
    from `..._never_writes_a_marker` to `..._stays_legacy_owned`); the label-conflict route test
    completes each native flow before the next start; the PostgreSQL commit-order races wait for the
    second writer to park on a lock and expect 409 plus a retry where the delete read a stale pair.
