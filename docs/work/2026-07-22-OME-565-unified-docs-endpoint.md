---
ticket: OME-565
stack: url4-cloud
status: done
started: 2026-07-22
finished: 2026-07-22
---

# OME-565 — Unify doc viewers into /docs (Scalar REST + AsyncAPI switcher)

## Intent

One canonical `/docs` Scalar reference with a document switcher over both specs (`/openapi.json`
REST default + `/asyncapi.json` Stream), using Scalar's multi-document `sources` config. `/scalar`
and `/asyncapi` 307-redirect to `/docs`. Supersedes OME-564's two separate pages — one entry point.

## Planned changes

- `src/url4_cloud/ops.py` — `GET /docs` → `_docs_page()` (multi-source Scalar); `/scalar` +
  `/asyncapi` return `RedirectResponse('/docs')`; drop the single-source `_scalar_page`; docstring.
- `tests/unit/test_docs_ops.py` — **AUTHORIZED edits** (viewer structure changed per owner):
  `/scalar` + `/asyncapi` assert `307` → `/docs`; NEW test that `/docs` serves Scalar referencing
  both `/openapi.json` + `/asyncapi.json`.

## Test plan

- **RED:** `/scalar` + `/asyncapi` asserted as `307`→`/docs` fail (they serve HTML today); the
  `/docs` test fails (route doesn't exist).
- **GREEN:** add `/docs` + the redirects → pass.
- **Browser acceptance:** `/docs` renders with a **document switcher**; REST (OpenAPI) shows by
  default; switching to Stream renders the AsyncAPI 3.0 channel. (The one real unknown — Scalar's
  docs only show all-OpenAPI source lists; verify the mixed list works.)

## Acceptance

`/docs` renders both specs with a working switcher (browser-verified); `/scalar` + `/asyncapi`
redirect to `/docs`; `run_gates.py url4-cloud` green.

> **Append-only note (rule 5):** re-pointing the `/scalar` + `/asyncapi` page tests at the redirect
> is the authorized contract change (viewer structure changed); verified `--skip-append-only`.

## Outcome

- **Actual files:** `src/url4_cloud/ops.py` (`_DOCS_HTML` multi-source Scalar; `GET /docs`;
  `/scalar` + `/asyncapi` → `RedirectResponse('/docs')` (307); dropped `_scalar_page`; docstring) ·
  **`src/url4_cloud/app.py`** (FastAPI `docs_url=None, redoc_url=None`) · `tests/unit/test_docs_ops.py`
  (`/docs` serves Scalar referencing both specs; `/scalar` + `/asyncapi` assert `307`→`/docs`).
- **Commits:** see the OME-565 commit on `OME-513-url4-cloud`.
- **Gates:** `run_gates.py url4-cloud --skip-append-only` GREEN — ruff · format · pyright · pytest
  cov ≥ 80 (123 tests, 96.9% cov). Append-only skipped: re-pointing the viewer-page tests is the
  authorized contract change.
- **Deviations:** **`app.py` change beyond the planned `ops.py`-only scope** — FastAPI reserves
  `/docs` for Swagger UI by default, so our route never won; disabled the built-in Swagger + ReDoc
  (`docs_url=None, redoc_url=None`) to free `/docs` for Scalar (Scalar replaces them). Browser-
  verified on `:9108`: `/docs` shows a **document switcher** — REST (OpenAPI 3.1) default + Stream
  (AsyncAPI 3.0) with all message types; `/scalar` + `/asyncapi` 307-redirect to `/docs`.
