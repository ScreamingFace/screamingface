---
ticket: OME-1819   # slug-named ledger; filed at PR-open
stack: aigateway
status: in_progress   # planned | in_progress | done | blocked
started: 2026-11-03
finished:
---

# effective-row-gateway — OME-1138 close-out L7a: the gateway marks the effective Connection

## Intent

Leaf L7a of the OME-1138 close-out (close-out spec §4.7; spec
`docs/spec/2026-10-29-local-engine-effective-row.md` §2 and plan
`docs/plan/2026-10-29-local-engine-effective-row.md` §2, both accepted by the owner 2026-11-03).
The Local Engine works only on the row labelled `screamingface`, while chat uses the row the
default resolve serves, so the Engine can list `connected` while chat refuses, or delete a row chat
does not use. L7a gives the Engine what it needs to follow chat: `GET /v1/oauth/connections` marks
each row `effective` when it is the row the default chat resolve serves. One pure core function
decides that row; the availability listing is re-expressed on it, so the two cannot drift. L7a also
treats an `expired` effective row as unusable (spec §8.1), so a labelled create replaces it.

## Planned changes

Gateway src (`apps/aigateway/src/aigateway/`):

- New `core/provider_access/effective_connection.py`: the pure rule (spec §2) — a provider that
  declares only `none` has none, whatever its marker or rows; a `migrated` pair with a reference
  has the referenced row, whatever its status; any other pair has its single `active` row, and
  none for zero or two or more. Also the listing step the route calls: one marker listing and one
  Connection listing over every status, the ids computed first, the `provider` and `status`
  filters applied after; without a `status` filter `revoked` rows stay hidden except the effective
  one (spec §8.3). Exported from `core/provider_access/__init__.py`.
- `core/provider_access/connection_backed.py`: `availability` re-expressed on the rule with no
  behaviour change; resolve keeps `_select_by_label`.
- `core/provider_access/connection_native.py:88`: `UNUSABLE_EFFECTIVE` gains `expired`.
- `core/oauth/store.py`: `OAuthConnectionStore.list` takes `include_revoked` (keyword, default
  off) so the route lists every status in one query; a list-row mapper beside
  `response_from_connection`.
- `core/oauth/schemas.py`: `OAuthConnectionListRow` extends `OAuthConnectionResponse` with a
  required, read-only `effective: bool`; `OAuthConnectionListResponse` lists it.
- `routes/oauth_connections.py:66-77`: the listing calls the core step. The single-row GET and the
  write responses are unchanged.

No schema or model change, so no migration (S1 not triggered). The OpenAPI change is additive; L9
regenerates the UI schema after this merges.

## Test plan

RED first:

- `tests/unit/core/provider_access/test_effective_connection.py`:
  - the pure rule over a table: no-auth provider with a stray `active` row, and with a `migrated`
    reference to it → none; a `migrated` reference → the referenced id whatever the row's status,
    beside another active row too, and when the row is not listed; no marker, `none`, or
    `migrated` without a reference → the single `active` row, none for zero or two or more;
    providers computed independently;
  - agreement with resolve on `ConnectionBackedHarness` (migrated with a reference; unmarked or
    `none` with one active row; two active; pending only; error only; no rows): the effective id
    is exactly the Connection the default resolve serves, and none where resolve refuses.
- `tests/unit/test_oauth_connections_effective.py`, through the route:
  - every row carries a boolean `effective`, at most one per provider, on the row the rule picks;
  - a `provider` and a `status` filter keep the flag of the unfiltered computation;
  - an unfiltered listing shows a `revoked` effective row flagged and hides every other `revoked`
    row; `status=revoked` lists the revoked rows;
  - `ollama` (declares only `none`) lists a stray `active` row with `effective: false`, alone and
    with a `migrated` marker that names it (spec §6.3);
  - the single-row GET and the write responses carry no `effective`; the OpenAPI list row
    requires it and marks it read-only;
  - the listing reads no secret, writes nothing, lists markers once and Connections once;
  - a stored marker in an unknown state fails the listing with `PairAuthorityDataError`.
- `tests/unit/core/provider_access/test_native_replaces_an_expired_effective.py`: a labelled
  API-key create and a labelled OAuth flow each replace an `expired` effective row. The prior
  `test_a_usable_effective_row_is_not_displaced` keeps its `pending` case unmodified.
- `tests/integration/test_oauth_connections_effective_postgres.py` (`needs_postgres`): the
  listing route on PostgreSQL over a migrated pair and an unmarked pair.
- GREEN: the full `aigateway` suite (`run_gates.py aigateway --base origin/main`), then the
  `needs_postgres` lane.

## Acceptance

- `GET /v1/oauth/connections` flags exactly the row the default chat resolve serves, at most one
  per provider, under any `provider` or `status` filter, and none for a provider that declares
  only `none`.
- The availability listing answers as before; every L1 and D17 test passes unmodified.
- A labelled create replaces an `expired` effective row; a `pending` one stays (R6).
- `run_gates.py aigateway --base origin/main` green; the PG lane green; no prior test changed, or
  each changed one is pinned in `.claude/test-change-approvals/OME-N.json`.

## Outcome (fill at the end — required before COMMIT)

- **Actual files (11 under `apps/aigateway`, plus this ledger and the task mirror
  `docs/tasks/2026-11-03-OME-1819-effective-row-gateway.md`):**
  - src (7): the new `core/provider_access/effective_connection.py` (`effective_connection_ids`,
    `flagged_connections`, `no_auth_providers`, `served_by_reference`, `visible_providers`) and
    its two exports in `__init__.py`; `connection_backed.py` (availability on the rule,
    `_unserved_status`, the visible providers from the shared helper);
    `connection_native.py` (`expired`); `core/oauth/store.py` (`include_revoked`,
    `list_row_from_connection`); `core/oauth/schemas.py` (`OAuthConnectionListRow`);
    `routes/oauth_connections.py` (the listing calls the core step).
  - tests (4, all new): `test_effective_connection.py` (64 cases),
    `test_oauth_connections_effective.py` (17), `test_native_replaces_an_expired_effective.py`
    (2), and the PG `test_oauth_connections_effective_postgres.py` (2). No prior test changed.
- **Commits:** `ef802a6bb` `feat(aigateway): mark the Connection chat uses in the Connection
  listing`, then a records fix to this ledger; the PR squash-merges them as one.
- **RED seen:** the rule's module did not exist; every listing test failed on the missing
  `effective` key, the schema test on the missing list row, the unknown-marker test with no
  `PairAuthorityDataError`; both `expired` cases kept the old effective row. After review: a
  delete committed between the two reads flagged its revoked row, and a listing whose marker
  kept moving answered 200; an active row of an unregistered provider, and of a provider hidden
  from the caller, were each flagged.
- **Gates:** `run_gates.py aigateway --base origin/main` (base `ffdc7e93f`, 2026-11-03): the
  append-only check, ruff, format, pyright, the no-enterprise check and pytest with coverage
  passed. `needs_postgres` lane: 69 passed.
- **Mutation checks:** showing every `revoked` row or none, and dropping the no-auth guard, each
  fail the new tests, as does the listing without its generation fence. Applying the
  `provider`/`status` filters before the rule changes nothing:
  the flag comes from the marker and the pair's active rows, which no filter hides. The single
  listing over every status stays for the `revoked` effective row.
- **Deviations:**
  - The route test lives in `tests/unit/core/provider_access/` (plan: `tests/unit/`) to use the
    Connection-backed harness, as the other Connection route tests there do.
  - `_served_by_reference` moved from `connection_backed.py` into the new module as
    `served_by_reference`, shared by resolve and the rule; `_label_status` became
    `_unserved_status`, since the one-active case now goes through the rule.
  - A reference to a row that is not listed still names it in the rule: availability lists
    `not_connected` (such a row is `revoked`, which lists the same; the read by id it kept before
    is dropped), the listing flags nothing.
  - The spec and plan PR (#1658) keeps its branch `local-engine-effective-row` rather than an
    `OME-1819-` name: a branch named for the issue would let that PR's merge close OME-1819
    before the code lands. It refs OME-1819 in its body; the code PR's branch carries the id.
  - The two listings are fenced by the pair generations, as `pair_inventory` fences its reads:
    one re-read, then 503 `credential_store_unavailable` (the legacy row of
    `routes/provider_access_http.py`). Spec §2 and plan §2 carry the sentence.
- **Review:** an independent review of the diff found one should-fix and three minor points.
  - Read skew between the marker and the Connection listing (should-fix): fixed by the fence
    above, with a race test and a bounded-retry test. Availability reads the same two listings
    unfenced; that predates L7a and drives no write, so it stays as it is.
  - Availability's read by id never changed the answer: dropped, pinned by a test over a
    reference to a revoked row beside an active one.
  - Rows of a provider the registry does not know, or the caller may not VIEW, could be flagged.
    The owner chose (2026-11-03) to leave them unflagged, as availability lists no row for them:
    `visible_providers` now gives both callers the one set, and spec §2 carries the rule.
  - The listing loads every `revoked` row of the account to find the effective one: accepted;
    pushing the filters into the query would split the one listing the flag is computed over.
