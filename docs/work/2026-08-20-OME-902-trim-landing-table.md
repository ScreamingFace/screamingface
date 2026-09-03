---
ticket: OME-902
stack: scoreboard
status: in_progress
started: 2026-08-20
finished:
---

# OME-902 — Trim scoreboard landing: drop stats strip + Dataset column

## Intent

Slim the scoreboard portal landing page for the leaderboard MVP: remove the three-cell stats
strip (Benchmarks / Datasets published / Newest benchmark) and the Dataset column from the
benchmarks table. Frontend-only change to the static portal — no Python/API/model changes.
The Focus column is left showing the editorial `b.focus` field (unchanged from `main`).

## Planned changes

- `apps/scoreboard/portal/index.html` — delete the `.stats` strip; delete the Dataset `<th>`.
- `apps/scoreboard/portal/main.js` — delete the Dataset `<td>` block; delete the now-dead
  `updateIndexStats` (+ its call in `initIndex`), `formatDateOnly`, and `publishedDataFileName`.
  Focus cell keeps rendering `b.focus`. Keep `httpUrlOrNull` (exported, used by
  benchmark.js/spec.js) and `benchmarkSubtitle` (name-subtitle stays per owner).

## Test plan

- No new automated test (owner decision — see Deviations). The Focus truncation is inline
  display logic in `main.js`, which has no test harness (the portal JS gate runs only the pure
  ranking logic in `leaderboard-logic.js`).
- Guard against regression via the existing gates staying green + manual verification:
  `node --check portal/main.js`; orphan grep for removed helpers/IDs; existing
  `leaderboard-logic.test.js` still passes; eyeball the served page.

## Acceptance

- Landing page shows no stats strip between the "Get started" button and the Benchmarks heading.
- Benchmarks table header has 5 columns (Benchmark · Focus · Fusions · Best reproducible ·
  Open); no Dataset column; every row appends exactly 5 `<td>`s.
- Focus cell shows the editorial `b.focus` field (unchanged from `main`), em dash when absent.
- No dangling references to `updateIndexStats` / `formatDateOnly` / `publishedDataFileName` /
  `stat-benchmarks` / `stat-datasets` / `stat-newest`; `httpUrlOrNull` still present + exported.
- `run_gates.py scoreboard` green.

## Outcome

- **Status:** done.
- **Actual files:** `apps/scoreboard/portal/index.html` (stats strip + Dataset `<th>`
  removed) and `apps/scoreboard/portal/main.js` (Dataset `<td>` block, `updateIndexStats` +
  call, `formatDateOnly`, and `publishedDataFileName` removed; Focus cell keeps `b.focus`;
  `httpUrlOrNull` + `benchmarkSubtitle` kept). Plus this ledger and the `docs/tasks/` mirror.
- **Commits:** `fix(scoreboard): trim landing — drop stats strip + Dataset column`
  (Refs: OME-902).
- **Gates:** `run_gates.py scoreboard` — ALL GREEN (append-only check, ruff check, ruff
  format --check, pyright, pytest --cov=scoreboard --cov-fail-under=80, node --test
  leaderboard-logic.test.js). Extra verification: `node --check portal/main.js` OK; orphan
  grep clean (no `updateIndexStats`/`formatDateOnly`/`publishedDataFileName`/`stat-*`);
  `benchmarkRow` appends exactly 5 `<td>`s matching the 5-column header.
- **Deviations:** By owner decision, no new automated test — `main.js` is not test-covered by
  design (the JS gate runs only the ranking logic in `leaderboard-logic.js`); wiring a
  `main.js` test into the gate/CI is separate work.
- **Owner-verify:** eyeball the served landing page against a seeded benchmark — confirm no
  stats strip, no Dataset column, and Focus shows the editorial focus.
