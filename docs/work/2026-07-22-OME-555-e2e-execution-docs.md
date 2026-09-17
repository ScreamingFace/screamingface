---
ticket: OME-555
stack: url4-cloud
status: done
started: 2026-07-22
finished: 2026-07-22
---

# OME-555 — e2e execution docs: sync / async / streaming (diagrams + Scalar-exercisable)

## Intent

Give developers the end-to-end execution picture for the three modes (sync / async / streaming),
**and make sync vs async actually exercisable in `/scalar`**. Two parts:

1. **Diagrams** — produced with the **`/diagramming:architecture-diagram` skill** (SVG + PNG in
   `docs/diagrams/`, verified SVG→PNG per repo convention), covering the sync / async / streaming
   flows across Client → App (REST+WS) → NATS/JetStream → Runner Job. Referenced from the served
   docs. (NOT ad-hoc Mermaid — owner corrected this; the diagramming skill is the tool.)
2. **Prefer header** — declare `Prefer` (and its `wait`) as a documented OpenAPI **header
   parameter** on `GET /`, so Scalar renders an input and a developer can drive sync vs async
   (today `routes.py` reads it via `request.headers.get("Prefer")`, so it never reaches OpenAPI and
   Scalar shows no way to select the mode — the gap the owner flagged).

The three flows (from the code):
- **sync** — `GET /` holds to the terminal frame (bounded by `SYNC_MAX_WAIT`), returns the Result
  body; WS carries live telemetry (`rest/routes.py::_run_sync`).
- **async** — `Prefer: respond-async` → `202` + `Location`/`Link`; Result/Terminated arrive on the
  WS stream (JetStream-buffered, resumable).
- **streaming/resume** — WS attach (`?ticket=`) + `sequence` + `ai.url4.attach{from_sequence}`
  replay + `ai.url4.stop` cancel (`ws/endpoint.py`, `ws/bridge.py`).

## Planned changes

- `src/url4_cloud/rest/routes.py` — declare `Prefer` as a typed `Header()` parameter on `GET /`
  (documented, optional) and parse from it, so the sync/async control is visible + tryable in
  Scalar. Keep behaviour identical.
- Diagrams via the diagramming skill → `docs/diagrams/url4-cloud-execution-*.svg|png`.
- Reference the diagrams from the served docs (`docs/protocol.md` and/or the OpenAPI description).
- `tests/unit/test_*` — assert the `Prefer` header parameter is documented on `GET /`.

## Test plan

- **RED:** a test asserting `GET /` documents a `Prefer` header parameter — fails today.
- **GREEN:** declare the `Header()` param → passes; existing sync/async behaviour tests stay green.
- **Browser acceptance:** `/scalar` shows the `Prefer` input on `GET /`; the diagrams render/are
  linked.

## Acceptance

Sync vs async is selectable/visible in `/scalar` (Prefer header documented); the execution diagrams
exist (diagramming skill, SVG+PNG) and are reachable from the docs; `run_gates.py url4-cloud` green.

## Deviations (running)

- Initially drafted Mermaid-in-OpenAPI-description; **reverted** — owner asked for the
  `/diagramming:architecture-diagram` skill. Header name stays `URL4-Capability` (owner-confirmed).

## Outcome

**Part 1 — Prefer sync/async doc (committed `d61bf49`, combined with OME-566):** `rest/routes.py`
declares `Prefer` as a documented `Header` parameter on `GET /` + a sync/async operation
description; `test_docs_ops.py` asserts it. Browser-verified: Scalar renders the `Prefer` input +
explanation on `GET /`.

**Part 2 — execution-flow diagrams (this commit):**

- Authored with the **`/diagramming:architecture-diagram`** skill's design system (dark slate,
  semantic colours, text halos, label chips) via a Python emitter → **SVG**, rendered to **PNG**
  with `rsvg-convert` (repo diagram rule). Three flows: sync / async / streaming.
- `docs/diagrams/url4-cloud-execution-{sync,async,stream}.{svg,png}` (canonical) +
  `…-flows.gen.py` (regenerable source) · `src/url4_cloud/assets/diagrams/*.svg` (served copy, ships
  in the image via `COPY src ./src`) · `app.py` (`StaticFiles` mount at `/diagrams`) ·
  `schemas/openapi.py` (`## Execution flows` section embedding the three SVGs) · `test_docs_ops.py`
  (served + embedded tests).
- **Owner chose option B** — embed in the served docs. Browser-verified on `:9108`: `/scalar`
  renders all three diagrams **inline** in the Introduction (Scalar renders markdown `![]()`
  images — the open question, now confirmed).

- **Commits:** `d61bf49` (Prefer) + the diagrams commit on `OME-513-url4-cloud`.
- **Gates:** `run_gates.py url4-cloud --skip-append-only` GREEN — ruff · format · pyright · pytest
  cov ≥ 80.
- **Deviations:** first drafted Mermaid in the OpenAPI description; reverted per owner to the
  diagramming skill (SVG). Served SVGs duplicate `docs/diagrams/` (image build context can't reach
  repo-root `docs/`) — acceptable, `docs/diagrams` is the source of truth.
