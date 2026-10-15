---
ticket: OME-1497
stack: aigateway
status: done   # planned | in_progress | done | blocked
started: 2026-10-13
finished: 2026-10-13
---

# g1-pair-admin-list — the pair-addressed Connection LIST (G1, part 1 of 3)

## Intent

First PR of the G1 successor of the D18 contract
(`docs/spec/2026-10-02-provider-credential-admin-contract.md`; plan section C). G1 ships as three
PRs, like G0: (1) the ordered pair disposition and `GET /v1/admin/accounts/{account_id}/connections`
with the neutral DTO and the new-route hygiene; (2) PUT and DELETE through the mutation bridge
(rows 5-10); (3) the legacy OAuth shadow identity proof (row 11). This part is read-only: it adds
no writer, advances no marker and never reads or decrypts a provider credential.

Release order (OME-1497 checklist): G0 merged → G0 deployed → G1 merged → G1 deployed. This PR is
reviewed now and merged only after the G0 deployment.

## Planned changes

All under `apps/aigateway/src/aigateway/` unless noted.

- `core/provider_access/pair_admin.py` (new): the §5 ordered disposition over one pair's marker,
  legacy documents and live Connections (`classify_pair`), the per-provider LIST projection, and
  `pair_inventory(app, account_id)` — three reads, no write, no secret read.
- `core/provider_access/types.py`: typed refusals `CredentialStoreReadUnavailable` (row 1) and
  `CredentialAuthorityUnavailable` (row 2).
- `core/provider_access/pair_authority.py`: `PairAuthorityStore.providers(account_id)` — the
  marked providers without parsing their state, so an unknown state is refused per provider.
- `core/provider_access/__init__.py`: export the new names.
- `core/admin_connection_schemas.py` (new): `AdminConnectionOut`, `AdminConnectionConflictOut`,
  `AdminConnectionList`.
- `routes/provider_access_http.py`: the successor rendering scope (§7) — store-read and authority
  503s and the per-provider conflict body; legacy rows unchanged.
- `routes/admin_connections.py` (new): the thin router, `AdminConnectionsRoute` (audit plus
  `Cache-Control: private, no-store` on every response, errors included), the auth-first
  `X-Profile` refusal.
- `main.py`: register the router.
- Tests: `apps/aigateway/tests/unit/core/provider_access/test_pair_admin_disposition.py`,
  `apps/aigateway/tests/unit/test_admin_connections_list_route.py`.

## Test plan

RED first:

- Disposition rows (core, over real stores): empty pair → nothing; row 8 Profile-only
  (authenticated → `active`, `pending`, `error`; `last_refreshed_at` from the owner); row 9
  Connection-only (`active`/`pending`/`error`); row 10 same locator → the legacy owner; row 11
  different locators → unresolved; row 3 two documents or two live Connections → ambiguous
  whatever the marker; row 4 quarantined → unresolved; row 5 migrated → the effective row
  (`pending` included); row 5 with a referenced revoked or missing row → 503 authority; row 6
  migrated null reference with or without leftover documents → nothing; unknown provider →
  unresolved; row 2: unknown marker state, unknown Connection status or auth type, malformed or
  out-of-scope locator → 503 authority; row 1: an index read failure → 503 store-read.
- Route: admin only (401/403 keep their bodies); unknown account 404; sorted arrays; the DTO has
  exactly the five fields and `masked_key_hint` is `null`; no name, id, defaults or key on the
  wire; a conflict body is `{code, message, provider}`; a store failure is `{code, message}` with
  no partial list; nonblank `X-Profile` (repeated, `default`) → 400 `x_profile_unsupported`,
  blank → ignored; `Cache-Control: private, no-store` on 200, 400, 401, 403, 404, 422 and 503;
  audit line names the actor and the final status; LIST leaves the marker and the database
  unchanged; OpenAPI names (`list_admin_account_connections`, the three schemas, `Admin` tag,
  admin security) and the legacy operations unchanged.

## Acceptance

- Every §5 row has a test; LIST never writes, never decrypts, never refreshes.
- `uv run .claude/scripts/run_gates.py aigateway --base origin/main` green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `core/storage_outages.py` (review fix). The core test file
  is `tests/unit/core/provider_access/test_pair_admin_disposition.py`, the route file
  `tests/unit/test_admin_connections_list_route.py`; 71 tests together after the review.
- **Commits:** `feat(aigateway): list an account's provider credentials by pair (G1 1/3)`, rebased onto `main` after G0 3/3 (#1396) merged.
- **Gates:** `uv run .claude/scripts/run_gates.py aigateway --base origin/main` — ALL GATES GREEN
  (append-only, ruff check/format, pyright, no-enterprise, pytest with coverage >= 80%); full
  suite 5633 passed, 106 skipped after the review fixes and the rebase. RED: every new test failed before the implementation (route
  404, missing names). The PostgreSQL lane is not needed for this part: LIST takes no lock and
  writes nothing; the concurrency claims arrive with PUT/DELETE (part 2).
- **Mutation checks, each caught:** the locator scope check off (4 tests fail); a referenced row
  replaced by another live row (1); quarantine ignored (1); the same-locator proof skipped (1);
  `no-store` missing on errors (7); only the first `X-Profile` judged (1); a store failure read as
  an empty inventory (2); a broad catch turning a bug into an outage (1).
- **Deviations / decisions to confirm with the owner:**
  - A `migrated` pair with a null reference AND a live Connection matches no row of the table;
    it is listed as `credential_pair_unresolved` (row 11, "any other unresolved combination").
  - An unreadable or invalid metadata index (an unknown Profile state included) refuses the whole
    LIST as `credential_store_read_unavailable`: the index is one document per account, so the
    failing provider cannot be named.
  - A malformed or out-of-scope locator on any live candidate (a migrated effective row included)
    is row 2, before row 3; the read path's UUID fallback is never used here.
  - A path validation error on the new route keeps the app-wide redacted 422 body and gains the
    `no-store` header; the successor's own 422 codes are body codes and arrive with PUT.
  - Docs: the FastAPI route-class pattern was checked against the current official docs and the
    installed 0.141.1 source, and a direct probe confirmed that endpoint and router dependency
    refusals both pass through the route class.
- **Review (before commit) and its fixes:**
  - Fixed: a database outage answered a bare 500 without `no-store` — the account lookup ran
    outside the successor scope, and Tortoise's asyncpg client passes a dropped connection, a
    server restart, an exhausted server or a socket timeout through as the driver's own exception.
    The account lookup now runs inside `store_reads()`, and `core/storage_outages.py` lists those
    driver failures; every read of LIST (account, index, Connections, markers) is tested with them.
  - Fixed: an unknown provider was decided before rows 2 and 3, so a marker left by a disconnect
    of an unregistered plugin showed as a conflict. Rows 2 and 3 now run first; an unknown
    provider with no candidate lists nothing.
  - Pinned: the "migrated, null reference, live Connection → unresolved" decision now has a test.
  - Recorded, not changed: (1) LIST's reads are separate, so a write committing between them can
    show a transient false conflict or 503; the mutations in part 2 decide whether LIST fences on
    the pair generation. (2) A genuine bug still answers the app-wide 500 without `no-store` —
    that handler runs outside the route and its body is generic. (3) An invalid value inside the
    index is a whole-account `credential_store_read_unavailable`, not `credential_authority_
     unavailable`: the index is one document, so the provider cannot be named. (4) Schema drift
     (a missing migration) is reported as unavailable, like any `OperationalError` today.

## Post-review correction — 2026-10-14

Independent review returned `NOT READY` on the ordered disposition, multi-read consistency and
response-hygiene boundaries. This correction will:

- run marker/reference/locator, ambiguity, quarantine and migrated-reference checks before the
  unknown-provider rendering decision;
- fence LIST with a bounded optimistic pair-generation snapshot, retry once when ownership changes
  across the candidate reads, then refuse the whole request as temporarily unavailable;
- render an unexpected route exception through the existing sanitized 500 handler inside the route
  wrapper so `private, no-store` remains mandatory without leaking exception text;
- narrow driver outage matching from every `OSError` to connection/timeout failures;
- make both nullable DTO fields required on the wire and in OpenAPI;
- align the normative contract with the owner-confirmed whole-account store-read refusal for an
  invalid unified Profile index, whose provider cannot be named safely.

Acceptance: every reproduced counterexample fails closed; a one-time concurrent generation move is
retried into a stable truthful view, persistent movement refuses; all prior tests plus focused race,
unexpected-500, outage-taxonomy and OpenAPI regressions pass; full Gateway gates and independent
security re-review are green.

Post-review outcome: ordered unknown-provider/quarantine/migrated checks are fail-closed, shipped
credential namespace aliases remain valid without a loaded plugin, persisted nonpositive generations
are refused, LIST retries one ownership-generation movement and rejects persistent movement, and every
standard method on the canonical/trailing path is authenticated, audited and `private, no-store`.
Verification: 636 provider-access/admin tests, 20 PostgreSQL writer/fence races, the real PostgreSQL
interleaving regression, and the full AIGateway gate pass. Independent pair-security and route-privacy
re-reviews both report `READY`; the latter exercised 36 method/path/auth combinations. No model or
migration changed.
