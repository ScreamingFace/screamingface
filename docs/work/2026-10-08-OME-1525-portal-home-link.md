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
- **Deviations:**
  - The planned single test `test_rail_brand_links_home_and_crumbs_are_consistent` became three: `test_rail_brand_is_the_home_link_and_no_crumb_repeats_it` (per page), `test_rail_crumbs_show_only_where_you_are_below_home`, `test_rail_benchmark_crumb_starts_hidden_with_its_separator`.
  - The benchmark and spec crumbs show the benchmark id straight away, then the display name once it loads.
  - Code-review fixes (round 2):
    - Empty crumb placeholders start `hidden`. The benchmark crumb and its separator hide again on a missing id or a 404.
    - The spec page's missing-parameter error links to the benchmark list instead of naming a removed "leaderboard" crumb.
    - The brand emoji is `aria-hidden`, and the brand gets a hover tone change.
    - Duplicated name logic is pulled into one helper per script.
  - Not done, proposed as a follow-up: generating the rail from one shared source instead of 5 hand-copied pages.
  - Browser check on a local scoreboard (empty database): all 5 bars as specified, and the brand is a link with no underline.
