---
ticket: OME-1497
stack: aigateway
status: done   # planned | in_progress | done | blocked
started: 2026-10-14
finished: 2026-10-14
---

# g1-pair-admin-mutations — pair-addressed PUT and DELETE through the bridge (G1, part 2 of 3)

## Intent

Second PR of the G1 successor of the D18 contract
(`docs/spec/2026-10-02-provider-credential-admin-contract.md` §5, §5.1, §5.2, §6, §6.1, §7, §8;
plan section C). It adds `PUT /v1/admin/accounts/{account_id}/connections/{provider}/api-key` and
`DELETE /v1/admin/accounts/{account_id}/connections/{provider}` over the ordered pair table that
part 1 (#1397) introduced for LIST. A single-candidate `none` pair (rows 8-10) is adopted at
mutation time: PUT validates the key, then publishes `migrated` with an active API-key Connection;
DELETE ends the pair as `migrated` with a null reference, without a dummy Connection. Rows 3, 4
and 11 answer 409; part 3 adds the legacy OAuth shadow identity proof for row 11. The LIST read race recorded in
part 1 is closed by part 1's own hardening commit, which this branch is rebased on.

Stacked on part 1 (`OME-1497-g1-pair-admin-list`); rebased on `main` once that merges. Release
order unchanged: merged only after the G0 deployment.

## Planned changes

All under `apps/aigateway/src/aigateway/` unless noted.

- `core/provider_access/pair_admin_writes.py` (new): `set_pair_api_key` and `delete_pair` —
  capture the pair after key validation (marker first, then candidates), classify with
  `classify_pair`, refuse rows 3/4/11 and an unknown provider, then write in one transaction
  fenced on the captured generation (§5.3: a stale mutation is never retried on a freshly read
  generation), re-checking the live Connections after the claim.
- `core/provider_access/connection_admin.py`: extract the migrated publication body of
  `set_api_key` into a method the bridge reuses (behaviour of the legacy facade unchanged).
- `core/provider_access/pair_admin.py`: public `read_marker` and `connection_credential` for the
  mutations (the LIST fence itself is part 1's).
- `core/provider_access/types.py`: typed refusal `PairNotManageable(provider, kind)`.
- `core/pending_auth.py`: `pop_for_pair` — post-commit cleanup scoped to the pair's captured
  targets (§5.2).
- `core/admin_connection_schemas.py`: `SetAdminConnectionApiKeyRequest` (`additionalProperties:
  false` in OpenAPI).
- `routes/provider_access_http.py`: successor rows for superseded (409
  `credential_publication_superseded`), retry exhaustion (503 `credential_write_conflict`) and the
  pair 409s; legacy rows unchanged.
- `routes/admin_connections.py`: PUT and DELETE, the auth-dependent body prevalidation (§6.1:
  `defaults_not_accepted`, `unsupported_credential_fields`, `invalid_credential_request`).
- Tests: `tests/unit/core/provider_access/test_pair_admin_mutations.py`,
  `tests/unit/test_admin_connections_mutation_routes.py`,
  `tests/integration/test_pair_admin_mutations_postgres.py`.

## Test plan

RED first:

- Core, per row: 5 (replace on the effective row, `pending`/`error` included), 6 (PUT reuses one
  leftover document as the mirror and the pair stays unambiguous; DELETE 204 no-op), 7 (PUT
  creates a fresh Connection at the `default` address with a `default` mirror; DELETE 204 without
  a marker), 8 (post-copy legacy key → PUT adopts the Profile address; DELETE removes the document
  and the blob, no dummy Connection), 9 (Connection-only, `pending` included → PUT keeps id and
  locator and adds a `default` mirror; DELETE revokes and removes the blob), 10 (same locator),
  3/4/11 and migrated-null-with-a-live-row → 409 with nothing written, unknown provider → 404,
  row 2 → 503 authority. Failed key validation leaves marker, documents, rows and blobs unchanged.
  A second candidate created during validation → 409 ambiguous. A stale legacy writer that read
  `none` before the bridge loses. Repeated PUT keeps one effective row; repeated DELETE is 204.
  A blob another live owner needs is kept. Post-commit cleanup pops only the pair's flows.
- Route: 422 matrix (invalid JSON, non-object, missing/blank/non-string key, unknown member,
  `defaults` incl. `null`) with exact bodies and no echo; 200 DTO; 204; 409/503 bodies;
  `no-store` on all of them; `X-Profile`; audit actor and final status; OpenAPI names and
  `additionalProperties: false`; legacy operations and the three legacy conflict bodies unchanged.
- PostgreSQL: two first creates on one pair → exactly one commits, no orphan row or blob; PUT vs
  DELETE; a bridge vs a legacy PUT on the same `none` pair.

## Acceptance

- Every §5 row has a mutation test; the §8 falsifiers in scope pass (the shadow proof is part 3).
- `uv run .claude/scripts/run_gates.py aigateway --base origin/main` green; PostgreSQL lane green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, under `apps/aigateway/`: new
  `src/aigateway/core/provider_access/pair_admin_writes.py`; changed `connection_admin.py`
  (`publish_api_key` extracted, `live_connection_ids` + the in-claim live re-check), `pair_admin.py`
  (public `read_marker` / `connection_credential`), `types.py`
  (`PairNotManageable`), `provider_access/__init__.py` (exports), `core/pending_auth.py`
  (`pop_for_pair`), `core/admin_connection_schemas.py` (`SetAdminConnectionApiKeyRequest`),
  `routes/provider_access_http.py` (successor superseded / write-conflict / pair 409 rows),
  `routes/admin_connections.py` (PUT, DELETE, body prevalidation). Tests: the three planned files
  (`test_pair_admin_disposition.py` only has its note prefix changed).
- **Commits:** `feat(aigateway): add pair-addressed admin PUT and DELETE through the mutation bridge` (one commit, stacked on part 1).
- **Gates:** `uv run .claude/scripts/run_gates.py aigateway --base origin/main` — ALL GATES GREEN
  (append-only, ruff, format, pyright, no-enterprise, pytest with coverage ≥ 80). PostgreSQL lane
  (`AIGW_TEST_PG=1 uv run pytest -m needs_postgres`): 69 passed, including the 5 new bridge races;
  5 failures in `test_cache_snapshot_upload_postgres.py` are local-environment only (the host
  `pg_dump` 15 refuses the newer test server) and untouched by this change. Mutation spot-checks:
  removing the PUT live re-check, the DELETE live re-check, or the row 3/4/11 refusal each turns a test red.
- **Deviations:**
  - The PUT declares no body parameter; the body is read by an auth-dependent dependency and the
    schema is published through `openapi_extra` (inline, `additionalProperties: false`). Reason:
    FastAPI parses a declared body before it solves dependencies, so malformed JSON would answer
    422 before 401/403 and its validation error would carry the input (§6.1: auth first,
    secret-safe 422).
  - The successor renders both legacy superseded subjects as one 409
    `credential_publication_superseded`; retry exhaustion is 503 `credential_write_conflict`.
  - DELETE removes a row-8 blob at its Profile address directly (like the Connection branch)
    instead of building a credential strategy, so no new strategy build site exists.
  - A `pending` row recovered by PUT reports the real `last_refreshed_at` set at completion; the
    RED test that expected `None` was corrected within this unit.
  - Review against the installed FastAPI 0.141.1, Pydantic 2.13.5 and Tortoise 1.1.8 (and their
    docs) found and fixed three defects, each test-first:
    1. The raw-body read ignored FastAPI's strict Content-Type default (0.132+): a body with no or
       a non-JSON Content-Type was parsed, the cross-site no-preflight shape the default blocks. It
       now answers 422 `invalid_credential_request`; `; charset=` and `+json` are accepted as in
       FastAPI.
    2. The request model's docstring (an internal note) was published as the OpenAPI
       `description`; the note moved to a comment.
    3. A storage outage inside a mutation (the write transaction, or DELETE's document read)
       surfaced as a bare 500 without `no-store`. It is now 503 `credential_store_unavailable`
       (existing body, `Retry-After`), or `credential_store_read_unavailable` for the read; the
       transaction rolls back whole, so a retry is safe.
  - Note comments added by G1 (parts 1 and 2) use a plain `NOTE:` prefix.
  - Rebased onto part 1's hardening commit (`fix(aigateway): harden pair admin inventory`). Its LIST
    generation fence replaces the one drafted here (a pair that keeps moving is a whole-request
    store-read 503 there), so the drafted fence and its two tests were dropped. The PUT DTO now
    sets the required `masked_key_hint` explicitly.
  - Following part 1's route hardening, the PUT and DELETE paths also authenticate and audit every
    other standard method (405 with `Allow`) and their trailing-slash form (307 to the canonical
    path), all with `no-store`; Starlette's own 405 and redirect bypassed all three.
