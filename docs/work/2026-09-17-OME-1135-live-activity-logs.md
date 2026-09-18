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

## Contained log-box correction
Owner screenshot shows report-like spacing and right-aligned statuses, inconsistent with requested log box. Replace generic heading markup with isolated log-line classes and enforce a 280px scroll container; keep inline details. Add regression for containment/markup and verify in Jupyter.

Verified the correction in a real Jupyter kernel using simulated records: compact inline lines in a bordered 280px box, with grouped indentation. Screenshot checked. 34 focused tests pass. Existing live evaluation kernels remain untouched.

Contained-box correction: all Client gates passed, including the 95% coverage threshold. Follow-up UX discussion identified that case attribution needs authoritative Engine context; current stage observer carries kind and emitter only.

## Flat, case-aware logs — 2026-09-18
Owner authorized continuing against #980 stacked on #988: remove indentation, routine durations and normal finish reasons; make case/model/stage readable on each model line. Preserve explicit parent grouping, unknown identity, failure/retry information, bounded rendering and disclosure controls. Normalize supplied case IDs with str() without numeric coercion; do not invent case ordinals or infer missing IDs from siblings. Stage records without IDs remain unlabelled. Hosted preview is disabled; proceeded with the existing local-preview workflow after the optional preference question received no reply.

Plan/test: add presentation regressions for interleaved cases, leading-zero IDs, missing identity, failures/retries and flat styling; render actual stacked Engine records through the Client decoder; verify Jupyter light/dark and full Client gates. Owner's removal of routine timing authorizes replacing the old measured-duration display assertion; all privacy/freshness/loss assertions remain. No provider calls initiated by the agent.

Case-aware outcome: 41 focused tests and all Client gates pass (including 95% coverage, notebook/build/distribution checks). Real #980+#988 native producers emitted 16 records through the Client decoder with zero invalid records; cases 42 and 007 rendered correctly in Jupyter light/dark views. A full two-case IFEval run against the local Engine using a literal answer and the Client transport decoded all four stage kinds, with zero invalid records and no provider calls. This transport smoke deliberately bypassed Recipe reconstruction because literal candidates have no Recipe metadata. User notebook IFEval-case-activity.ipynb targets local :9108 and remains unexecuted. No stage-case IDs invented; direct stage attribution remains an Engine follow-up. Existing measured-duration and failure-spelling assertions migrated for the explicitly requested presentation change; privacy, freshness and loss assertions preserved. Self-review: presentation only, safe escaping and explicit identity, no report/accounting/transport changes. Keep draft/In Progress.

## Lifecycle wording preview — 2026-09-18
Owner requested trying a chronological log with selected-case positions, phase boundaries and model identities. First produce a clearly labelled static notebook preview using the existing theme/scroll-box styling. This is a presentation prototype, not real Engine events or a claim of completed integration. No provider calls. Engine inspection confirms stage observation currently lacks case facts and candidate stage starts outside case_scope; case selection ordinals are not supplied. Keep case metadata in #988, stage association/lifecycle production in #980, Client wording/history rendering in #983. Before production wiring, establish authoritative selected-case order/total and whole-case grading completion; do not synthesize these from model arrival or endpoint completion.

Owner approved “Synthesising” wording and separation of case/stage/role. Updated the illustrative notebook's source and saved HTML output consistently, plus the Client spec/plan. No production role attribution or chronological projection implemented in this wording-only step; no runtime behavior changed. Four stages remain unchanged.

## Live chronological projection — 2026-09-18
Owner approved wiring. Render the existing bounded accepted-event history in arrival order, preserving start/retry/terminal transitions and explicit parent-stage attribution. Keep the latest-operation index for current status and freshness; historical records must not be marked as currently stale/active. Pagination counts retained events. Test interleaving, event-page boundaries and terminal resolution before implementation. Missing role and ordinal remain unknown until an authoritative producer contract exists; do not fabricate the complete illustrative preview.

Timeline outcome: 45 focused checks passed and all Client gates passed, including 95% coverage, notebooks, build and distribution. First full run was interrupted during an apparently stalled connection test; that file passed independently (36 tests), then the unchanged full gate rerun passed. Native Engine producers rendered 16 chronological records in a fresh Jupyter notebook with zero invalid records and explicit Case 42/007 labels. No provider requests. Self-review: no new unbounded index, escaped safe fields only, latest-state freshness stays separate from historical transitions, explicit parentage only, no existing tests modified. Remaining semantic-role work is already owned by OME-699; selected-case ordinals and whole-case grading boundaries are not implemented here.


## Selected-case numbering — 2026-09-18

Owner approved explicit selected-case positions alongside IDs. Update safe decoding and flat log prefix to [Case n/N], with ID fallback. No inference, model role additions or layout changes. Test independent candidates, dropped/replayed records and malformed pairs; run full Client gates.

Numbering consumer outcome: seven new tests passed after RED, including ten independent candidates and out-of-order arrivals, plus malformed/missing position pairs. Existing timeline tests pass unchanged. Full Client gates green (lint, format, types, full test suite/95% coverage, notebooks, build and distribution). Preserves ID fallback and bounded history; no provider requests. Producer integration remains pending the #988 test migration approval.
