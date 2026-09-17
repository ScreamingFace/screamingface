---
ticket: OME-564
stack: url4-cloud
status: done
started: 2026-07-22
finished: 2026-07-22
---

# OME-564 — Render /asyncapi with Scalar (unify viewers, drop web-component)

## Intent

Scalar ≥ 1.61 (June 2026) renders AsyncAPI 3.x with the same UI as OpenAPI. Swap `/asyncapi` from
the `@asyncapi/web-component` to a Scalar embed on `/asyncapi.json` — one polished, same-origin
viewer for both docs. Removes the web-component dependency **and** the shadow-DOM `cssImportPath`
workaround (supersedes OME-553 / `0dbf119`).

## Planned changes

- `src/url4_cloud/ops.py` — add a DRY `_scalar_page(title, spec_url)` helper; `/scalar` and
  `/asyncapi` both return it (openapi.json / asyncapi.json). Drop `_SCALAR_HTML` / `_ASYNCAPI_HTML`
  constants + the web-component markup; update the module docstring.
- `tests/unit/test_docs_ops.py` — **AUTHORIZED edits** (viewer tech changed per owner):
  `test_asyncapi_reference_page_renders_the_ws_schema` asserts `createApiReference` + `/asyncapi.json`
  (was `asyncapi-component`); **remove** `test_asyncapi_page_imports_component_css_into_shadow_root`
  (obsolete — no web-component, no shadow DOM).

## Test plan

- **RED:** the asyncapi page test, switched to expect `createApiReference`, fails against the
  current web-component HTML.
- **GREEN:** the `_scalar_page` helper serves Scalar for both → passes; the `/scalar` test is
  unchanged and stays green.
- **Browser acceptance:** rebuild compose `app`; `/asyncapi` renders the AsyncAPI 3.0 channel in
  the Scalar UI (Models section, channels, RECEIVE /ws operation).

## Acceptance

`/asyncapi` renders via Scalar (browser-verified); tests updated; `run_gates.py url4-cloud` green.

> **Append-only note (rule 5):** removing the `cssImportPath` test + changing the asyncapi assertion
> are the authorized contract change for this ticket (the web-component is intentionally removed);
> verified with `--skip-append-only`.

## Outcome

- **Actual files:** `src/url4_cloud/ops.py` (new `_scalar_page(title, spec_url)` helper; `/scalar`
  and `/asyncapi` both return it; dropped `_SCALAR_HTML`/`_ASYNCAPI_HTML` + the web-component +
  `cssImportPath`; module docstring updated) · `tests/unit/test_docs_ops.py`
  (`test_asyncapi_reference_page_renders_the_ws_schema` asserts `createApiReference`; removed the
  obsolete `test_asyncapi_page_imports_component_css_into_shadow_root`).
- **Commits:** see the OME-564 commit on `OME-513-url4-cloud`.
- **Gates:** `run_gates.py url4-cloud --skip-append-only` GREEN (ruff · format · pyright · pytest
  cov ≥ 80). Append-only skipped: the asyncapi assertion change + cssImportPath-test removal are the
  authorized contract change (web-component intentionally removed).
- **Deviations:** browser-verified on compose `:9108` — `/asyncapi` renders the AsyncAPI 3.0 channel
  in the Scalar UI (Models section, telemetry-stream channel, server). Removes the
  `@asyncapi/react-component` + unpkg dependency; **supersedes** OME-553 / `0dbf119` (cssImportPath).

## Closure justification (OME-1215, round 2)

This ledger's `status:` was `in_progress` with the unit's work already merged, while the
`docs/tasks/` mirror said `done` — the mirror was the correct side. `OME-1215` closed the
ledger, which is an edit to an audit record, so the owner required the closure to be
justified with evidence rather than asserted.

EVIDENCE, verifiable from this repo: the unit's work is on `origin/main` as `ad4cc2f8`
(`feat(url4-cloud): render /asyncapi with Scalar, unify the doc viewers`), authored 2026-07-22. `finished: 2026-07-22` is that commit's author date — read
from git, not reconstructed.

WHAT IS *NOT* CLAIMED: nothing about why the ledger was left open, and nothing about the
ticket's Linear state. Only that the work in this ledger reached `main` on the date given.
