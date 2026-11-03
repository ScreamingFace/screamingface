---
ticket: OME-1309
stack: scoreboard
status: done
started: 2026-11-03
finished: 2026-11-03
---

# OME-1309 — Put imported results in the regular table

## Intent

User explicitly requested removing extra prose/separate presentation, and selected
“Same table and sorting, with normal rank numbers.” This replaces the original
unranked-section decision; the PR's new tests must follow that approved contract.

## Planned changes

External-row normalization/presentation, main table selection and rendering, scoped
neutral CSS, removal of the separate section and superseded screenshots, exact
behavior assertions, and updated spec/plan/PR description.

## Test plan

RED/GREEN for shared score-based ranks and header sorting; top-50 selection after
merge; stable ties; external-only, mixed, empty and invalid data; exact field checks;
absolute source URLs and text safety; no fabricated run data or recipe actions.
Run four timezones, full scoreboard gates, and light/dark/mobile visual checks.

## Acceptance

One table, ordinary ranks, gray external rows, source actions and no added prose.
Existing community-only behavior and provenance remain intact. No Linear writes.

## Outcome

- Shared top-50 table, score-based ranks and all existing header sorts implemented.
  External rows are gray with source actions; no separate heading, paragraph, label,
  or notes column. Accessible text/hover retains origin and reproduction limitations.
- Selection merges before limiting, so baselines below the fetched community page
  do not receive invented global ranks. Stable ties keep community order first.
  Table summary/score bars include the displayed rows; cost chart excludes imports.
- Review fixes: structural URL parsing, exact cell/attribute checks, timezone-aware
  date assertions, stdlib HTML parsing for markup checks, and removal of committed
  screenshots. Browser captures are ignored and remain local only.
- RED: seven shared-table JS checks and the HTML structure test failed against the
  old presentation. GREEN: all 12 JS cases and the structural test passed.
- Timezones: 12/12 pass in UTC, Pacific/Pago_Pago, Pacific/Auckland and
  Pacific/Kiritimati.
- Full scoreboard gate runner: ALL GATES GREEN, including lint, formatting,
  typecheck, Python coverage gate and all portal JS tests. No pre-existing main
  tests changed; this PR's new assertions were revised for the owner's new contract.
- Visual checks: light/dark desktop, 390px mobile (page width stays 390px; table
  scrolls inside its 356px region), and a local mixed fixture with an explicitly
  synthetic measured row between the actual two imported records. No dev writes.
- Review: no backend/schema changes or new dependencies; records are copied before
  assigning view ranks, imports cannot gain recipe buttons or frontier marks, and
  unknown run fields remain dashes. Gray styling retains legible theme tokens.
- Follow-up to PR #1644. No Linear writes, shared deployment or production changes.
- Commit: `feat(scoreboard): integrate external results into ranked table`.
