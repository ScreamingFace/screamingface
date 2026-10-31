---
ticket: OME-1778
stack: aigateway
status: in_progress   # planned | in_progress | done | blocked
started: 2026-10-29
finished:
---

# availability-fold-in — provider availability follows the resolver (D17 fold-in, OME-1138)

## Intent

`GET /v1/provider-access` reports a status only for `migrated` pairs, while chat serves unmarked,
`none` and reference-less `migrated` pairs through their Connections by label. A provider
connected natively after the E4 census therefore answers chat and reads `not_connected` for the
Hosted Engine. The epic's end state asks for one resolver for chat and availability; epic spec
§3.3 op 6 deferred the fold-in as "a later flagged behaviour change", and no landing took it up.
The owner chose on 2026-10-29 to fold those pairs in (spec
`docs/spec/2026-10-29-availability-fold-in.md`, plan `docs/plan/2026-10-29-availability-fold-in.md`):
an ambiguous pair lists `error`, and there is no runtime flag.

## Planned changes

- `apps/aigateway/src/aigateway/core/provider_access/connection_backed.py`: one pure label
  selection shared by `resolve` and `availability`; `availability` applies spec §4 to every pair
  not served by its effective reference, listing the account's Connections once per call.
- Docstrings: `availability`, and the module docstring of
  `tests/unit/core/provider_access/test_provider_access_availability.py`.
- New `apps/aigateway/tests/unit/core/provider_access/test_availability_follows_resolve.py`; one
  test appended to `apps/aigateway/tests/unit/test_provider_access_availability_route.py`.
- Prior test changed (owner manifest at PR-open):
  `test_connection_only_resolve.py::test_availability_reports_a_non_migrated_pair_as_not_connected`
  keeps only its `quarantined` case.
- `docs/spec/2026-09-09-OME-1138-converge-connections.md` op 6: a dated line naming this leaf.
- No model, queryset or migration is authored, so the `tortoise-dev` companion does not apply.

## Test plan

- Agreement table over marker (absent, `none`, `migrated` without reference) and rows (one active
  OAuth, one active API key, two active, pending only, error only, revoked only, none): the spec
  §4 status, and `connected` exactly when the default resolve returns a stored target that
  `authorize` accepts.
- A missing credential record lists `needs_reauth` on every marker; a recorded `needs_reauth`
  outcome does on a reference-less `migrated` pair.
- The new path reads no secret, writes nothing, and lists Connections once per call.
- An unreadable Connection store propagates from `availability`.
- Route: a `none` pair with one active Connection lists `connected` through
  `GET /v1/provider-access`.

## Acceptance

- The agreement table and route test pass; every existing resolve, admission, model-parameters and
  route test passes unmodified; the one changed availability test is in the manifest.
- `uv run .claude/scripts/run_gates.py aigateway` passes; the `needs_postgres` suites pass.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus four docstring-only files so no comment states the retired
  rule: `core/provider_access/ports.py` (`availability`),
  `routes/provider_access_availability.py`, `tests/unit/remote_endpoint/test_app_catalog.py`
  (module docstring), and the section header in `test_connection_only_resolve.py`.
  `test_provider_access_availability.py` also lost the stale line that `needs_reauth` is never
  emitted in the window.
  At PR-open: the manifest `.claude/test-change-approvals/OME-1778.json` and the mirror
  `docs/tasks/2026-10-29-OME-1778-availability-fold-in.md`.
- **Commits:** pending: `feat(aigateway): list provider availability by the rule chat resolves by`.
- **Gates:** `run_gates.py aigateway --skip-append-only`: ALL GATES GREEN (ruff check, ruff
  format, pyright, check_no_enterprise, pytest with coverage ≥80; 7416 tests collected). The
  append-only check against `origin/main` flags only
  `test_connection_only_resolve.py:353`, the planned prior-test change; the owner manifest covers
  it at PR-open. `needs_postgres`: 67 passed. Engine adapter suites
  (`test_connections_aigateway.py`, `test_connections_provider_access_availability.py`): 68
  passed. RED before GREEN: 29 failures, each a `not_connected` where the table expects another
  status or a resolve that did not raise.
- **Deviations:** the spec gained "Accepted consequences (review, 2026-10-29)": a recorded
  `insufficient_credits` lists `error` while chat still dispatches; an OAuth row with a missing
  record lists `connected` until chat marks it; an abandoned OAuth start lists `pending` until the
  row is removed (the Hosted SDK shows `pending` as unavailable). The §5 invariant now says an
  unreadable credential record fails the request with 503. With `AIGW_LIVE=1`, live tests gated on
  `connected` now also run for providers connected natively after the census.
- **Review fix (2026-10-30):** `availability` read a `migrated` pair's reference before the
  no-auth guard, which sat only in `_label_status`, so a provider declaring only `none` with a
  legacy reference to an active row listed `connected` while resolve returned targetless. The
  guard now runs first in the listing, as in resolve. New test
  `test_a_no_auth_provider_lists_not_connected_beside_a_migrated_effective_row` (RED:
  `'connected' == 'not_connected'`). `run_gates.py aigateway --base a7e5d8577`: ALL GATES GREEN;
  `needs_postgres`: 67 passed.
