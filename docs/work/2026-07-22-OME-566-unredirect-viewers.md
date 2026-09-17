---
ticket: OME-566
stack: url4-cloud
status: done
started: 2026-07-22
finished: 2026-07-22
---

# OME-566 — Drop the /scalar + /asyncapi redirects (direct pages; keep /docs switcher)

## Intent

Owner decision (discussed 2026-07-22): keep `/docs` as the REST ⇄ Stream **switcher**, and drop the
OME-565 redirects — `/scalar` and `/asyncapi` serve their **own** direct Scalar pages again. Scalar
renders one spec per view, so a single *merged* scroll isn't possible; the switcher (one page, both
docs a click apart) is the accurate solution, and the direct pages give each doc its own URL.
`/asyncapi` directly shows the WS channel + message list.

## Planned changes

- `src/url4_cloud/ops.py` — add `_scalar_page(title, spec_url)`; `/scalar` + `/asyncapi` return
  direct pages (not `RedirectResponse`); keep `_DOCS_HTML` + `/docs`; drop the unused
  `RedirectResponse` import; docstrings/WHY.
- `src/url4_cloud/schemas/openapi.py` — remove the empty **Stream** + **Ops** tags from `TAGS`
  (Stream = WS, AsyncAPI-only; Ops = hidden routes) so the REST sidebar shows no empty sections.
- `tests/unit/test_docs_ops.py` — **AUTHORIZED edits**: `/scalar` + `/asyncapi` assert 200 HTML
  referencing their own spec (revert the 307 assertions); keep the `/docs` both-specs test; NEW
  test that the OpenAPI tags omit Stream/Ops.

## Test plan

- **RED:** `/scalar` + `/asyncapi` page tests (200 HTML) fail against the current redirect handlers.
- **GREEN:** direct pages restored → pass; `/docs` switcher test stays green.
- **Browser acceptance:** `/asyncapi` shows the AsyncAPI channel + message list; `/docs` still
  switches REST ⇄ Stream.

## Acceptance

`/asyncapi` renders the WS message list directly; `/scalar` renders REST; `/docs` still the
switcher; `run_gates.py url4-cloud` green.

## Outcome

- **Actual files:** `src/url4_cloud/ops.py` (restored `_scalar_page`; `/scalar` + `/asyncapi` serve
  direct pages; dropped `RedirectResponse`; docstring/WHY) · `src/url4_cloud/schemas/openapi.py`
  (removed the empty **Stream** + **Ops** tags from `TAGS`) · **`src/url4_cloud/app.py`** (hid
  `/healthz` from the schema, `include_in_schema=False`) · `tests/unit/test_docs_ops.py`
  (`/scalar` + `/asyncapi` assert 200 direct pages; NEW tag/`healthz`-omission test).
- **Commits:** combined commit with OME-555 (shared `test_docs_ops.py`) — `Refs: OME-566, OME-555`.
- **Gates:** `run_gates.py url4-cloud --skip-append-only` GREEN — ruff · format · pyright · pytest
  cov ≥ 80. Append-only skipped: re-pointing the viewer-page tests is the authorized change.
- **Deviations:** **scope expanded** (owner decluttering intent) to also hide `/healthz` — a real
  `GET /healthz` operation was leaking into the user-facing reference while the sibling probes
  (livez/readyz/metrics) were already hidden. Browser-verified on `:9108`: `/scalar` sidebar =
  Introduction / Token / Execution / Models (no Stream / Ops / Healthz); `/asyncapi` renders the WS
  channel + messages directly; `/docs` switcher intact. `/healthz` still responds `200`.

## Closure justification (OME-1215, round 2)

This ledger's `status:` was `in_progress` with the unit's work already merged, while the
`docs/tasks/` mirror said `done` — the mirror was the correct side. `OME-1215` closed the
ledger, which is an edit to an audit record, so the owner required the closure to be
justified with evidence rather than asserted.

EVIDENCE, verifiable from this repo: the unit's work is on `origin/main` as `bccb5ee0`
(`feat(url4-cloud): declutter REST docs + document Prefer sync/async`), authored 2026-07-22. `finished: 2026-07-22` is that commit's author date — read
from git, not reconstructed.

WHAT IS *NOT* CLAIMED: nothing about why the ledger was left open, and nothing about the
ticket's Linear state. Only that the work in this ledger reached `main` on the date given.
