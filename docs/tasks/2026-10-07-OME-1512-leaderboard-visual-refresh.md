---
id: OME-1512
linear_url: https://linear.app/openmined/issue/OME-1512/refresh-the-leaderboard-portal-curated-benchmarks-card-led-landing
status: in_progress
type: task
priority: 3
labels: [scoreboard, agentic, autonomous]
created: 2026-10-07
closed:
---

# Refresh the leaderboard portal: curated benchmarks, card-led landing, Pareto axes at 0

Parent epic: OME-1282 (Leaderboard clearly shows the Pareto-frontier wins and open-frontier wins).

Visual/UX refresh of the scoreboard portal (`apps/scoreboard/portal`), driven in a live-iteration
session:

- **Featured shortlist** — the tab strip and the index catalogue lead with a curated five
  (DRACO 3-Pass, ContractEval, FrontierScience, HealthBench Professional, IFEval); the long tail
  folds into a searchable "More benchmarks" overlay (`partitionFeatured`, `filterBenchmarks`).
- **Card-led landing** — the index table becomes a grid of white clickable cards (title · focus ·
  ≤100-char description · best reproducible + a gold "→"), revealed 9 at a time; a classic hero
  (gold eyebrow, Parastoo serif title, subtitle, Reproducible/Unverified/Solo definitions, one
  monochrome button), gold+blue accents, a small "Catalogue" label.
- **Pareto axes anchored at 0** — score floor `min(0, lowest)` (never crops negative boards),
  linear cost floors at 0; wide-cost (log) boards keep their positive minimum.
- **Cleaner board** — the per-benchmark page drops the old "Read this first" note and the Pareto
  caption; the terminal "about" note moves under the benchmark description.

Spec: docs/spec/2026-10-07-leaderboard-visual-refresh.md
Plan: docs/plan/2026-10-07-leaderboard-visual-refresh.md
Ledger: docs/work/2026-10-07-OME-1512-leaderboard-visual-refresh.md
