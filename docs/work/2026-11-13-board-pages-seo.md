---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: scoreboard
status: done
started: 2026-11-13
finished: 2026-11-13
---

# board-pages-seo — one indexable page per leaderboard

## Intent

Every leaderboard is served from the same static file, `benchmark.html?id=<id>`. The HTML is
byte-identical for all boards (title `screamingface · leaderboard`, one description, one link
preview, body `Loading…`), there is no sitemap, and an unknown id answers 200. A search engine
or link-preview fetcher cannot tell one board from another, and cannot list them. This unit
gives each public board its own address and its own head, served by the existing FastAPI app
at request time, with the portal's JavaScript unchanged on top.

Spec: `docs/spec/2026-11-13-board-pages-seo-spec.md`. Plan: `docs/plan/2026-11-13-board-pages-seo.md`.

## Planned changes

- `apps/scoreboard/src/scoreboard/board_pages.py` (new): routes `/benchmarks/{id}/`,
  `/benchmarks/{id}`, `/benchmark.html`, `/sitemap.xml`, `/robots.txt`; page rendering.
- `apps/scoreboard/src/scoreboard/portal.py`: register the routes before the static mount.
- `apps/scoreboard/portal/analytics.js`, `subscribe.js`, `main.js`, `benchmark.js`, `spec.js`:
  read the board id from the path as well as `?id=`; build board links for the clean address.
- `apps/scoreboard/tests/unit/test_board_pages.py` (new), `tests/portal/board-url.test.js` (new).
- `.claude/sdlc.local.md`: name the new Node test file in the scoreboard gate.
- `.github/workflows/scoreboard-tests.yml`: the same, if the workflow names test files.

No model or schema change, so no migration.

## Test plan

- Scored public board: 200, own title, description, canonical, `og:url`, preview tags, heading.
- Unscored public board: the same, plus `noindex`.
- Private board: 200, generic head, `noindex`, no board field in the HTML.
- Unknown id: 404.
- Markup in `display_name`/`focus`/`description` is escaped.
- No relative `href` or `src` remains in a served board page.
- `/benchmark.html?id=x&utm_source=y` answers one 301 that keeps `utm_source`; the bare file is
  still served byte-identical.
- Sitemap lists home, about and scored public boards only; `robots.txt` names the sitemap.
- JS: the board id is read from `/benchmarks/<id>/` and from `?id=`; links use the clean
  address over http(s) and the query form otherwise.
- No existing test is edited.

## Acceptance

- `curl` of a scored board with no JavaScript shows that board's name in `<title>`, the
  description, the canonical and the preview tags.
- "Follow this board" and the Plausible `benchmark` property work on the clean address.
- `uv run .claude/scripts/run_gates.py scoreboard` green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `apps/scoreboard/portal/board-url.js` (new) and one
  `<script>` tag for it in the five portal pages.
- **Commits:** see PR.
- **Gates:** `run_gates.py scoreboard` → ALL GATES GREEN (append-only check, ruff, format,
  pyright, pytest with coverage, node portal tests).
- **Deviations:**
  - **A shared `board-url.js`** holds both address forms, in place of a reader in each script.
    `analytics.js` and `subscribe.js` load on pages where `main.js` does not, and a file named
    `analytics.js` is a common content-blocker target, so neither could own the helper.
  - **Title tagline shortened** to `models & fusions`, limit 70, so the tagline survives on
    81 of 92 boards; at the planned wording and a limit of 60 it survived on almost none.
  - **A store failure answers 503** on the board page and the sitemap, matching the score
    routes. Found because the existing `og:url` test follows the new 301 into a database with
    no schema.
  - **Lead paragraph is `description`, not `focus` then `description`**, so the page reads the
    same before and after `benchmark.js` writes that node.
  - **No existing test edited.** `test_parameter_pages_declare_no_og_url_that_drops_the_shared_item`
    still passes, but its two `benchmark.html?id=` cases now follow the 301 and assert on the
    503 body. They no longer test anything about those addresses; the per-board `og:url` is
    asserted in `test_board_pages.py`. Updating the old test is left to the owners.
- **Not verified:** the pages in a real browser, and a live "Follow this board" submission.
  The id readers are covered by the Node tests only.
