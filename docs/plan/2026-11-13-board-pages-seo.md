---
title: One indexable page per leaderboard — plan
status: proposed
created: 2026-11-13
spec: docs/spec/2026-11-13-board-pages-seo-spec.md
---

# One indexable page per leaderboard — plan

## Server: `apps/scoreboard/src/scoreboard/board_pages.py`

Registered from `register_portal()` before the static mount, so these routes win over files.

1. **`GET /benchmarks/{id}/`**
   - Look the id up in `list_benchmark_summaries()`.
   - Found: fill in the page. `best_score is None` adds `robots: noindex,follow`.
   - Store unavailable: 503, so a crawler retries instead of dropping the board.
   - Not found but `Benchmark.exists(id=…)`: a private board. Serve the page with its generic
     head and `noindex`; no board field is written.
   - Otherwise 404.
   - `Cache-Control: no-store`, as the catalog route sends.
2. **`GET /benchmarks/{id}`** → 301 to the slash form.
3. **`GET /benchmark.html`** → with `id`, 301 to `/benchmarks/<id>/` keeping other parameters;
   without, the file unchanged.
4. **`GET /sitemap.xml`** → home, about, and each summary with a score.
5. **`GET /robots.txt`** → `User-agent: *`, `Allow: /`, `Sitemap:`.

**Page rendering.** `portal/benchmark.html` is read once at registration. Relative `href` and
`src` values are made root-relative in that copy, since they would otherwise resolve under
`/benchmarks/<id>/`. Each request substitutes `<title>`, the description, `og:`/`twitter:`
title and description, the `<h1>`, the lead paragraph, and appends canonical, `og:url` and
`robots` to the head. Every value passes through `html.escape`. A missing substitution target
fails app creation, so a later edit to the shell cannot silently drop a tag.

**Text.**
- Title: `{name} leaderboard: models & fusions | ScreamingFace`; when that exceeds 70
  characters, `{name} leaderboard | ScreamingFace`.
- Description: `{name} leaderboard: {focus}. An open leaderboard for single models and
  fusions: ensembles, routers, cascades. Copy any result's recipe and rerun it.`

## Portal scripts

- `board-url.js` (new, loaded first on every page): `idFromPath`, `idFromLocation`,
  `idFromHref`, `boardHref`, `pageHref`. Over http(s) a board link is `/benchmarks/<id>/`;
  otherwise the relative query form, for `file://` use.
- `analytics.js`: the `benchmark` property and the card-click label read either form.
- `subscribe.js`: `boardId()` reads the path first.
- `main.js`: `boardId()`, `boardHref(id)`, `pageHref(file)`, `atBoardAddress()`; the tab strip,
  the More menu and the catalog cards link through `boardHref`.
- `benchmark.js`: id from `boardId()`; `spec.html` and `index.html` links through `pageHref`;
  `document.title` is left alone at `/benchmarks/<id>/`, where the server set it.
- `spec.js`: back link through `boardHref`.

## Tests

New files only: `tests/unit/test_board_pages.py`, `tests/portal/board-url.test.js` (named in
the CI workflow and the gate card, which a guard test requires). The cases
are the ledger's test plan. Existing tests are not edited: readers keep the `?id=` fallback
they pin, and link builders keep the query form when there is no http(s) location.

`test_parameter_pages_declare_no_og_url_that_drops_the_shared_item` keeps passing, but its two
`benchmark.html?id=` cases now follow the 301 and no longer exercise those addresses. The
per-board `og:url` it guards against losing is asserted directly in the new test file.
