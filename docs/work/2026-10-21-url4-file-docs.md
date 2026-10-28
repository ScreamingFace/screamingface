---
ticket: OME-1552
stack: repo
status: in_progress   # docs drafted; PR waits for spec #1450 and Sergey's confirmation
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

## Revision 2026-10-26 (rewrite against spec #1450 at `910d24ca6`)

Sergey approved on 2026-10-26 a redraft scoped to what the spec says ships in v1. The branch had
fallen 140 commits behind, so `origin/main` was merged in (no force-push of the pushed branch).
This ledger is reused rather than a second `2026-10-26-…` ledger for the same unit.

- **Page rewritten** (`public-docs/src/pages/learn/Url4FilesPage.vue`): file URL as a source,
  the transport guard, blob refs, what v1 refuses, Benchmark Cases (v2 envelope), limits,
  `input_modalities`, errors. Each claim carries a status: on main / lands with #N / specified.
  The `fetch_bytes` / `StaticIOLayer` API detail from #1478 was dropped (SDK-level, not v1 contract).
- **Mirror added:** `docs/tasks/2026-10-26-OME-1552-url4-file-docs.md` (none existed; priority,
  labels and created date left to copy from Linear, which this unit did not touch).
- **Verified on main (`origin/main` merged at this revision):** `x.source_*` codes and
  `SourceGuard` defaults (`packages/url4/src/url4/core/errors.py`, `io/_source_policy.py`,
  `io/http.py`, #1521); 8 MiB `AIGW_MAX_REQUEST_BYTES` and 413 `request_too_large`
  (`apps/aigateway/src/aigateway/config.py`, `middleware/body_cap.py`, #1479); data:-only media and
  422 `unsupported_content_part` (`core/media_intake.py`, `core/content_parts.py`, Ollama
  `allow_files=False`, Anthropic system-slot refusal); `input_modalities` (`core/input_modalities.py`,
  `core/model_capabilities.py`, #1451); v2 envelope (`benchmarks/candidate_input.py`, #1507).
- **Verified on open PRs:** `x.remote_blob_unsupported`, `x.blob_digest_mismatch` on #1482 head
  `ffd69a70a`; `unsupported_content_type` on #1478 head `9d32862f9`; `MAX_PICTURES = 20`,
  `MAX_CASE_BYTES = 8_000_000` on #1554.
- **Spec-only (no code anywhere):** `x.remote_node_unsupported` (on main a `url4://` remote call is
  refused as `x.source_destination_blocked` by the empty peer allowlist); engine modality admission
  (`intent_error`, C9); non-text `https` body to attachment (`OME-1540`/`OME-1543`); run-scoped store.
- **Python-client blob upload:** none exists; the page says "coming".
- **Gates:** `public-docs`: `npx oxlint .`, `npx eslint .`, `npm run build` (vue-tsc + vite) all
  clean; prettier check clean on the page.

## Revision 2026-10-28 (spec rounds 8-10, merged #1450 at `638be5024`)

Branch rebased onto `origin/main` (merge commits flattened, no content commits dropped).

- **Attachment opt-in:** `;accept=` must be exactly one lower-case attachment type
  (`image/png|jpeg|gif|webp`, `application/pdf`); no `image/*`, no lists; the response type must
  equal it, else `unsupported_content_type`. Wildcard examples removed from the page.
- **Literal targets:** URL and `;accept=` literal; row-derived URLs deferred (`OME-1748`);
  variable/templated gets `x.source_not_static`.
- **Model-free reachability:** an attachment in an iteration over a model-dependent collection gets
  `x.source_not_static` before any I/O; example added.
- **Caps:** 20 entries / 8,000,000 bytes over the whole `attachments[]` (blob refs plus https).
- **Status markers:** spec now merged; #1478, #1482 still open ("lands with"); per-Case picture caps
  moved to "on main (#1554)" (verified `picture_input.py` on `origin/main`).
- **Gates:** `public-docs`: `npx oxlint .`, `npx eslint .`, `npm run build` clean; prettier applied.
