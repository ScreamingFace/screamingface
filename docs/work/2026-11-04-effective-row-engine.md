---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: screamingface-engine
status: in_progress   # planned | in_progress | done | blocked
started: 2026-11-04
finished:
---

# effective-row-engine — OME-1138 close-out L7b: the Local Engine selects the effective Connection

## Intent

Leaf L7b of the OME-1138 close-out (close-out spec §4.7, P-F2; spec
`docs/spec/2026-10-29-local-engine-effective-row.md` §3-§5 and plan
`docs/plan/2026-10-29-local-engine-effective-row.md` §3, both merged in #1658). The Local Engine
works on the row labelled `screamingface`, while chat uses the row the default resolve serves, so
it can list `connected` while chat refuses, or delete a row chat does not use. L7a (#1660) made
`GET /v1/oauth/connections` mark that row `effective`. L7b makes the Local Engine select the
`effective` row, take every Local status from `GET /v1/provider-access` (the answer the Hosted
Engine already shows), write by spec §3's create and repair table, and fall back to the label rule
for one release against a gateway that predates the field. The label `screamingface` stays as the
label of an Engine create and the mark the stale-row repair reads; it is never read for selection.

L7b is blocked by L7c (owner decision 5, 2026-11-04): the stale-row repair deletes through the
gateway's conditional delete (spec §2a), so its PR opens after L7c merges, rebased.

## Planned changes

Engine src (`apps/screamingface-engine/src/screamingface_engine/connections/`):

- new `aigateway_rows.py`: the row rules — selection of `E`, the listing checks, the create and
  repair decisions, the stale-row repair set, and the version-skew fallback with a `WHY` naming its
  removal in the release after L7b ships;
- `aigateway.py`: `_ConnectionRow` records `effective` (present or absent); `_validate_row` accepts
  a boolean or its absence and refuses any other value; Local `list` reads the rows and
  `/v1/provider-access`; `connect`, `start_oauth` and `disconnect` follow the table; `connect` and
  `disconnect` return the provider-access status read after their writes; `connect` drops its label
  check; `_select` is replaced; `_MANAGED_LABEL` stays.

Tests (`apps/screamingface-engine/tests/unit/`):

- new `test_connections_aigateway_effective.py` and `test_connections_aigateway_version_skew.py`;
- prior tests that change are listed at RED, approved by the owner before GREEN, and pinned in
  `.claude/test-change-approvals/OME-N.json`.

No gateway change, no model change, no migration. The Hosted adapter (`mutable=False`) is
unchanged.

## Test plan

RED first, per plan §3 step 3:

- every row of spec §3's create and repair table, including `E` `pending` → `ConnectionConflict`
  on `connect` and `start_oauth`, API-key `E` in `active` or `error` re-keyed in place, in
  `revoked` replaced by a `POST`;
- `list` shows the provider-access status (`needs_reauth` and `error` on an `active` `E`,
  `not_connected` for a provider absent from it); `E` adds `auth_method` and `account_label`;
- the listing checks raise `ConnectionBadResponse` (the field on some rows only; two flagged; one
  `active` and none flagged, for a listed provider);
- a stray `active` row of an unlisted (no-auth) provider is ignored;
- a malformed provider-access body, an unreachable gateway and a timeout map to
  `ConnectionBadResponse`, `ConnectionUnavailable` and `ConnectionTimeout`;
- `connect` and `disconnect` return the status read after the writes;
- the stale-row repair removes only non-active `screamingface` rows and is idempotent;
- decision 5: every repair `DELETE` carries `expected_status`, the status listed; a row that
  turns `active` as its `DELETE` arrives → `ConnectionConflict`, no create or start, the key in no
  request; `disconnect` of `E` carries no condition;
- the accepted collision with a user row labelled `screamingface`, pinned;
- 409 `label_conflict` → `ConnectionConflict`; an in-place `PUT` on a row under the user's label is
  accepted;
- version skew: no row carries `effective` → the label rule, logged once per process; the status
  still from `/v1/provider-access`; zero rows read the same under both rules.

## Acceptance

- The new suites pass; every prior Engine test passes, changed only as the owner approved.
- `uv run .claude/scripts/run_gates.py screamingface-engine --base origin/main` all green.
- The Hosted adapter's suite is unchanged.

## Outcome (fill at the end — required before COMMIT)

- **Actual files (under `apps/screamingface-engine`, plus this ledger and the spec):**
  - src (2): the new `connections/aigateway_rows.py` (`ConnectionRow`, `MANAGED_LABEL`,
    `select`, `api_key_plan`, `oauth_start_plan`, `disconnect_plan`, the repair before a create
    that replaces an unusable `E`, the skew fallback and its once-per-process notice; 214 lines) and `connections/aigateway.py` (the Local listing and every write on
    the rules, statuses from `/v1/provider-access` read after the writes, `_validate_row` reads
    `effective`, `_select`, `_public` and `_disconnected` gone; 437 lines).
  - new tests (3, plus one support module): `aigateway_effective_support.py` (the fake gateway
    and row builders the two effective suites share), `test_connections_aigateway_effective.py`
    (the listing, its checks and the provider-access failures; 17 cases),
    `test_connections_aigateway_effective_writes.py` (`connect`, `start_oauth`, `disconnect`; 40)
    and `test_connections_aigateway_version_skew.py` (7). The effective cases were one 583-line
    file until review; they were split to keep each file under 450 lines.
  - decision 5 (a second commit): `test_connections_aigateway_conditional_repair.py` (13 cases);
    the fake gateway of `aigateway_effective_support.py` honours `expected_status` (422 for a
    value the gateway does not take, 409 for a row no longer in that status or effective) and
    can activate a row as its `DELETE` arrives (`activate_at_delete`). In src, `Plan` splits
    `retire` (`E`, a plain `DELETE`) from `repair` (stale rows, each `DELETE` with
    `expected_status`); the stale set is the `pending` and `error` rows (`_STALE`). The adapter
    is 447 lines, the rules 219.
  - prior tests changed with the owner's approval (2026-11-04), each fake now answering
    `/v1/provider-access`: `test_connections_aigateway.py` (the shared `_get` and the handlers of
    12 tests), `test_connections_provider_access_availability.py`
    (`test_an_explicitly_mutable_adapter_keeps_the_local_listing_and_its_mutations`: its
    INVARIANT and the expected paths), `test_profile_env_characterisation.py` (the fake,
    `test_a_single_non_active_managed_row_is_not_a_conflict`, and the docstring naming the label
    rule's new home), `test_traceparent_propagation.py` (`_RecordingUpstream`, which three tests
    share, and its docstring). No test was retired. Pinned in
    `.claude/test-change-approvals/OME-N.json` at PR-open.
  - spec `docs/spec/2026-10-29-local-engine-effective-row.md` §3, amended by owner decision 3:
    the table row for an unusable `E`, the stale-row repair and the accepted limitation; and by
    decision 5: the conditional repair, its `pending` and `error` set, and `disconnect` of `E`.
- **Commits:** two on branch `effective-row-engine` (the effective row; then decision 5), renamed
  `OME-N-effective-row-engine` at PR-open; their shas are recorded then.
- **Owner decisions (2026-11-04):**
  1. The prior-test changes listed at RED (the four files above) are approved.
  2. Under the skew fallback the label row stands in for `E`. With no `screamingface` row and
     exactly one active row of the user's, `connect` creates as before L7b. With two or more
     active rows, `connect`, `start_oauth` and `disconnect` raise `ConnectionConflict` before any
     write, as the table's "no `E`, `A` ≥ 2" row. Spec §4 does not say either.
  3. Over an unusable `E` that a labelled create replaces, `connect` and `start_oauth` first
     remove the provider's non-active `screamingface` rows other than `E`, and refuse with
     `ConnectionConflict`, before any write and before the key leaves, when an `active` row other
     than `E` holds the label. Without this, a row a pre-L7b Engine created beside a migrated `E`
     made every create return 409 `label_conflict` (`routes/oauth_connections.py:136-152,263-272`)
     until a disconnect. Spec §3 is amended to match.
  4. The removal of the skew fallback is filed at PR-open as a deferred leaf under `OME-1138`
     (`screamingface-engine`, `agentic`, `deferred`; precondition: an Engine release that
     carries L7b).
  5. After the second review, which found the repair could delete a row an OAuth callback or a
     key write activated between the listing and the `DELETE`: the gateway gains a conditional
     delete in its own leaf, L7c (`?expected_status=pending|error`, spec §2a), and every repair
     `DELETE` here carries the status the listing showed. A 409 is `ConnectionConflict`, raised
     before any create or start. `disconnect` of `E` stays a plain `DELETE`. L7b is blocked by
     L7c.
- **Review (independent, read-only):** nothing blocking. Added after it: the skew conflict for
  two active rows (three cases), a written row of another provider, `disconnect` deleting only
  `E` when stale rows exist, and an `E` whose method the catalogue lacks. Each of these four
  mutations survived the suites before and fails one now. Its question on an old
  `screamingface` row beside an unusable `E` became owner decision 3.
- **RED seen:** the skew suite could not import `aigateway_rows`; 38 of the 48 effective cases
  failed: the status came from the row's lifecycle, the listing checks never raised, the row was
  picked by its label, the repair never ran and no status was read after a write. The other 10
  pin behaviour that already matched the table (an in-place `PUT` on the labelled row, a create
  with nothing to repair, 409 `label_conflict`). For decision 3, the six new cases failed
  before its change: no removal before the create, and no refusal when an active row held the
  label. For decision 5, 10 of the 13 new cases failed before its change: the `DELETE` carried
  no condition, so the fake removed the activated row and the create followed, and an `expired`
  labelled row was deleted. The other 3 pin that `disconnect` of `E` sends no condition.
- **Prior tests that failed under GREEN before their approved change:** exactly the 17 of the
  approved set (12 + 1 + 1, and the three traceparent tests through their shared fake).
- **Gates:** `run_gates.py screamingface-engine --base origin/main` (base `52d9492aa`,
  2026-11-04) with `--skip-append-only`: ruff, format, pyright, the layering check and pytest with
  coverage passed (6837 passed, 168 skipped). The append-only check lists the four approved files
  until the manifest exists. After review and owner decision 3, the same gate commands, run one
  by one (a first runner pass hung inside pytest and was stopped; the rerun took 51 s): ruff,
  format, pyright and the layering check clean; pytest 6849 passed, 168 skipped, coverage 96%.
  For decision 5, the same commands one by one: ruff, format, pyright and the layering check
  clean; pytest 6862 passed, 168 skipped, coverage 95.99%. Each of three mutations fails the new
  suite: a repair `DELETE` without its condition (9 cases), the stale set back to every
  non-active row (1), a condition on the `DELETE` of `E` (9).
- **Deviations:**
  - `_ConnectionRow` moved to `aigateway_rows.py` as `ConnectionRow`, with `MANAGED_LABEL`, so the
    rules and the adapter share one row type; `_validate_row` stays in the adapter.
  - Under the skew fallback, with no `screamingface` row and exactly one active row of the
    user's, `connect` creates as today (owner, 2026-11-04); the table has no such row because
    the gateway's flag makes it a bad response.
  - The changed prior tests are four files, not the plan's two: the characterisation and
    traceparent fakes answer every non-catalogue read with the row listing too.
  - Spec §3 changed after its merge in #1658 (owner decision 3); the amendment ships in this
    unit's PR.
  - Decision 5 narrows the stale set from the non-active labelled rows to the `pending` and
    `error` ones, the only values the gateway's conditional delete takes. Every reachable state
    reads the same: an OAuth `error` row and every `revoked` row carry a placeholder label, and
    nothing writes `expired`. A labelled `expired` row would now meet `label_conflict` instead of
    a 422. Spec §3 says so.
  - Close-out spec §8 says that after L7b the Engine's selection no longer reads the label. That
    holds against a gateway that lists `effective`; the §4 skew fallback still selects by
    `MANAGED_LABEL` for one release, and its removal in the release after L7b completes the line.
