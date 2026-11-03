---
id: OME-1688
linear_url: https://linear.app/openmined/issue/OME-1688/refresh-the-leaderboard-landing-colab-notebook-and-about-page-papers
status: in_progress
type: task
priority: 3
labels: [scoreboard, agentic, autonomous]
parent: OME-1282
created: 2026-10-20
closed:
---

# Refresh the leaderboard landing and About page

Leaf under epic OME-1282 (leaderboard launch surfaces); unblocks the deferred OME-1595
about-page "citation" item.

- **Landing** (`index.html`) — hero + CTA beside an academic-style **quality–cost frontier figure**
  (fusion vs single-model lines, gold band, plotted sample runs, serif axes), above the live Browse
  grid. Title "The leaderboard for fusi[😱]ns." (mark set as the o); subtitle "The first verified map
  of the quality–cost frontier for multi-model systems: ensembles, routers, cascades,
  mixture-of-agents, and more."
- **About** (`about.html`) — rewrite (no carousel): new hero/evidence copy, a centered reading
  column, and the sections (how a result gets on a leaderboard, how to read it, how the map is drawn,
  contribute, who builds this).
- **All pages** — em-dash → middot in the `<title>` / link-preview metadata (house style).

Design evolved during live iteration with Irina: the landing started as a Colab notebook, then a
features panel, and finally the frontier figure; the About papers carousel was explored then dropped.

Ledger: `docs/work/2026-10-20-leaderboard-copy-and-papers-carousel.md`.
