---
ticket: OME-1322
stack: aigateway-ui
status: in_progress
started: 2026-09-23
finished:
---

# OME-1322 — AIGateway UI: stop authoring saved Profile defaults

## Intent

This is Stage C of `OME-1138` (spec §3.7/§5): request parameters are supplied by the caller on each
request, and saved `ProfileDefaults` go away. This unit is the **UI-first** step. The Admin UI's
attach/replace-key form stops offering the "Defaults (optional)" fieldset, and the key write sends
exactly `{ "api_key": … }`, with no `defaults` property at all, not even `null`. The change is
compatible with the current gateway: `AdminSetApiKey.defaults` defaults to `None`, so an absent key is
treated like `null`, and both backings (`profile_admin.py`, `connection_admin.py`) *preserve* stored
values on `None`. Nothing is wiped. In dev, none of the 23 retained Profile documents holds a non-null
default.

## Plan refinement (recorded here, UI-first sequencing)

Plan §2 row S7 reads "Move the Admin UI onto the admin successor and drop the defaults fieldset at the
cutover" (depends on U3, D18, C). The owner-filed issue splits it, and this unit follows that split:

- **S7a** (this unit, `OME-1322`): drop the fieldset and the payload on the **existing** endpoint
  `/v1/admin/accounts/{id}/profiles/{provider}/{name}/api-key`. There is no new endpoint and no
  generated-schema edit.
- **S7b** (later): move the UI onto the admin successor. It stays gated on D18.
- **S11/C server part** (`OME-1323`, blocked by this unit): reject legacy writes carrying `defaults`
  and drop the defaults read/merge for the same body in both cache and dispatch. The cache-key
  version, algorithm, projections and adapter revisions stay unchanged.

The acceptance source is the owner's issue `OME-1322` ("UI only, first in the rollout"). No tracked
spec/plan text is changed in this unit, and the runtime diff is UI-only. A plan-row note is a
candidate for the `OME-1323` docs pass.

## Planned changes

- `apps/aigateway-ui/src/app/accounts/[id]/credentials/new/form.tsx`: remove the defaults fieldset
  and the `temperature` / `max_tokens` failure routing.
- `apps/aigateway-ui/src/app/accounts/[id]/credentials/new/form.module.css`: remove the four
  classes only that fieldset used (`section`, `legend`, `sectionNote`, `grid`).
- `apps/aigateway-ui/src/app/actions.ts`: stop parsing the six defaults fields; remove
  `optionalNumber` and the `ProfileDefaults` import; pass `{ api_key }` only.
- `apps/aigateway-ui/src/lib/aigateway/client.ts`: `setApiKey` input becomes `{ api_key: string }`,
  and the body is built from `api_key` alone, so no extra property can reach the wire.
  `ProfileDefaults` stays exported until nothing else needs it (the type still mirrors the
  response schema).
- Tests: `src/app/actions.test.ts`, `src/app/accounts/[id]/credentials/new/form.test.tsx`,
  `src/lib/aigateway/client.test.ts`.

## Test plan

New tests, written RED first:

1. The form offers no saved-default controls: no Model, Temperature or Max tokens control, and no
   "Defaults" group (`form.test.tsx`).
2. `setApiKeyAction` forwards exactly `{ api_key }` even when stale FormData carries all six fields
   with values, including malformed numbers, which must no longer block the write
   (`actions.test.ts`).
3. `setApiKey` sends a JSON body whose only key is `api_key`: no `defaults` property, even when the
   caller's object carries one at runtime (`client.test.ts`).

Retired prior tests, with their mapping (the contract change is owner-directed by `OME-1322` and spec
§5 C, "retired defaults tests with recorded mapping"):

| Retired test | Why | Covered by |
| --- | --- | --- |
| `actions.test.ts` "forwards the key once, names the default profile, and sends no defaults when blank" | asserts `defaults: null` in the payload, which this unit forbids | new test 2 (same key and name, payload `{ api_key }`) and new test 2's successful-write `revalidatePath` assertion |
| `actions.test.ts` "passes through the defaults that were filled in" | defaults are no longer authored | new test 2 (filled fields are ignored) |
| `actions.test.ts` `badInput` rows `max_tokens`, `temperature`, `timeout_seconds` | those fields are no longer parsed | new test 2 (malformed values no longer block); the `account_id` / `provider` / `api_key` rows stay |
| `form.test.tsx` "puts a numeric failure on the field that was mistyped" | the control is gone | new test 1 |
| `form.test.tsx` "puts a temperature failure on the temperature field" | the control is gone | new test 1 |

Unchanged and still required green: write-only key tests, error-kind routing, secret scrubbing, the
hidden account field, provider discovery fallback, name `default`, `page.test.tsx`, and the
`detail.test.tsx` "never renders a defaults blob" test (a response-side pin, kept).

## Acceptance

- The three new tests fail on `origin/main` and pass after the change.
- The focused suites `src/app/actions.test.ts` and `src/app/accounts/[id]/credentials/new/{form,page}.test.tsx`
  are green.
- All `aigateway-ui` card gates pass: `npm ci`, `npm run lint`, `npm run lint:css`,
  `npm run typecheck`, `npm run build`, `npm run test:ci`.
- UI behavior remains in `apps/aigateway-ui/`; the later owner-approved append-only gate transition lives in `.claude/scripts/` plus its exact approval manifest, recorded below.

## Outcome (fill at the end — required before COMMIT)

- **Status at review handoff:** implemented and gated locally; publication later authorised by the
  owner for OME-1322, including the exact task mirror and ledger paths.
- **Actual files at the UI-only gate** (before the separately approved repo gate follow-up below):
  - `src/app/accounts/[id]/credentials/new/form.tsx`: fieldset and `temperature`/`max_tokens`
    failure routing removed; header `INVARIANT` added.
  - `src/app/accounts/[id]/credentials/new/form.module.css`: `section`, `legend`, `sectionNote`,
    `grid` removed (used only by the fieldset; `accounts/[id]/page.tsx` uses its own module).
  - `src/app/actions.ts`: `optionalNumber`, the six-field parse, the numeric refusals and the
    `ProfileDefaults` import removed; the action forwards `{ api_key }`.
  - `src/lib/aigateway/client.ts`: `setApiKey` input is `{ api_key: string }`; the body is built as
    `{ api_key: input.api_key }`; the now-unused `ProfileDefaults` alias is removed.
    `schema.d.ts` is untouched.
  - Tests: `src/app/actions.test.ts`, `src/app/accounts/[id]/credentials/new/form.test.tsx`,
    `src/lib/aigateway/client.test.ts`.
- **RED (on `origin/main` code, `c6774ea1`):** 5 new tests failed, 71 passed. The action refused the
  stale form (`{ ok: false, … }`) and did not call the client with `{ api_key }`; the client body keys
  were `['api_key', 'defaults']`; the form still rendered the `legend` and posted 7 named fields
  instead of 4.
- **GREEN:** focused `client.test.ts`, `actions.test.ts`, `form.test.tsx`, `page.test.tsx` → 4
  files, 76 tests passed.
- **Gates (actually run, 2026-09-23, `apps/aigateway-ui`):** `npm ci` ✓ · `npm run lint` ✓ ·
  `npm run lint:css` ✓ · `npm run typecheck` ✓ · `npm run build` ✓ (compiled, static pages
  generated) · `npm run test:ci` ✓ (17 files, 238 tests, statement coverage 89.43 %).
  `git diff --check` clean.
- **Gate runner:** `uv run .claude/scripts/run_gates.py aigateway-ui` stops RED at its first step,
  the append-only check. It flags `form.test.tsx` and `actions.test.ts` (tests retired per the
  mapping above) and also `client.test.ts`, which received additions only: the checker cannot parse
  TS test artifacts, so it treats any modified TS test as a deletion. Because the runner stops there,
  the six card gates above were run individually in order.
- **Deviations:**
  1. Prior tests were retired: 2 tests and 3 `badInput` rows in `actions.test.ts`, and 2 tests in
     `form.test.tsx`, each mapped in the Test plan table. This is an owner-directed contract change
     (`OME-1322` scope; spec §5 C "retired defaults tests with recorded mapping"), not a clean
     append-only pass.
  2. The removal of the `ProfileDefaults` type alias from `client.ts` was not listed in Planned
     changes. It was dead after the change and nothing imports it.
  3. The SDLC card names `sdlc-react` as this stack's skill, but no such skill exists in
     `.claude/skills/` (card defect, surfaced). This unit followed the shared SDLC loop, which is
     identical across the sdlc skills by loop parity, plus the card body for `aigateway-ui`.
- **Commit at review handoff:** none; conventional commit follows the approved staging review.

### Owner-approved same-branch gate follow-up

The owner approved the recorded retirement of prior saved-default assertions and requested the gate
correction in this OME-1322 branch. `git push --force` is unnecessary — this branch has not been
published and force would not change a failing pre-push hook. No hook was skipped or disabled.

- `.claude/scripts/approved_test_changes.py` (new, 84 lines) permits only an exact TS/TSX test diff
  with an issue/branch-matching approval manifest and matching before/after Git blob IDs. Every other
  TS/TSX edit, deletion, rename and Python-test change keeps the old fail-closed path.
- `.claude/scripts/run_gates.py` consults this approval only when a test file is unsupported by the
  Python AST range parser; it prints each approved transition. The editing check reformatted other
  lines in this already oversized script mechanically; no Python AST-check rule changed.
- `.claude/test-change-approvals/OME-1322.json` names exactly the three reviewed test files,
  including additive-only `client.test.ts`. Any further edit changes its blob hash and fails again.
- `.claude/scripts/tests/test_approved_ts_change.py` (new) was RED before the integration and now
  covers exact approval, edited-after-approval rejection, unlisted-file rejection, wrong branch,
  and wrong baseline. The prior `.claude/scripts/tests/test_run_gates.py` is untouched.

**Checks actually run after the follow-up:** 5 new gate tests passed; 48 existing gate tests
passed; `uv run .claude/scripts/run_gates.py aigateway-ui --base origin/main` printed the three
approved test transitions, then append-only and all six UI gates passed (`ALL GATES GREEN`).
`git diff --check` clean. Pre-push had not run at the pre-commit review point.

**Publication:** the owner subsequently authorised staging, commit, push and PR of this exact
OME-1322 package, including `docs/tasks/2026-09-23-OME-1322-aigateway-ui-stop-authoring-profile-defaults.md`
and `docs/work/2026-09-23-OME-1322-aigateway-ui-stop-authoring-profile-defaults.md`. OME-1323 remains
separate and blocked on this unit.

### PR review follow-up — preserve the non-defaults success assertion

Post-publication review found that the retired successful key-write test also asserted
`revalidatePath("/", "layout")`, unrelated to saved defaults. The implementation still called it,
but the replacement test had not retained the assertion. The owner explicitly authorised restoring
it and publishing a follow-up. Added that assertion to the successful `setApiKeyAction` test and
updated the exact `actions.test.ts` Git blob ID in the approval manifest; its reason now accurately
counts four retired tests plus three `badInput` rows. The full branch-level gate, not a filtered
coverage run, is the acceptance check for this test-only follow-up.
