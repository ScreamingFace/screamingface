---
ticket: OME-1525
stack: scoreboard
status: in_progress
started: 2026-10-08
finished:
---

# OME-1525 — portal logo links home; one consistent breadcrumb

## Intent

The portal's top bar names the home page "leaderboard" on two pages and "portal" on three, and the `😱 screamingface` brand is not a link. The owner chose "logo is home": the brand links to `index.html`, the home crumb is dropped, and the breadcrumb only shows where you are below home.

## Planned changes

- `apps/scoreboard/portal/{index,about,benchmark,data,spec}.html`: `<span class="brand">` → `<a class="brand" href="index.html">`; remove every crumb that points at `index.html`; index has no separator or crumbs.
- `apps/scoreboard/portal/benchmark.html` + `benchmark.js`: the single crumb gets `id="crumb-benchmark"` and is set to the benchmark's display name.
- `apps/scoreboard/portal/spec.js`: the `#back-link` crumb's text becomes the benchmark's display name (it already links to the benchmark).
- `apps/scoreboard/portal/portal.css`: `.rail a.brand` drops the global link underline (style.css is the vendored brand file and stays untouched).
- `apps/scoreboard/tests/unit/test_portal_static.py`: structural rail test.

## Test plan

- RED first: parse each page's `.rail` with `html.parser` and assert:
  - the brand is an `<a>` with `href="index.html"` on all 5 pages;
  - no crumb has `href="index.html"` and no crumb's text is "portal";
  - index has no crumbs; about/data have exactly one (`here`); benchmark has one with `id="crumb-benchmark"`; spec has two, `#back-link` then the `here` crumb.

## Acceptance

- See OME-1525. Owner visual check: the brand looks unchanged and clicking it returns home from every page.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned (5 pages, `benchmark.js`, `spec.js`, `portal.css`, `test_portal_static.py`).
- **Commits:** see the PR (squash-merged).
- **Gates:** RED 6 failed → GREEN; scoreboard `pytest` 958 passed / 9 skipped; `ruff check` + `ruff format --check` clean; `pyright` 0 errors; Node portal tests 82/82 (CI's file list).
- **Deviations:** the benchmark and spec crumbs show the benchmark id straight away and switch to the display name once it loads, so an unknown benchmark never shows a misleading "leaderboard" crumb. Browser check on a local scoreboard (empty database): all 5 bars as specified, the brand is a link with no underline.
