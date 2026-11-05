---
ticket: OME-1831
stack: aigateway-ui
status: in_progress   # planned | in_progress | done | blocked
started: 2026-11-04
finished:
---

# ui-schema-effective — OME-1138 close-out L9: the Admin UI catches up with the gateway

## Intent

Leaf L9 of the OME-1138 close-out (close-out spec `docs/spec/2026-10-29-ome-1138-closeout.md`
§4.9, plan `docs/plan/2026-10-29-ome-1138-closeout.md` L9; X1, P-F10, X6). The Admin UI's
committed `schema.d.ts` was last regenerated at `08f534317` (E3), so it lacks what the gateway has
published since, among it `/v1/cache/entries` and the `effective` flag L7a (OME-1819, `6e998fa4d`)
added to the Connection listing. The UI still maps `credential_write_conflict` to `conflict`,
though the gateway stopped sending that code in E5a (`routes/provider_access_http.py:214`). This
unit regenerates the schema from `origin/main`, removes the dead mapping, and replaces the brand
README's "delete profile" with the Connection action. `profile_index_conflict` stays (close-out
spec §2, "Keep").

## Planned changes

Under `apps/aigateway-ui/`:

- `src/lib/aigateway/schema.d.ts`: regenerated with the pinned `openapi-typescript` 7.13.0
  (`node_modules/.bin/openapi-typescript openapi.json -o src/lib/aigateway/schema.d.ts`) from the
  gateway OpenAPI exported at `origin/main` (`app.openapi()` of `aigateway.main:app`), as
  `docs/work/2026-10-14-ui-connection-admin.md` records. No hand edit.
- `src/lib/aigateway/errors.ts`: drop `credential_write_conflict` from `CODE_KINDS` (`:77`) and from
  the `conflict` kind's doc comment (`:16-17`).
- `src/brand/README.md:25`: the `--danger-*` row names the Connection action instead of
  "delete profile".
- `src/lib/aigateway/client.test.ts:373`: the prior pin of the retired mapping changes, with the
  owner's approval (see Test plan).
- `.claude/test-change-approvals/OME-N.json`: pins the changed prior test file's base and approved
  blob, once the issue is filed.

## Test plan

- RED (new, no prior test touched): a gateway answer carrying the retired code
  `credential_write_conflict` is no longer dispatched before its status, so it takes the status's
  kind (a 503 reads `unavailable`, a 409 `conflict`), while `profile_index_conflict` still maps to
  `conflict`.
- Prior test expected to change, for owner approval before GREEN: `client.test.ts:373`
  `[503, "credential_write_conflict", "conflict"]` in the successor-code table.
- The regenerated schema is exercised by `npm run typecheck`: every consumer of a changed type
  must still compile.

## Acceptance

- `schema.d.ts` equals the `openapi-typescript` 7.13.0 output for `origin/main`'s OpenAPI.
- No non-test source under `apps/aigateway-ui/src` maps `credential_write_conflict` (`errors.ts`,
  `client.ts`); only the tests that pin its removal name it.
- `src/brand/README.md` no longer says "delete profile".
- `run_gates.py aigateway-ui --base origin/main` is green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files (5 under `apps/aigateway-ui/`, plus this ledger):**
  - `src/lib/aigateway/schema.d.ts`: regenerated with `openapi-typescript` 7.13.0
    (`node_modules/.bin/openapi-typescript openapi.json -o src/lib/aigateway/schema.d.ts`) from
    the gateway OpenAPI exported at `origin/main` `52d9492aa` (`app.openapi()` of
    `aigateway.main:app`; 42 paths, 41 schemas). sha256 of the generated `schema.d.ts`:
    `dafb66ed3b75ba63c59b4aa03ce5b9810b1bb5408c250b782a4ef3844fb1922d`; of the exported OpenAPI
    JSON (`json.dumps(app.openapi())` plus a trailing newline):
    `3a2137871a2238f972acd1bbf6a795a131da2972af834feb23b03f1dbced8de3`. Additive only: the new
    `OAuthConnectionListRow` with `readonly effective: boolean`, which the
    `/v1/oauth/connections` listing now returns in place of `OAuthConnectionResponse`;
    `/v1/cache/entries`; and one OAuth callback description line ("account and Connection").
    No UI source consumes a changed type. Regenerated once more the same way after L7c
    (#1678) merged, from `origin/main` `24d979a5e` (42 paths, 41 schemas): the one further change
    is the Connection delete's optional query parameter `expected_status?: ("pending" | "error")
    | null`. sha256 of the generated `schema.d.ts`:
    `514c3b09050f652ecbcc81bed8e0fb8c2e5dda991aa2dd636fc9b1ff0edc6652`; of the exported OpenAPI
    JSON: `085fe16d59f4038f3ffb59fc7a93f73ae9ff1efb7fe31469e2789b2721d21533`. A second run of the
    generator writes the same bytes.
  - `src/lib/aigateway/errors.ts`: `credential_write_conflict` left `CODE_KINDS` and the
    `conflict` kind's doc comment, which now says `profile_index_conflict` is decoded for a
    gateway older than E5a (`routes/provider_access_http.py:77-78`).
  - `src/brand/README.md`: the `--danger-*` row reads "deactivate, detach a connection", the
    console's Connection action ("Detach").
  - `src/lib/aigateway/errors.test.ts` (new, 3 cases): the retired code reads as its bare status
    (503 and 409), and `profile_index_conflict` stays `conflict`.
  - `src/lib/aigateway/client.test.ts` (prior test, owner-approved 2026-11-04): the row
    `[503, "credential_write_conflict", "conflict"]` is deleted, with a one-line tombstone naming
    its successor in `errors.test.ts`; after review, the owner also approved rewording the
    comment above it, which described the deleted row, to "Retryable: the legacy index
    conflict, decoded for a gateway older than E5a."
- **Commits:** on branch `OME-1831-ui-schema-effective` (`ui-schema-effective` until PR-open),
  rebased onto `24d979a5e` after L7c (#1678) merged: `3bd04b413` fix(aigateway-ui): catch the
  Admin UI up with the gateway (OME-1138 L9); `291bfa1ba` fix(aigateway-ui): carry the
  conditional Connection delete into the UI schema (OME-1138 L9); then the commit that files
  `OME-1831` here and in its `docs/tasks` mirror and adds the manifest.
- **Review (independent, read-only):** nothing blocking; the schema regenerated byte-identical
  from `origin/main`. Acted on: the acceptance line above, the labelled checksums, the
  `conflict` doc in `errors.ts`, and the comment above the tombstone.
- **RED seen:** `errors.test.ts` failed on the 503 case only (`expected 'conflict' to be
  'unavailable'`); the 409 case and the `profile_index_conflict` invariant passed before GREEN, as
  expected.
- **Gates (2026-11-04, base `origin/main` `52d9492aa`):** baseline before any change: lint 0
  errors (5 prior warnings), typecheck clean, 20 files / 307 tests. After GREEN,
  `run_gates.py aigateway-ui --base origin/main` stops at the append-only check on the approved
  `client.test.ts` change: the manifest `.claude/test-change-approvals/OME-N.json` is written at
  PR-open, once the issue id exists. The same runner with `--skip-append-only`: `npm ci`, `lint`,
  `lint:css`, `typecheck`, `build` and `test:ci` passed, ALL GATES GREEN; 21 files / 309 tests.
  Rerun the same way after the review's `errors.ts` edit: ALL GATES GREEN; the comment-only
  change to `client.test.ts` after it passed that file's tests and `eslint`. Rebased onto
  `24d979a5e` and rerun with the final schema the same way (2026-11-05): ALL GATES GREEN. With
  `.claude/test-change-approvals/OME-1831.json` the append-only check passes, `client.test.ts`
  pinned byte-exact.
- **Deviations:**
  - Close-out spec §8 says `credential_write_conflict` is "gone from the UI src". The plan's RED
    step needs a test that names the retired code, and the UI's tests sit under `src`, so this
    unit reads §8 as the non-test source: `errors.test.ts` and the tombstone in
    `client.test.ts` still name the code.
  - The regenerated schema also carries three classification routes the close-out spec §4.9
    does not name: `/v1/classifications` (POST), `/v1/classifiers` and `/v1/classifiers/details`
    (GET), with their operations. They are additive and no UI source uses them.
  - Card defect: `.claude/sdlc.local.md` maps the `aigateway-ui` stack to `skill: sdlc-react`, a
    skill that does not exist under `.claude/skills/` (only `sdlc-electron` and `sdlc-python`).
    This unit followed the shared loop rules those two skills carry.
