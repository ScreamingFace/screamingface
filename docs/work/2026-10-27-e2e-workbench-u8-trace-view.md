---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: repo
status: in_progress
started: 2026-10-27
finished:
---

# e2e-workbench-u8-trace-view — one Trace view that tells the run's story (unit 8)

## Intent

The bundle page's "Trace chain" is a pass/fail table: two hops and their line counts. The run's
story is already in the bundle but scattered: 39 spans, 59 SDK events, gateway logs and the
accounting. Unit 8 joins these into one Trace view, with a header, a hop path, a cross-service
span tree rooted at a client span derived from SDK events, model calls with their logs, the
checks in plain words, and an OTLP/JSON export.
- Plan: `docs/plan/2026-10-27-e2e-workbench-u8-trace-view.md`.
- Spec: §3.8.

## Planned changes

See the plan, Tasks 1–5.

## Test plan

See the plan. The Review Focus items each get a test in the owning task.

## Acceptance

- The replay bundle shows five hops and one tree from `sdk.evaluate` down to the gateway calls.
- The expected-failure bundle has its failing path open and red.
- The OTLP/JSON download parses as `TracesData`.
- Gates green.

## Findings (before work)

- **2026-10-27 real replay** (trace `e7117aab…`), on the UI branch with 6a:
  - gateway chat spans nest under the engine span `/benchmarks/candidate`;
  - `url4.run` is the only orphan, and its parent is the client's `traceparent` span id;
  - gateway server spans have `attributes: {}`, which becomes follow-up B8 (`aigateway`).

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
- **Commits:**
- **Gates:**
- **Deviations:**
  - Task 3 `trace_html.section(story, key, token, page: int = 1, *, appendix="")`: `page` is
    1-based (matches `tm.page_of` and the `trace_page` query), not the plan's `page: int = 0`;
    `appendix` carries the raw trace.json into the section.
  - Task 3 `trace_html` has its own `_pager`/`_link` instead of reusing `telemetry_html._pager`:
    a different query key (`trace_page`) and anchor (`#trace-tree`).
  - Task 3 hop path is a CSS-styled `<table>` (boxes + arrows, column under 480px), not an SVG
    row: tabular data stays readable as rows to screen readers and text search; each state
    carries a small inline SVG glyph only.
  - Review of T3: `Telemetry.found` names the JSONL files that exist, so the Trace header can
    tell a missing `events.jsonl` (unknown) from an empty one (0).
