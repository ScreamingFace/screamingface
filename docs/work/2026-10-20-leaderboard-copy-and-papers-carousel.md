---
ticket: OME-1688
stack: scoreboard
status: in_progress
started: 2026-10-20
finished:
---

# leaderboard-copy-and-papers-carousel — landing + about refresh (Colab landing, papers carousel)

## Intent

Refresh the public leaderboard launch surfaces. The landing (`index.html`) is reframed around
the category ("fusions & routers" / "composed AI systems") and the mission ("the core of
sovereign, pro-human AI"), with a compact top band — hero + CTA beside a **Colab-style
notebook** that loads a copied url4 (`sf.load` → a `Fusion(...)` ensemble repr) and reproduces
its score (`sf.evaluate` → score/cost/cache) — above the live Browse grid so the grid clears
the fold. The About page is rewritten to explain how a result gets on a board / how to read it /
how the map is drawn, with an inline **papers carousel** (the most-cited ensemble/router/
multi-agent results, as first-page arXiv thumbnails) proving "combinations beat single models".
Unblocks the OME-1595 about-page "citation" item; filed as its own leaf under epic OME-1282.

## Changed files

- `apps/scoreboard/portal/index.html` — Layout A: hero + CTA | Colab notebook (`.colab`), then
  the live Browse grid. Title "The leaderboard for fusions & routers." (no o-mark); subtitle
  "…for composed AI systems: the core of sovereign, pro-human AI." (house style: colon).
- `apps/scoreboard/portal/about.html` — rewrite into evidence + papers carousel, "How a result
  gets on a leaderboard", "How to read the leaderboards", "How the map gets drawn", "Contribute",
  "Who builds this"; short same-length rule under the subtitle + each section header.
- `apps/scoreboard/portal/portal.css` — `.colab`/`.frepr` notebook CSS, `.la-top` band, the
  `.papers` inline carousel + `.paper-card` thumbnails, `.about-evidence` layout; removed the dead
  legend CSS (`.defs-lead`, `.hero-defs`, `.kv .dt-repro`, `.about-evidence__head`).
- `apps/scoreboard/portal/papers.js` — about carousel: one paper at a time, auto-switch every 3s,
  pause on hover/focus, reduced-motion aware.
- `apps/scoreboard/portal/assets/papers/*.jpg` — 11 vendored arXiv first-page thumbnails.
- `apps/scoreboard/tests/unit/test_portal_launch_copy.py`, `test_portal_static.py` — re-pin the
  About copy/structure to the new text, add carousel assertions, drop the obsolete hero-mark test.

## Test plan

- About lead / recipe / contribute sentences re-pinned, still dash-free (house rule); url4 stays a
  plain docs link; carousel = 11 arXiv thumbnails, each image-only link, new-tab, with alt text.
- Grant banner + rail invariants unchanged on every page; `data-section="catalogue"` preserved.

## Acceptance

- `run_gates.py scoreboard` green (ruff, format, pyright, pytest ≥80%, node portal suite).
- Landing renders Layout A + Colab + live grid; About renders the rewrite + the thumbnail carousel;
  both light and dark.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as listed above (design evolved from a terminal receipt to the Colab notebook
  during live iteration with Irina; three throwaway layout previews explored then deleted).
- **Commits:** <sha — message>
- **Gates:** run_gates.py scoreboard — ALL GATES GREEN (append-only vs HEAD ✓; ruff/format/pyright ✓;
  pytest 1442 passed, 91.6% cov; node portal suite ✓). CI (scoreboard-tests.yml) runs the raw gates.
- **Deviations:** landing uses a Colab notebook (not the terminal first explored); about evidence
  copy lightly edited by Irina post-rewrite (tests re-pinned to match).
