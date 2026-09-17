---
id: OME-706
linear_url: https://linear.app/openmined/issue/OME-706/add-v1admin-api-email-allowlist-plus-account-and-api-key-profile
status: done
type: task
priority: P1
labels: [aigateway, autonomous, agentic]
created: 2026-07-30
closed: 2026-07-30
---

# OME-706 — Add `/v1/admin` API: email allowlist + account and API-key profile management

The aigateway half of `OME-705`. **Blocked by `OME-684`** — imports
`core/auth/cloudflare_identity.py`, which exists only on PR #444's branch. No stacked PRs, so this
starts after that merges to `main`.

## Changes

1. **`config.py`** — `admin_emails: Annotated[frozenset[str], NoDecode]` from
   `AIGATEWAY_ADMIN_EMAILS`. `NoDecode` is mandatory: pydantic-settings JSON-decodes complex field
   types from the environment, so a comma-separated value fails as malformed JSON before any
   validator runs — the identical trap `allowed_networks` already documents. A `mode="before"`
   validator splits, strips and lowercases to match `CloudflareIdentity.username`.
2. **New `core/auth/admin.py`** — `AdminPrincipal`, `require_admin`, `CurrentAdmin`. Reuses
   `HEADER_USER_EMAIL`, `identity_from_headers`, `peer_in_networks` rather than re-deriving them.
   Checks in order: empty allowlist → 503 · `jwt` mode → 503 · untrusted peer → 403 *before the
   header is read* · no identity → 401 · not allowlisted → 403.
   **INVARIANT:** `require_admin` never calls `account_for_identity` — an admin is not a tenant.
3. **New `routes/admin.py`** — `prefix="/v1/admin"`, `AdminAuditRoute` mirroring
   `ProvisioningAuditRoute`. Accounts: `GET`/`POST` list+create, `GET`/`PATCH` by id. No `DELETE`
   (deactivate instead — a real delete cascades `oauth_connections` and orphans `credential_blobs`).
   Profiles: `GET` list, `PUT …/api-key` upsert, `PATCH`, `DELETE`. **API key only, no OAuth.**
4. **Schemas + OpenAPI** — admin routes declare `response_model=` (unlike the existing profile
   routes, which return bare `dict`), because a TypeScript client is generated from this schema.

## Key reuse — no new store code

`ProfileIndexStore` is already account-parameterized: `list(account_id, provider=None)`,
`get(account_id, provider, name)`, `upsert(profile)`, `remove(profile_id)`. Today's routes simply
always pass the caller's own id. Cross-account access is a different argument, not a different
store. The api-key write path in `routes/auth.py` is extracted to a shared helper called by both
the tenant route and the admin route.

## Test plan

New modules land inside the dedicated auth-surface coverage CI step (80% over
`aigateway.core.auth`). Pin: mode/allowlist gating (503s), untrusted peer 403 before header read,
missing/blank header 401, non-allowlisted 403 **with no `Account` row created**, mixed-case
allowlisted allowed, cross-account profile isolation, and that an API key never appears in any
response body or log record.

## Acceptance

`uv run .claude/scripts/run_gates.py aigateway` green, plus the three-curl check in the Linear
issue against a local `cloudflare_headers` instance.
