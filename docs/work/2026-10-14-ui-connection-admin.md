---
ticket: OME-1498
stack: aigateway-ui
status: done   # planned | in_progress | done | blocked
started: 2026-10-14
finished: 2026-10-14
---

# ui-connection-admin — Admin UI credential management on the pair-addressed Connection API

## Intent

Admin UI landing of D18 (`docs/spec/2026-10-02-provider-credential-admin-contract.md` §2-§4, §7,
§8; plan section D). The Gateway G1 API is merged and deployed (#1397, #1405, #1408). The console's
account page, attach/replace form and detach control move from the name-addressed legacy Profile
admin routes to `GET/PUT/DELETE /v1/admin/accounts/{account_id}/connections…`. The Profile name
field, the Name column, every name binding and the `default` fallback are removed; LIST `conflicts`
are rendered; the Label column becomes the always-`null` `masked_key_hint`; successor error codes
are dispatched before the status fallback. Owner decision 2026-10-14: the legacy UI code is
removed, not kept beside the new code, and the prior tests that pinned it are rewritten to the new
contract with their protective invariants carried over.

## Planned changes

All under `apps/aigateway-ui/src/`.

- `lib/aigateway/schema.d.ts`: regenerated with the pinned `openapi-typescript` 7.13.0 from the
  Gateway OpenAPI at `origin/main` `3bfa2fd24` (G1 complete); never edited by hand.
- `lib/aigateway/client.ts`: `listConnections`, `setConnectionApiKey`, `deleteConnection` replace
  `listProfiles`, `setApiKey`, `deleteProfile`; successor codes classified first (§7).
- `lib/auth.ts`: `describeFailure` for the new kinds (superseded, ambiguous, unresolved, temporary);
  non-retryable codes never read "try again".
- `app/actions.ts`: `setConnectionApiKeyAction` (no name, no fallback) and `deleteConnectionAction`
  (account and provider only).
- `app/accounts/[id]/`: connections table and conflicts list in `detail.tsx`, the detach control,
  `page.tsx` on `listConnections`; `credentials/new/form.tsx` without the name field.
- Tests rewritten or added beside each module.

## Test plan

- Client: exact paths with encoded segments, PUT body exactly `{api_key}`, DELETE 204, LIST shape;
  code-first classification for every §7 code; a bare or configuration 503 stays `unavailable`;
  legacy `profile_index_conflict` stays retryable.
- Actions: no name posted or forwarded, key never returned (scrub), kind carried, delete bound to
  account and provider only, revalidation only on success.
- Page and detail: connections rendered by provider with no name or label, `masked_key_hint` shown
  or dashed, conflicts listed with guidance per code, empty state, 404, refusal, bug rethrow.
- Form: no name control, write-only key, provider fallback, failure placement.

## Acceptance

- `npm run lint`, `npm run lint:css`, `npm run typecheck`, `npm run test:ci` green; `next build`
  succeeds.
- No source references `listProfiles`, `setApiKey`, `deleteProfile`, a profile name or the
  `default` fallback.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** under `apps/aigateway-ui/`:
  - `src/lib/aigateway/schema.d.ts`: regenerated with `openapi-typescript` 7.13.0
    (`node_modules/.bin/openapi-typescript openapi.json -o src/lib/aigateway/schema.d.ts`) from
    the Gateway OpenAPI exported at `origin/main` `3bfa2fd24` (`app.openapi()` of
    `aigateway.main:app`), sha256 `cd1adf5d822ff8363e23af963454c54c7330192d6dd1fcd420cff33d6c287c96`.
    Additive only.
  - `src/lib/aigateway/errors.ts` (new, 120 lines): the error taxonomy moved out of `client.ts`
    (which would have reached 461 lines), with four new kinds (`superseded`, `ambiguous`,
    `unresolved`, `temporary`) and a code table consulted before the status fallback.
  - `src/lib/aigateway/client.ts`: `listConnections`, `setConnectionApiKey`, `deleteConnection`
    replace `listProfiles`, `setApiKey`, `deleteProfile`; re-exports `AdminApiError` and
    `AdminErrorKind` so no importer changed.
  - `src/lib/auth.ts`: `describeFailure` copy for the four new kinds.
  - `src/app/actions.ts`: `setApiKeyAction` without a name or `default`;
    `deleteConnectionAction(accountId, provider)` replaces `deleteProfileAction`.
  - `src/app/accounts/[id]/`: `detail.tsx` (credentials table by provider with a Key hint column,
    `describeCredentialState`, new `CredentialConflicts`), `detail.module.css`, `page.tsx`,
    `delete-connection-button.tsx` (replaces `delete-profile-button.tsx`),
    `account-status-control.tsx` (copy), `credentials/new/form.tsx` (no name field) and
    `credentials/new/page.tsx` (copy).
  - `CLAUDE.md`: the write-only key guardrail no longer promises a masked `account_label`.
  - Tests: new `src/lib/auth.test.ts`; rewritten `client.test.ts`, `client-log.test.ts`,
    `actions.test.ts`, `detail.test.tsx`, `page.test.tsx`, `credentials/new/form.test.tsx`;
    one case appended to `credentials/new/page.test.tsx`. Approval manifest
    `.claude/test-change-approvals/OME-1498.json`.
- **Commits:** see the PR.
- **Gates:** `uv run .claude/scripts/run_gates.py aigateway-ui --base origin/main` → ALL GATES
  GREEN (append-only check through the OME-1498 manifest, npm ci, lint, lint:css, typecheck,
  build, test:ci; 20 files, 300 tests after the review fixes). Browser smoke: against a local Gateway built from
  `3bfa2fd24` (SQLite, header auth) the empty list rendered and a key PUT through the form reached
  `PUT …/connections/openai/api-key`, answered 422 and showed the provider refusal with the key
  field empty; against a mocked Gateway the table, Key hint dash, conflict list, a 204 DELETE and a
  409 superseded DELETE (reload guidance, no "try again") rendered as tested.
- **Deviations:**
  - A 409 with an unknown code still falls back to the retryable `conflict` kind, so routes outside
    D18 (for example account creation) keep their existing advice.
  - `credential_store_unavailable` was classified `unavailable` ("Admin API is not enabled") on
    every route before; it is now `temporary` everywhere, which is what the code means.
  - `setApiKeyAction` and `CredentialsTable` keep their names; only their contracts changed.
  - No success-path PUT in the smoke: a real provider key was not used.
- **Review fixes (before commit):**
  - The provider key check's codes are classified by code: `api_key_permission_denied` and
    `api_key_no_quota` → `invalid`, `api_key_validation_rate_limited` and
    `api_key_validation_unavailable` → `temporary`, `api_key_validation_misconfigured` → `unknown`.
    By status they read as "not an administrator" (403) or "admin API disabled" (503).
  - `temporary` now shows the gateway's own message, so a storage outage and a key check that
    could not run are told apart.
  - `segment()` refuses `""`, `.` and `..` before any request: encoding does not stop a dot
    segment from collapsing into its parent path.
  - A page test pins the Detach bind order (account, then provider).
  - `CLAUDE.md`: the OAuth guardrail now says OAuth connections are listed and can be detached.
  - Not changed: `README.md` still says "finds a profile"; left for a follow-up.
