# OME-1525 plan — portal logo links home; one consistent breadcrumb

Spec: `docs/spec/2026-10-08-OME-1525-portal-home-link.md`. One SDLC unit, scoreboard stack.

1. **RED.** Add `test_rail_brand_links_home_and_crumbs_are_consistent` to `apps/scoreboard/tests/unit/test_portal_static.py`. It parses each page's `.rail` with the stdlib `html.parser` (no substring checks) and asserts the spec's table structurally. It must fail on `origin/main`.
2. **GREEN, markup.** In all five pages: change `<span class="brand">` to `<a class="brand" href="index.html">`, and remove the crumbs that link to `index.html`. On index, also remove the separator and the empty crumbs nav. On benchmark, the remaining crumb gets `id="crumb-benchmark"`.
3. **GREEN, script.** `benchmark.js` sets `#crumb-benchmark` text with the same value as `#benchmark-name`. `spec.js` sets `#back-link` text from `resolveBenchmarkName`, the same value it already puts in `#spec-benchmark`.
4. **Style.** `portal.css` gets `.rail a.brand { text-decoration: none; }`. The global `a` rule would otherwise underline the brand. `style.css` stays untouched.
5. **Gates.** `uv run pytest`, `ruff check`, `pyright`, plus the Node portal tests in `apps/scoreboard`.
6. **Visual check** in a browser on a local `uv run scoreboard`: all five pages, light and dark.
