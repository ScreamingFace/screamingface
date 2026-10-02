---
ticket: OME-1398
stack: repo
status: completed
started: 2026-10-01
finished: 2026-10-01
---

# remove-stale-x-profile-guidance — align UI and diagrams with the selector sunset

## Intent

Remove stale operator and generated guidance that teaches credential selection through
`X-Profile`, while preserving the explicit 400 refusal at request ingress and leaving D18 and Stage
E untouched. The generated declaration remains reproducible from the local AIGateway OpenAPI.

## Planned changes

- Verify the local provider-access OpenAPI source already describes nonblank selectors as
  unsupported before regenerating its committed declaration.
- `apps/aigateway-ui/src/app/accounts/[id]/credentials/new/form.tsx` and `form.test.tsx` — replace
  the stale selection hint with effective-credential guidance.
- `apps/aigateway-ui/src/lib/aigateway/schema.d.ts` — regenerate with pinned
  `openapi-typescript` 7.13.0 from this working tree's OpenAPI.
- `docs/diagrams/gateway-identity.md`, `gateway-identity-flow.mmd`, and rendered flow assets — show
  selector-less resolution and the multi-active 409 path.
- The OME-1398 task mirror and this ledger.

## Test plan

- Confirm the provider-access OpenAPI description says nonblank `X-Profile` is unsupported, not
  ignored.
- RED: the credential form keeps the required legacy name but neither renders `X-Profile` nor
  presents the name as a request selector; it explains effective credential resolution.
- Regenerate `schema.d.ts` and verify its provider-access description matches the OpenAPI source.
- Render the Mermaid flow and verify the Markdown inline source, `.mmd`, SVG and PNG stay aligned.
- Run the complete AIGateway UI gate list plus focused AIGateway route tests and formatting checks.

## Acceptance

- No current Admin UI copy instructs an operator to send `X-Profile`.
- The generated schema states that nonblank selectors are unsupported.
- Markdown and Mermaid flows show selector-less pair resolution and explicit 409 ambiguity.
- Relevant checks pass with no D18, carrier-cleanup or Stage E changes.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** the credential form and its focused test; regenerated `schema.d.ts`; the gateway
  identity Markdown, Mermaid source, SVG and PNG; the OME-1398 task mirror and this ledger. No
  AIGateway Python source or test change was needed.
- **Commits:** `71192cf1c12cf7fd1d24bd0bd708f9455e594af7` —
  `fix(aigateway-ui): remove stale X-Profile guidance`; PR #1210 squash-merged as
  `57e78d71a9582b238ac4fe7cf0f682cb012c06a2`.
- **Gates:** `npm ci` succeeded; focused form suite 16 passed; ESLint 0 errors (two pre-existing
  unused-parameter warnings in `upload-form.test.tsx`); CSS lint, TypeScript, and Next production
  build passed; full Vitest 17 files / 238 tests passed with 89.43% statements and 90.55% lines.
  `openapi-typescript` 7.13.0 regeneration changed only the two stale provider-access description
  lines. Mermaid CLI 12.0.0 rendered SVG and 2x PNG; the PNG was visually inspected; inline/source
  consistency assertions and `git diff --check` passed.
- **Deviations:** `sdlc-react` is named by the stack card but unavailable; owner approved the
  general SDLC fallback with the exact declared UI gates. Owner also approved keeping the minimal
  AIGateway OpenAPI source correction in this issue if needed; current `origin/main` already has
  the corrected source, so no Python source or test change remains in the diff. The first Mermaid
  render exposed a sequence-label semicolon parse trap; replacing the separators with line breaks
  made both committed renders succeed without changing the intended content.
