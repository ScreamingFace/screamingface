---
ticket: OME-1135
stack: screamingface
status: in_progress
started: 2026-09-17
finished:
---
# OME-1135 — Live activity in the evaluation widget

## Intent
Expose safe Engine activity while notebook evaluations run. Target PR #980's four-stage contract; the owner explicitly declines older-Engine compatibility.

## Planned changes
- Independent typed activity projection and Logs rendering in Client `_ui`.
- Stage-aware candidate status and independently expandable, grouped activity rows.
- Bounded decoder ID window in `_engine/contract.py`.
- New decoder, projection, widget and local Engine integration checks.

## Test plan
Write failing tests for safe parsing, occurrence/revision isolation, rolling eviction, loss snapshots, historical updates, terminal outcomes, and interactive rendering. Exercise current Engine records through the real Client decoder. Run the screamingface gate runner.

## Acceptance
Four stage labels plus model-call detail; no inference from prose/routes; rolling bounded memory; unknown outcomes remain unknown; results, accounting and callbacks unchanged. Draft PR and Linear In Progress until ready for review.

## Outcome
- Implemented safe activity decoding, rolling history/occurrence summaries, paged, grouped candidate activity, and bounded decoder event-ID window.
- Preserved existing widget assertions; the owner approved extending its fake ipywidgets fixture with the required widget controls. No assertions removed or weakened.
- Removed the pre-existing six-hour ticker cutoff and added a simulated three-day regression. Focused widget/activity/decoder suite: 75 passing; Pyright clean.
- Actual #980 producers passed through the Client decoder: 10 records, five completed operations, zero invalid records. This in-process check is not a hosted full-evaluation test.
- Local stack runs #980 checkout on 9105/9106/9108 with activity full. Jupyter runs on 8888; a separate IFEval notebook copy uses this Client checkout. No paid model calls or publishing performed.
- Full expanded-row gates passed: lint, formatting, types, 95% coverage threshold, notebooks, build and distribution. Commit/PR pending. Activity uses measured durations with unknown current freshness, no extrapolation or inferred provider progress.

## Expanded-row iteration
Owner rejected tab layout and approved replacing it with per-Candidate expansion and stage status. Prior full gate run passed. Write grouping/status/expansion tests first, then replace tab-specific UI/tests. Keep local stack and Jupyter running; do not interrupt an active user kernel.

Expanded-row validation: 92 focused tests passed, including explicit parent grouping, late parents, cross-run isolation, concurrent stages, independent expansion and pagination. Jupyter simulated-event preview verified both rows can remain expanded; no model calls were made. A fresh IFEval-expanded-activity.ipynb is available without resetting the original notebook. Hosted/local full fake-provider evaluation remains an acceptance follow-up before moving the draft to review.

## Terminal-output iteration
Owner explicitly requested flat scrollable terminal-style output instead of inner activity tables. Keep grouping, row expansion and bounded rendering; replace only markup/CSS and migrate the table-count pagination assertions to log-line counts. Validate no table markup and escaped model details, then run Client gates.

Terminal-output outcome: 33 focused checks passed and all Client gates passed (including 95% coverage). Diff review confirmed this is presentation-only: safe escaping, parent grouping, measured durations and stable scroll roots remain. Browser security policy blocked the standalone file preview, so this iteration is not claimed as visually verified in-browser. Fresh IFEval-terminal-activity.ipynb is available for user testing without resetting existing kernels.
