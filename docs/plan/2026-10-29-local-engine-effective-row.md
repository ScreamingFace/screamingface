---
status: accepted   # owner, 2026-11-03, with the spec
issue: OME-1819   # L7a (aigateway); L7b (screamingface-engine) is filed at its own PR-open
parent: OME-1138
date: 2026-10-29
base: origin/main ffdc7e93f
---

# The Local Engine manages the Connection chat uses (L7a + L7b) — plan (OME-1138)

Implements `docs/spec/2026-10-29-local-engine-effective-row.md` (accepted 2026-11-03; the owner's
answers are its §6). Close-out spec §4.7, close-out plan section "L7a + L7b". Two leaves under
`OME-1138`, two code PRs: L7a lands `aigateway`, L7b lands `screamingface-engine`.

The spec's §8 lists three points where the code differed from its create and repair table and
its listing checks. The owner settled all three on 2026-11-02, and the spec folds them into §2 and
§3: the gateway treats an `expired` effective row as unusable and keeps a `pending` one usable
(R6); an API-key `E` is re-keyed in place when `active` or `error` and replaced by a new row when
`revoked`; the listing always shows the effective row, whatever its status.

On 2026-11-03 the owner limited the listing check "exactly one `active` row and none flagged" to
credential-bearing providers (spec §6.3). A provider that declares only `none` has no effective
row whatever its stored rows; its public status comes from `/v1/provider-access`.

On 2026-11-04 the owner added a third leaf, L7c (`aigateway`, §3a, spec §2a): a delete that
requires the row's status, which the stale-row repair of L7b uses. L7b is blocked by L7c.

## 1. Layout and order

| Tree | Branch (from `origin/main`) | Carries |
|---|---|---|
| `.claude/worktrees/local-engine-effective-row` | `local-engine-effective-row` | this plan and the spec |
| `.claude/worktrees/effective-row-gateway` | `effective-row-gateway` | L7a: code, tests, ledger |
| `.claude/worktrees/effective-row-engine` | `effective-row-engine` | L7b: code, tests, ledger |
| `.claude/worktrees/stale-row-conditional-delete` | `stale-row-conditional-delete` | L7c: code, tests, ledger, the spec §2a and this §3a |

`uv sync --locked` in the app of each worktree. Nothing is edited in the shared checkout.

1. **Spec and plan.** Accepted 2026-11-03. They land in a `docs(spec): …` PR, the first PR of the
   L7a issue, filed at its PR-open; the L7a code PR refs the same issue.
2. **L7a.** Starts in a fresh `effective-row-gateway` worktree from the current `origin/main`.
   L5 has merged (`330e4204d`, #1652), so L7a reads its names: `PendingAuthEntry.fallback_label`
   (`routes/oauth_connections.py:177`) and the `connection_authorize` import in
   `core/provider_access/connection_backed.py:43`. Within the `aigateway` stack at most one leaf
   is between GREEN and merge.
3. **L7b.** Built against a fake gateway; it merges after L7a and L7c.
4. **After L7a merges:** L9 regenerates the UI schema, and L3 may start (L4a, L4b and L5 have
   merged).

## 2. L7a — the gateway marks the effective row (`aigateway`)

1. **Ledger first.** `docs/work/YYYY-MM-DD-effective-row-gateway.md` from `docs/work/TEMPLATE.md`
   (`ticket: unfiled`; Intent, Planned changes, Test plan, Acceptance).
2. **Baseline.** On the fresh worktree, the focused suites pass:
   `tests/unit/core/provider_access/test_availability_follows_resolve.py`,
   `tests/unit/core/provider_access/` (resolve, availability), `tests/unit/test_oauth_connections_routes.py`
   and `tests/unit/test_provider_access_availability_route.py`.
3. **RED.**
   - New `tests/unit/core/provider_access/test_effective_connection.py`:
     - the pure function over a table (spec §2): a provider that declares only `none` → none,
       whatever its marker or rows (a stray `active` row, a `migrated` reference to one); a
       `migrated` pair with a reference → the referenced id, whatever the row's status; no
       marker, `none`, or `migrated` without a reference → the single `active` row, and none for
       zero or two or more;
     - agreement with resolve, on `ConnectionBackedHarness` over L1's cases (migrated with a
       reference; unmarked or `none` with one active row; two active; pending only; no rows): the
       flagged id is exactly the Connection the default resolve returns, and none where resolve
       refuses.
   - New `tests/unit/test_oauth_connections_effective.py`, through the route:
     - every listed row carries a boolean `effective`, at most one per provider;
     - a `provider` filter and a `status` filter keep the flag of the unfiltered computation;
     - an unfiltered listing shows a `revoked` effective row flagged, and still hides every other
       `revoked` row (spec §8.3);
     - a provider that declares only `none` (`ollama`) lists a stray `active` row with
       `effective: false`, alone and with a `migrated` marker that names it (spec §2, §6.3), as
       the D17 tests pin its status (`test_availability_follows_resolve.py:317-345`);
     - the single-row GET and the write responses carry no `effective`;
     - the listing reads no secret, writes no marker, Connection or credential record, and lists
       markers once and Connections once (spies on the wired stores);
     - a stored marker in an unknown state fails the listing as it fails chat
       (`PairAuthorityDataError`), and flags nothing.
   - In a new `tests/unit/core/provider_access/test_native_replaces_an_expired_effective.py`: a
     labelled API-key create and a labelled OAuth flow each replace an `expired` effective row
     (spec §8.1). The prior `test_a_usable_effective_row_is_not_displaced` keeps its `pending`
     case unmodified.
   - New `tests/integration/test_oauth_connections_effective_postgres.py` (`needs_postgres`): the
     listing route on PostgreSQL over a migrated pair and an unmarked pair.

   Each fails for the stated reason (no field, no module) before any production change.
4. **GREEN.**
   - New module `core/provider_access/effective_connection.py`: one pure function over the
     account's markers, its Connections and the providers that declare only `none`, returning each
     provider's effective Connection id or none. The no-auth guard comes before the marker, as in
     `availability` (`connection_backed.py:330-334`). The registered providers the caller may VIEW
     come from one helper that availability and the listing share; a row of any other provider is
     unflagged.
   - `ConnectionBackedProviderAccess.availability` (`connection_backed.py:295-370`) is re-expressed
     on it with no behaviour change; every L1 test stays unmodified and green. Resolve keeps
     `_select_by_label` (`:95-111`).
   - `core/oauth/schemas.py`: a list-row schema extending `OAuthConnectionResponse` (`:20-33`) with
     a required, read-only `effective: bool`; `OAuthConnectionListResponse` (`:36-37`) lists it.
   - `routes/oauth_connections.py:66-77`: one marker listing (`PairAuthorityStore.list`,
     `pair_authority.py:108`) and one Connection listing covering every status the filters can ask
     for (the default store listing hides `revoked`, `core/oauth/store.py:46-49`); the ids are
     computed first, the `provider` and `status` filters applied after. The route file is already
     653 lines, so the rule stays in the core module and the route adds only the call. The
     unfiltered listing keeps the effective row whatever its status. The two listings are fenced
     by `PairAuthorityStore.generations` (`pair_authority.py:117`) as `pair_inventory` fences its
     reads: one re-read, then the legacy 503 `credential_store_unavailable`.
   - `core/provider_access/connection_native.py:88`: `UNUSABLE_EFFECTIVE` gains `expired`.

   Then the full AIGateway suite. Retries are bounded at 10 per failing signal.
5. **Comments.** New comments use the `WHY` / `INVARIANT` / `FEATURE` / `STORY` anchors only. The
   OpenAPI change is additive; L9 regenerates the UI schema.
6. **Gates.**
   - `uv run .claude/scripts/run_gates.py aigateway --base origin/main` from the repo root.
   - `AIGW_TEST_PG=1 uv run pytest -m needs_postgres` from `apps/aigateway`, with
     `PATH=/opt/homebrew/opt/postgresql@16/bin:$PATH`: the default `pg_dump` 15 fails the snapshot
     tests against the PostgreSQL 16 server.
7. **Review.** An independent read-only review of the branch diff before PR-open; material
   findings are fixed or reported.
8. **Ledger outcome.** Actual files, commits, gate results, deviations.
9. **PR-open, on the owner's word for each external step.**
   - The L7a leaf under `OME-1138` (filed with the spec PR, step 1 of §1): labels `aigateway`,
     `agentic`, `autonomous`; assignee me. The branch is renamed `OME-N-effective-row-gateway`.
   - Prior tests: none is expected to change, since the field is additive and the listing tests
     assert named keys. A test that pins the listing's exact key set would be the exception, and
     its file goes into `.claude/test-change-approvals/OME-N.json` with its base and approved blob.
   - The `docs/tasks` mirror; stage the Markdown paths on approval of each exact path.
   - PR body from `pr_template.md` with `Refs: OME-N`, a release note line, and no attribution
     lines.
10. **Close.** Close comment and Done; close the mirror and the ledger.

## 3. L7b — the Engine selects the effective row (`screamingface-engine`)

1. **Ledger first.** `docs/work/YYYY-MM-DD-effective-row-engine.md`, as above.
2. **Baseline.** `tests/unit/test_connections_aigateway.py`,
   `tests/unit/test_connections_provider_access_availability.py` and
   `tests/unit/test_local_aigateway_connection.py` pass.
3. **RED.**
   - New `tests/unit/test_connections_aigateway_effective.py`, with a fake gateway that serves
     `/v1/providers`, `/v1/oauth/connections` with `effective`, `/v1/provider-access` and the write
     routes:
     - every row of spec §3's create and repair table, including the §8 rows: API-key `E` in
       `active` or `error` re-keyed in place, in `revoked` replaced by a `POST`; `pending` `E`
       answered with `ConnectionConflict` on `connect` and `start_oauth`;
     - `list` shows the provider-access status: `needs_reauth` and `error` on an `active` `E`,
       `not_connected` for a provider absent from it. `E` adds `auth_method` and `account_label`;
     - each listing check of §3 raises `ConnectionBadResponse`: the field on some rows only; for a
       provider `/v1/providers` lists, two rows flagged, or one `active` row and none flagged;
     - a stray `active` row of a provider `/v1/providers` does not list (a no-auth provider such
       as `ollama`), flagged `false`, raises no `ConnectionBadResponse`: `list` builds no
       Connection from it and takes no `auth_method` or `account_label` from it, and every listed
       provider keeps its `/v1/provider-access` status (spec §3, §6.3);
     - a malformed provider-access body raises `ConnectionBadResponse`, an unreachable gateway
       `ConnectionUnavailable`, a timeout `ConnectionTimeout`;
     - `connect` returns the `/v1/provider-access` status read after its write, never one derived
       from the written row: a write the gateway then lists as `needs_reauth` or `error` returns
       that status, and the written row only supplies `auth_method`;
     - `disconnect` of `E` while the user has a second active row returns `connected`, read after
       the writes;
     - the stale-row repair removes only the provider's non-active `screamingface` rows, leaves a
       non-active row under any other label, and is idempotent with nothing to remove;
     - the accepted collision (spec §3), pinned with a row the user created outside the Engine:
       with no `E`, an `error` API-key row labelled `screamingface` is re-keyed in place by
       `connect` (a `PUT`, the row turns `active`) and removed by the repair of `start_oauth`;
     - a 409 `label_conflict` maps to `ConnectionConflict`;
     - `connect` accepts an in-place `PUT` on a row under the user's label.
   - New `tests/unit/test_connections_aigateway_version_skew.py`: a listing in which no row carries
     `effective` selects by the label rule and logs once per process; the status still comes from
     `/v1/provider-access`; a listing with zero rows reads the same under both rules.
   - The hosted adapter's tests are unchanged.
4. **GREEN.**
   - `connections/aigateway.py` is already 454 lines. The row rules (selection, listing checks,
     create and repair decisions, the skew fallback) move to a new module
     `connections/aigateway_rows.py`; the adapter keeps the I/O.
   - `_ConnectionRow` (`:58-65`) records whether `effective` was present and its value;
     `_validate_row` (`:408-435`) accepts a boolean or its absence and refuses any other value.
   - Local `list` reads `/v1/oauth/connections` and `/v1/provider-access`; the writes follow the
     table; `connect` and `disconnect` return the provider-access status after their writes, so no
     Local status is derived from a row's lifecycle (`_public`, `connections/aigateway.py:276-297`,
     no longer decides it).
   - The per-provider listing checks run only for the providers `/v1/providers` lists; rows of any
     other provider are ignored. The field-presence check covers the whole response.
   - `_MANAGED_LABEL` (`:44`) stays as the label of an Engine create and the mark the stale-row
     repair reads. `_select` (`:253-259`) is replaced.
   - The skew fallback carries a `WHY` naming its removal in the release after L7b ships.

   Then the full Engine suite. Retries are bounded at 10 per failing signal.
5. **Prior tests expected to change** (close-out spec §6: "Engine connections suites that pin the
   managed label"). Under the skew fallback a listing without `effective` keeps the label rule, so
   the label-rule tests keep their meaning. They change where the Local `list` or `disconnect` now
   also reads `/v1/provider-access`, which the fake `_get` (`test_connections_aigateway.py:67-69`)
   answers with the row listing, and where `connect` drops its label check. Candidates:
   - in `tests/unit/test_connections_aigateway.py`: the Local listing tests
     (`test_connected_state_is_sanitized_and_identity_is_forwarded`,
     `test_oauth_account_exposes_only_the_safe_display_label`,
     `test_malformed_oauth_account_is_rejected`,
     `test_lists_every_provider_and_keeps_credentials_provider_scoped`,
     `test_multiple_unmanaged_rows_leave_the_automatic_row_disconnected`,
     `test_managed_row_is_selected_without_mutating_unmanaged_rows`), the `disconnect` tests
     (`test_disconnect_never_deletes_an_unmanaged_connection`,
     `test_disconnect_is_idempotent_and_removes_the_selected_connection`,
     `test_disconnect_is_idempotent_when_a_concurrent_delete_wins`), and the label case of
     `test_connect_rejects_an_incorrect_success_response`;
   - in `tests/unit/test_connections_provider_access_availability.py`:
     `test_an_explicitly_mutable_adapter_keeps_the_local_listing_and_its_mutations`.

   The exact list is confirmed at RED and approved by the owner before GREEN. A retired test keeps
   a tombstone naming its successor. `.claude/test-change-approvals/OME-N.json` pins each changed
   file's base and approved blob.
6. **Gates.** `uv run .claude/scripts/run_gates.py screamingface-engine --base origin/main` from the
   repo root.
7. **Review, ledger outcome, PR-open and close** as in §2 steps 7-10: the L7b leaf under `OME-1138`
   with labels `screamingface-engine`, `agentic`, `autonomous`; branch `OME-N-effective-row-engine`;
   the manifest of step 5; the release note says a Local Engine now lists and manages the
   Connection chat uses.

## 3a. L7c — a delete can require the row's status (`aigateway`)

Spec §2a. One leaf under `OME-1138` that blocks L7b; it merges before L7b and before gateway
1.0.0 is released.

1. **Ledger first.** `docs/work/2026-11-04-stale-row-conditional-delete.md`, `ticket: unfiled`.
2. **Docs.** Spec §2a and this section ship in the L7c PR.
3. **RED.**
   - `tests/unit/core/provider_access/test_conditional_delete.py`, on the Connection-backed
     harness of `test_connection_backed_native_routes.py`: the SQLite cases of spec §2a.
   - `tests/integration/test_conditional_delete_postgres.py` (`needs_postgres`), on the fixtures
     of `test_native_repair_postgres.py`: the two PostgreSQL orders of spec §2a.
   - No prior test changes.
4. **GREEN.**
   - `routes/oauth_connections.py`: an optional `expected_status: Literal["pending", "error"]`
     query parameter on `delete_connection`, passed to `_delete_connection`. After
     `claim_for_connection`, a row `effective_pair_of` names is refused; with the parameter,
     `mark_revoked` runs only after `lock_if_status` locked the row in that status. The 409 is
     raised inside the transaction.
   - `core/provider_access/connection_native.py`: `lock_if_status`, a locking read of the row in
     the expected status, beside `lock_lower_addressers` (the own-row lock of the one id order).
   - Without the parameter the path is unchanged.
5. **Gates.** `uv run .claude/scripts/run_gates.py aigateway --base origin/main`, and the
   PostgreSQL lane with `AIGW_TEST_PG=1` where Docker runs; the ledger records whether it ran.
6. **Review, ledger outcome, PR-open and close** as in §2 steps 7-10: the L7c leaf under
   `OME-1138` with labels `aigateway`, `agentic`, `autonomous`, blocking L7b; branch
   `OME-N-stale-row-conditional-delete`; the release note says a Connection delete can require
   the row's status.
7. **Then L7b** (§3): its ledger records the decision; every stale-row repair `DELETE` carries
   `expected_status`, `disconnect` of `E` does not; a fake gateway that activates the stale row
   at the `DELETE` pins `ConnectionConflict` with no create and the key in no request. L7b's
   PR-open follows L7c's merge, rebased.
8. **L9** waits for L7c, then regenerates the UI schema and re-checks the byte match.

## 4. Risks

- **Version skew.** A new Engine against an older gateway falls back to the label rule for one
  release; a listing with the field on some rows only is a bad response. An older Engine against
  the new gateway ignores the field: `_validate_row` reads named keys only.
- **One more request per Local listing** (`/v1/provider-access`), and one after each `connect` and
  `disconnect`.
- **The label collision** (the spec's accepted limitation): with no `E`, `connect` re-keys in place
  an `error` API-key row the user named `screamingface`, and the stale-row repair removes any other
  non-active row of that name.
- **Open points.** None: the owner settled the spec's §8 on 2026-11-02 and the no-auth listing
  rule on 2026-11-03.

## 5. Not in this plan

Promote-on-write; the Hosted adapter; the gateway UI (L9) and the catalog (L3); removing the skew
fallback, which is its own change in the release after L7b.
