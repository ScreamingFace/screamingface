---
ticket: OME-1688
stack: scoreboard
status: in_progress
started: 2026-10-20
finished:
---

# leaderboard-copy-and-papers-carousel — landing + about refresh (frontier figure)

## Intent

Refresh the public leaderboard launch surfaces. The landing (`index.html`) is reframed around
the category ("fusions" / "multi-model systems") and leads with the thesis as a figure: a compact
top band pairs the hero + CTA with an academic-style **quality–cost frontier chart** (the fusion
frontier above the single-model frontier, the gold band between them the accuracy gained, with
sample runs plotted as points), above the live Browse grid so the grid clears the fold. The About
page is rewritten to explain how a result gets on a leaderboard / how to read it / how the map is
drawn. Unblocks the OME-1595 about-page "citation" item; filed as its own leaf under epic OME-1282.

## Changed files

- `apps/scoreboard/portal/index.html` — hero + CTA beside a borderless `<figure class="frontier">`
  SVG (fusion/single-model frontier lines, gold band, plotted points, italic-serif axes), then the
  live Browse grid. Title "The leaderboard for fusi[😱]ns." (the vendored mark set as the o, with an
  `aria-label`); subtitle "…for multi-model systems: ensembles, routers, cascades, mixture-of-agents,
  and more."
- `apps/scoreboard/portal/about.html` — rewrite (no carousel): new hero + evidence copy, a centered
  reading column, "How a result gets on a leaderboard", "How to read the leaderboards", "How the map
  gets drawn", "Contribute", "Who builds this"; short same-length rule under subtitle + each header.
- `apps/scoreboard/portal/portal.css` — `.frontier` figure CSS (borderless, serif axis/label
  lettering) + `.la-top` band; removed the interim `.colab`/`.frepr` notebook, `.features`/`.feature`
  panel, `.papers`/`.paper-card` carousel, and dead legend CSS.
- `apps/scoreboard/portal/{benchmark,data,spec}.html` — em-dash → middot in the `<title>` /
  link-preview metadata (house style; applied site-wide for consistent previews).
- `apps/scoreboard/tests/unit/test_portal_launch_copy.py`, `test_portal_static.py` — re-pin the
  About copy/structure and the submission-history title to the new text; drop the carousel and
  hero-mark assertions.

## Test plan

- About lead / recipe / contribute sentences re-pinned, still dash-free (house rule); url4 stays a
  plain docs link.
- Grant banner + rail invariants unchanged on every page; `data-section="catalogue"` preserved.
- Page `<title>` previews carry the middot, not an em-dash.

## Acceptance

- `run_gates.py scoreboard` green (ruff, format, pyright, pytest ≥80%, node portal suite).
- Landing renders the hero + frontier figure + live grid; About renders the rewrite; both themes.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as listed above. Design evolved during live iteration with Irina: the landing
  passed through a terminal receipt → Colab notebook → features panel before landing on the frontier
  figure; the About papers carousel (11 vendored arXiv thumbnails) was explored then dropped. All
  interim scratch (previews, carousel assets, papers.js) removed.
- **Commits:** <sha — message> (squash-merge of PR #1497).
- **Gates:** run_gates.py scoreboard — ALL GATES GREEN (append-only vs HEAD ✓; ruff/format/pyright ✓;
  pytest ≥80% cov; node portal suite ✓). CI (scoreboard-tests.yml) runs the raw gates.
- **Deviations:** the chart serif is a system fallback (Georgia/Times) proposing the Computer-Modern
  feel — a small type-law exception to reconcile with the brand serif in a follow-up.
