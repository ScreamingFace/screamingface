---
ticket: OME-1824
stack: aigateway
status: done   # planned | in_progress | done | blocked
started: 2026-11-04
finished: 2026-11-05
---

# stale-row-conditional-delete — OME-1138 close-out L7c: a Connection delete can require the row's status

## Intent

A new leaf of the OME-1138 close-out, which blocks L7b. Spec and plan:
`.docs/2026-11-04-l7c-conditional-delete-{spec,plan}.md`, owner-approved on 2026-11-04 and landed
by this unit in `docs/spec/2026-10-29-local-engine-effective-row.md` and
`docs/plan/2026-10-29-local-engine-effective-row.md`.

L7b's stale-row repair decides from one listing, then sends a plain `DELETE`. If an OAuth
callback or a key write activates the row in between, the gateway deletes a working row and its
blob. This unit adds `?expected_status=pending|error` to `DELETE /v1/oauth/connections/{id}`.
After the delete's pair claim, inside its transaction, the row goes only if it still has that
status and is not its pair's effective reference. Otherwise the gateway answers 409
`connection_conflict` and rolls everything back. A delete without the parameter is unchanged.

## Planned changes

Under `apps/aigateway/`:

- `src/aigateway/routes/oauth_connections.py`:
  - `delete_connection` takes an optional `expected_status: Literal["pending", "error"]` and
    passes it to `_delete_connection`;
  - after `claim_for_connection`, a row that `effective_pair_of` names is refused;
  - the revoke becomes conditional on the status.
- `src/aigateway/core/oauth/store.py`: `revoke_if_status`, a conditional revoke in the
  `complete_pending` idiom, returning `None` when the row's status moved. (Not taken; see the
  Outcome's deviations.)
- New tests: `tests/unit/core/provider_access/test_conditional_delete.py` and
  `tests/integration/test_conditional_delete_postgres.py` (`needs_postgres`).

Docs: the gateway section and the L7c plan section in the two L7 documents above.

No model change, no migration.

## Test plan

RED first; no prior test is expected to change.

- Match: 204, the row revoked, its blob gone.
- The row went `active` after the caller listed it: 409 `connection_conflict`; row, blob and
  pair generation unchanged.
- The row is its migrated pair's effective reference: 409, nothing changed.
- No parameter: today's behaviour (a `pending` and an `active` row both go).
- `expected_status=active` or an unknown value: 422.
- PostgreSQL: a callback that activates the `pending` row while the conditional delete waits
  on the pair marker → the delete answers 409 and the row stays `active` with its blob; the
  reverse order → the callback loses.

## Acceptance

- The new tests pass; every prior gateway test passes unchanged.
- `uv run .claude/scripts/run_gates.py aigateway --base origin/main` all green.
- The PostgreSQL race runs green with `AIGW_TEST_PG=1`, or the ledger says why it could not run.

## Outcome (fill at the end — required before COMMIT)

- **Actual files (under `apps/aigateway`, plus this ledger, the spec and the plan):**
  - src (3): `routes/oauth_connections.py` (`ExpectedDeleteStatus`, the `expected_status` query
    parameter, the effective-row refusal after the claim, `lock_if_status` before
    `mark_revoked`, `_changed_since_listed`; 699 lines, 662 before),
    `core/provider_access/connection_native.py` (`lock_if_status`; 338 lines) and
    `core/provider_access/__init__.py` (its export).
  - new tests (2): `tests/unit/core/provider_access/test_conditional_delete.py` (16 cases) and
    `tests/integration/test_conditional_delete_postgres.py` (4 cases, `needs_postgres`).
  - docs: spec §2a; plan §3a, its layout row and the L7b order.
  - No prior test changed.
- **Commits:** on branch `OME-1824-stale-row-conditional-delete` (`stale-row-conditional-delete`
  until PR-open), rebased onto `00802ae3f` at PR-open; upstream changed no `apps/aigateway` file.
  `f09bdedab` feat(aigateway): let a Connection delete require the row's status (OME-1138 L7c);
  `7cead4584` docs(work): keep the L7c ledger open until its PR merges (OME-1138 L7c); then the
  commit that files `OME-1824` here and in its `docs/tasks` mirror, and the review's move of the
  mirror to `in_review`. Squash-merged to `main` as `24d979a5e` (#1678) on 2026-11-05.
- **RED seen:** 11 of the 16 SQLite cases failed: a conditional delete answered 204 where 409
  was expected (a row activated since the listing by a sign-in or by a key fix, a row in another
  status, the effective row in `pending` and in `error`) or where 422 was expected (six values).
  The other 5 pin unchanged answers. On PostgreSQL 2 of the 4 failed: a callback that commits
  after the delete read the row and before its claim lost its row to a 204, with no effective
  row and with a broken one. The reverse order already passed: the callback loses.
- **Mutations:** without the effective-row refusal 2 cases fail; with `lock_if_status` always
  true, 3 SQLite cases and the PostgreSQL race fail.
- **Gates:** `uv run .claude/scripts/run_gates.py aigateway --base origin/main` (base
  `15bea1200`, 2026-11-04): the append-only check, ruff, format, pyright, `check_no_enterprise`
  and pytest with coverage all green, 7885 tests collected (the PostgreSQL ones skip without
  `AIGW_TEST_PG`). The PostgreSQL lane ran: `AIGW_TEST_PG=1 uv run pytest -m needs_postgres`
  with `pg_dump` 16, 73 passed, the four new races among them.
- **Deviations:**
  - The status check is a locking read right before `mark_revoked` (`lock_if_status`,
    `core/provider_access/connection_native.py`), not the planned conditional `UPDATE` in
    `core/oauth/store.py`. The guarantee is the same under READ COMMITTED, the revoke keeps one
    shape, and `store.py` stays at 446 lines (the method took it to 471). Spec §2a and plan §3a
    name the locking read.
  - `routes/oauth_connections.py` was already over 450 lines (662); it grows by 37 inside the
    delete it owns.
  - The PostgreSQL races run on two pair shapes, no effective row and a broken one.
