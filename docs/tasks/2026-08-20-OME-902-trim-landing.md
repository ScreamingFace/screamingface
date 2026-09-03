---
id: OME-902
linear_url: https://linear.app/openmined/issue/OME-902/trim-scoreboard-landing-drop-stats-strip-dataset-column-focus-shows
status: in_progress
type: task
priority: medium
labels: [scoreboard, agentic, autonomous]
created: 2026-08-20
closed:
---

# Trim scoreboard landing: drop stats strip + Dataset column

Slim the scoreboard portal landing page (`apps/scoreboard/portal/`) for the leaderboard MVP.
Frontend-only (static HTML + vanilla JS); no Python/API/model changes.

Changes: (1) remove the three-cell stats strip (Benchmarks / Datasets published / Newest
benchmark) + the now-dead `updateIndexStats`/`formatDateOnly` in `main.js`; (2) remove the
Dataset column (`<th>` + the `<td>` block in `benchmarkRow`) + the orphaned
`publishedDataFileName`.

The Focus column is left unchanged — it still renders the editorial `b.focus` field (a
mid-PR change to preview `description` there was reverted per owner: the description already
shows as the name-subtitle, so previewing it in Focus duplicated it).

Owner decisions: Focus keeps editorial copy; name-subtitle stays. Out of scope: backend/
model/schema, benchmark detail page, CSS, portal test gate / CI wiring.

Ledger: `docs/work/2026-08-20-OME-902-trim-landing-table.md`
