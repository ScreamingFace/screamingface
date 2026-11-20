---
ticket: OME-1917
stack: scoreboard
status: done
started: 2026-11-19
finished: 2026-11-19
---

# OME-1917 — Collapse leaderboard search behind a less prominent button

## Intent

The leaderboard homepage's "Browse latest benchmarks" catalogue shows a full search
input ("Search benchmarks") at equal visual weight to the section heading. Per
OME-1917 (parent epic OME-1915, "Improve UX of the leaderboard"), the search bar
should start collapsed behind a less prominent button; clicking the button expands
the search bar in place. This reduces visual weight on first paint without removing
the ability to search.

## Planned changes

- `apps/scoreboard/portal/index.html` — wrap the existing `.catalog-search` label +
  input in a new `#benchmark-search-wrap` (keeps the `catalog-search` class/layout),
  hidden by default, and add a `#benchmark-search-toggle` quiet button
  (`class="btn ghost"`, the design system's documented "secondary/quiet action"
  rung) with `aria-expanded`/`aria-controls` wired to it.
- `apps/scoreboard/portal/catalog.js` — look up the new toggle button + wrap by id
  (both optional, defensive null-checks) and wire a click handler: toggle
  `wrap.hidden`, flip `aria-expanded`, focus the search input when expanding. Do
  not touch the existing `scored`/`search`/`more` wiring or any other node lookup.
- `apps/scoreboard/tests/portal/catalog-search-toggle.test.js` (new) — DOM-shim
  test for the toggle, following the `vm.runInNewContext` + hand-rolled element()
  convention used by `catalog.test.js`.
- `.claude/sdlc.local.md` (scoreboard gates) and
  `.github/workflows/scoreboard-tests.yml` — add the new test file by name to the
  explicit portal-JS test list, per the existing "NAMED EXPLICITLY, never a glob"
  convention (OME-798) so local gates and CI stay in agreement.

## Test plan

- Collapsed by default: the wrap starts hidden, the toggle starts
  `aria-expanded="false"`.
- Clicking the toggle expands the wrap (`hidden` cleared), sets
  `aria-expanded="true"`, and moves focus into the search input.
- Clicking again collapses the wrap and resets `aria-expanded="false"`.
- The existing search/filter behavior (typing in the now-visible input) still
  reaches `catalog.js`'s existing `applyFilters` path — i.e. the toggle is purely
  additive and does not change filtering.
- A DOM fixture that omits the new toggle/wrap nodes (the three existing
  `catalog.test.js` / `catalog-accessibility.test.js` / `catalog-session.test.js`
  fixtures) must keep passing unmodified — the new wiring is defensive against
  missing nodes.

## Acceptance

- On load, the leaderboard homepage's benchmark search input is not visible; a
  quiet "Search benchmarks" button is shown in its place within the controls row.
- Clicking the button reveals the search input (and only the input — the "Has
  scores" checkbox and the result count stay as they are) and focuses it.
- Clicking the button again collapses it back.
- All prior portal JS tests remain green and unmodified.

## Outcome

- **Actual files:** as planned —
  `apps/scoreboard/portal/index.html`, `apps/scoreboard/portal/catalog.js`,
  `apps/scoreboard/tests/portal/catalog-search-toggle.test.js` (new),
  `.claude/sdlc.local.md`, `.github/workflows/scoreboard-tests.yml`,
  plus this ledger and the `docs/tasks/` mirror.
- **Commits:** `feat(scoreboard): collapse leaderboard search behind a toggle button` (this unit's commit; see PR for the sha).
- **RED:** 3 of 5 new assertions in `catalog-search-toggle.test.js` failed first
  (wrap visible/aria-expanded unset before the toggle existed); the other 2
  (search-still-filters, missing-nodes-is-safe) passed trivially since nothing
  existed yet to break them — expected for additive, defensively-guarded code.
- **GREEN:** all 5 new assertions pass; full `run_gates.py scoreboard` is green —
  append-only test check, `ruff check`, `ruff format --check`, `pyright`,
  `pytest --cov=scoreboard --cov-fail-under=80 -q` (92.35% coverage), and every
  named `node --test` step (235 portal JS tests total across all CI-equivalent
  files, including the 5 new ones).
- **Wisdom review:** reused the design system's documented "quiet" `.btn.ghost`
  rung (style.css's own comment: "Secondary/quiet actions use .btn.ghost") rather
  than inventing new CSS; reused the existing `.catalog-controls [hidden] {
  display:none }` rule rather than adding new rules; kept the toggle a plain
  inline disclosure (no outside-click/Escape machinery) since, unlike the
  floating "More benchmarks" menu in main.js, this reveals content in normal
  page flow rather than an overlay — added complexity would have been
  speculative generality. No prior test was touched; the append-only gate
  confirms it. No schema/migration/ORM/secret touched.
- **Public-asset discipline:** caught and fixed by
  `test_portal_static.py::test_every_served_asset_carries_no_internal_references`
  — my first pass left `OME-1917` and a `FEATURE:` anchor in the HTML/JS
  comments, which that gate correctly rejects (portal/ is served verbatim to the
  public). Rewrote both comments to plain prose with only `WHY:`, matching the
  rest of the portal's own comment style.
- **CI/gate wiring:** added `catalog-search-toggle.test.js` by name to both
  `.claude/sdlc.local.md`'s scoreboard gate and
  `.github/workflows/scoreboard-tests.yml`'s "Catalog summary UI regressions"
  step, per `test_portal_ci_wiring.py`'s guard (OME-798 convention) — confirmed
  green only after both were updated.
- **Manual check:** seeded a local SQLite scoreboard DB, ran the real FastAPI
  app, and confirmed via `curl` that `index.html` serves the collapsed button +
  hidden search wrap exactly as authored. A live-browser screenshot (chrome-devtools
  MCP) was attempted but the shared browser profile was locked by another
  concurrent session; skipped rather than force-killing another session's
  browser. Recommend an optional owner spot-check of the expand/collapse
  interaction and focus behavior in a real browser.
- **Deviations:** none from the plan besides the public-asset comment fix
  above (not a scope change, a correctness fix caught by an existing gate).
