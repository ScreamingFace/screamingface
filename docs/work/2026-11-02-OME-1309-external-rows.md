---
ticket: OME-1309
stack: scoreboard
status: done
started: 2026-11-02
finished: 2026-11-02
---

# OME-1309 — Display imported external results

## Intent

Expose imported baselines as gray, unranked source-backed rows on the benchmark
page. Preserve the ranked-results experience while product policy remains open.

## Planned changes

Portal renderer, benchmark page wiring/markup, scoped neutral CSS, behavior tests,
CI/local test registration, spec, plan, and issue mirror.

## Test plan

RED then GREEN for real page rendering with external-only/mixed/empty/error data,
unsafe URLs and text, missing metadata, and native score formatting. Verify rank,
summary, chart and copy behavior remains restricted to community submissions.
Run scoreboard gates; inspect light/dark desktop and mobile previews.

## Acceptance

Imported rows show model/score/date/source and comparison note, explicitly not
reproducible, without ranks or recipes. Existing pages without baselines unchanged.

## Outcome

- Implemented a separate unranked external-results table with neutral styling,
  native scores, import dates, safe source links, and comparison notes. Missing
  details stay unknown. Existing community results and approved launch copy remain.
- RED: 7 new behavior checks failed before implementation; 5 absence/error checks
  already passed. GREEN: all 12 new checks passed. Prior tests were not changed.
- Gates: `uv run .claude/scripts/run_gates.py scoreboard --base 834c3086a` —
  **ALL GATES GREEN** (append-only check, ruff lint/format, pyright, full Python
  suite with >=80% coverage, and all explicitly registered portal tests).
- Visual QA: local preview using the captured dev API response; light/dark desktop
  and 390px mobile inspected. Two rows render, no JS errors; page width stays 390px
  while the table scrolls within its 356px region. Screenshots in
  `output/playwright/e20-external-section-light.png`, `e20-external-section-dark.png`,
  and `e20-external-mobile.png`.
- Review: presentation-only; no database/API changes, new dependencies, rank or
  chart changes. Reuses existing score/date/link/DOM helpers. Untrusted data remains
  text and source links are restricted to absolute HTTP(S) URLs. Unknown metadata
  does not fabricate compatibility. The small renderer keeps the page logic separate.
- Scope: first display increment only. Editing/history, automated source refresh,
  source health, and final ranking/comparability policy remain open in E20.
- No Linear writes; existing epic is the tracking item. No production data or
  shared deployment changes in this PR. Existing dev rows were imported separately.
- Commit: `feat(scoreboard): display external results with source attribution`.

## Superseded presentation

The 2026-11-03 owner decision replaces this separate/unranked view with shared table
sorting and normal rank numbers. See `docs/work/2026-11-03-OME-1309-shared-table.md`.
The original screenshot files are retained locally but removed from the PR tree;
review captures are not shipped on main.
