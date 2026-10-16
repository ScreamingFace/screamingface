---
ticket: OME-1640
stack: aigateway
status: in_progress   # planned | in_progress | done | blocked
started: 2026-10-15
finished:
---

# e1b-native-oauth-reauth — a migrated OAuth pair is re-authorised through the Connection API

## Intent

Landing E1b of Stage E (`OME-1209`, spec `docs/spec/2026-10-14-OME-1209-retire-legacy-profiles.md`
R6 and §8 Q5, plan §3 E1b). Mapping the tests E3 retires showed that the Profile facade
(`POST /v1/auth/{provider}/profiles`) is the only path that re-authorises a migrated pair's OAuth
credential in place: a native `POST /v1/oauth/connections` opens a row the pair marker never makes
effective, so chat keeps reading the errored row. This unit lets the native flow replace an unusable (`error`/`revoked`)
effective row: the callback makes the new row effective and revokes the old one, fenced by the
marker generation, using only the Connection side. No route or `reauth_url` changes.
The same change amends the Stage E spec and plan (E1b, the E3 catalog delta, the E3/E4 order note).

## Planned changes

Under `apps/aigateway/src/aigateway/`:

- `core/pending_auth.py`: `PendingAuthEntry.replaces_effective` (the observed migrated pair).
- `routes/oauth_connections.py` `start_connection_oauth`: record it when the observed pair is
  `migrated` and its effective row is `error`/`revoked`.
- `core/provider_access/connection_native.py`: the marker switch and the old row's retirement.
- `routes/auth.py` `_record_oauth_connection_completion`: call them in the D14 order inside the
  existing transaction.
- Docs: spec R6, §4, §5, §8; plan §2, §3 E1b, §3 E3 catalog delta, §4, §6.
- Tests: a new suite first; no prior test changes expected.

## Test plan

- Errored effective OAuth row on a migrated pair → native start → callback → new row effective,
  old row revoked, chat resolves the new row (200); same provider identity re-login included.
- Revoked effective row: same.
- Usable (`active`) effective row: a new connection stays a plain row; the effective is unchanged.
- A newer start, a delete or a key write between start and callback → 409, nothing half-published
  (marker, both rows and the blob unchanged).
- Non-migrated pairs: behaviour unchanged (existing suites stay green).

## Acceptance

- `uv run .claude/scripts/run_gates.py aigateway --base origin/main` green.
- OpenAPI byte-identical to the base.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `core/provider_access/__init__.py` (exports). Source:
  `core/pending_auth.py` (`replaces_effective`), `core/provider_access/connection_native.py`
  (`effective_to_replace`, `replaced_label`, `replace_effective`, `retire_replaced`,
  `take_over_effective`),
  `routes/oauth_connections.py` (OAuth start records the pair; API-key create takes over the
  effective row by the same rule), `routes/auth.py` (callback: marker CAS
  → compat step → rows locked in id order, old row revoked → new row activated → blob; same
  identity as another row → that row revoked with the old one, the new row activated; a lost native callback revokes its row; the
  replaced row's cached strategy evicted after commit). Tests: new
  `tests/unit/core/provider_access/test_native_oauth_replaces_unusable_effective.py` (17 cases) and
  `test_native_api_key_replaces_effective.py` (4 cases), and
  `test_native_unlabelled_targets_effective.py` (4 cases, the unlabelled rule),
  `test_native_repair_boundaries.py` (8 cases: the Profile document untouched on every repair
  branch, a same-identity row broken after its lookup, a stale failure after the repair, a failed
  repair leaving the same-identity row untouched), and the PostgreSQL lane
  `tests/integration/test_native_repair_postgres.py` (3 cases: a repair against a key takeover,
  against a delete of the replaced row, and a stale failure of the same-identity row waiting on
  the repair's lock);
  no test from before this unit changed; this unit's own promotion cases were rewritten to the
  owner's round-3 decision (below). Docs: spec R6 and §8 Q7, plan §3 E1b.
- **Commits:** `feat(aigateway): let a native connection replace a migrated pair's effective credential`;
  `feat(aigateway): let an unlabelled native connection replace the pair's main credential`;
  `fix(aigateway): keep a native repair off the Profile document and fence the live-row promotion`;
  `fix(aigateway): retire a same-identity row on repair instead of reusing it`
  (ticket backfilled at PR-open).
- **Gates:** `run_gates.py aigateway --base 59545b20b` (the unit's base; main has moved) all green after the review fixes, the unlabelled rule and review rounds 2 and 3 (append-only check, ruff, format, pyright, enterprise check, full suite with coverage).
- **Deviations:** review round (independent reviewer) → owner decisions 2026-10-16: a repair
  that signs into another live row's identity promotes that row; a broken effective row is
  replaced whatever its auth type, and a flow that asks for the effective row's own label
  replaces it even when it works (the Profile facade's re-auth by name — a working API key
  switches to OAuth in one step); the same rule for a native API-key create, the successor of the
  Profile key write (a working OAuth pair switches to a key in one step); a native write with
  no label targets the pair's main connection and keeps its real label (owner decision
  2026-10-16, this also lands an unlabelled same-identity re-login on the pair); a repaired pair is not R1-rollbackable (spec §8 Q7). Also fixed
  from the review: lock order with delete, a lost callback's stranded `pending` row, rollback
  tests for the 503 and integrity paths. The unit suite runs on SQLite, which ignores row locks;
  the lock order is exercised by the PostgreSQL lane cases below.
  Review round 2 (independent): the native repair callback still ran the compat-document update
  (the base's G0 step), so a repair under the Profile's own name rewrote it, against R6 and Q7 —
  now skipped whenever the flow replaces the effective row; the same-identity promotion now
  re-reads the live row under its lock and refuses (409) when a refresh failure broke it after
  the lookup; an unexpected failure of the promotion now retires the pending row like the plain
  activation (it had been left `pending`, its OAuth state already consumed). PostgreSQL lane:
  the 3 new cases pass (the broken-sibling case fails without the fix); 5 snapshot-upload cases
  fail on the local `pg_dump` 15 against the PostgreSQL 16 container, unrelated to this unit.
  Review round 3 (independent): a stale refresh rejection that arrives after a promotion commits
  (it waits on the lock and re-evaluates `status='active'`) still marked the promoted row `error`.
  Owner decision 2026-10-16: no row is reused — the same-identity row is revoked under the
  callback's row locks with the old effective row, and the repair's own new row becomes
  effective; `promote_live_row` and its separate failure path are removed (one repair path).
  A late `mark_error` now matches no `active` row. The unit's promotion tests were rewritten to
  this contract.
