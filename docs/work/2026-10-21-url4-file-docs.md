---
ticket: OME-1552
stack: repo
status: in_progress   # docs drafted; PR not opened (orchestrator instruction)
started: 2026-10-21
finished:
---

# url4-file-docs — document url4 file sources and blob refs in the public docs

## Intent

Public docs for url4 file inputs (epic `OME-1529`): fetching a source as bytes with its media
type, content-addressed `/blob/sha256/<hex>` and `blob:sha256/<hex>` refs, the typed errors, and
what v1 does not support. Only behaviour on `main` or in the open PRs #1478 (`OME-1538`, bytes
fetch) and #1482 (`OME-1539`, file refs) is documented; PR content is marked "lands with".

Public docs live in this monorepo under `public-docs/` (Vue site behind docs.screamingface.ai,
linked from `packages/url4/README.md`), not in `screamingface-web`, so the draft is a new
Learn page there.

## Planned changes

- `public-docs/src/pages/learn/Url4FilesPage.vue` (new): the page.
- `public-docs/src/router/index.ts`: route `/learn/url4-files`.
- `public-docs/src/navigation/learn.ts`: sidebar entry after "url4 SDK".

## Test plan

- Docs only. Every example run against the code: `origin/OME-1539-url4-file-refs` (stacked on
  #1478) for the PR claims, `origin/main` for the `data:` parse claims.
- `npm run build` (vue-tsc + vite) and `npm run lint` in `public-docs/`.
- `run_gates.py repo` (no stack covers `public-docs/`).

## Acceptance

- Each claim cites code on `main` or in #1478/#1482; PR claims carry a "lands with" marker.
- Remote blobs stated as not supported in v1; `data:` at Case ingress and size caps stated as
  not yet available rather than described.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus the routes table row in `public-docs/CLAUDE.md`.
- **Commits:** see branch `url4-file-docs`.
- **Gates:** `run_gates.py repo`: ALL GATES GREEN (append-only check included). `public-docs`: `npm run build` and `type-check` clean, prettier/oxlint/eslint clean on touched files. Examples verified by running them on `origin/OME-1539-url4-file-refs` and (`data:` / C7 parse claims) on `origin/main`.
- **Deviations:**
  - The orchestrating task asked to document "data: at Case ingress" and "size caps". Neither
    exists on `main`, #1478 or #1482 (data: attachment is `OME-1545`/#1507, caps are
    `OME-1544`), so the page lists them as not yet available.
  - The task asked to mark remote blobs as typed `remote_blob_unsupported`. That code exists only
    in the unmerged spec (#1450, F1). The code in #1482 refuses a `url4://<node>/blob/…` ref with
    `x.blob_peer_not_allowed` (empty interim allowlist, fail closed). The page states v1 does not
    support remote blobs, gives the code that actually fires, and notes the spec's intended name.
    Needs an owner decision: rename the code in #1482 to match F1, or amend the spec.
