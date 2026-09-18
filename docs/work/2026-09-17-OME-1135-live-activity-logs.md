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

## Dynamic-line presentation prototype

Owner asked to try one stable row per operation with a spinner/checkmark, suppressing redundant Answering stage lifecycle lines. Created the explicitly simulated, throwaway `.docs/OME-1135/dynamic-activity-prototype.html` and `Dynamic-activity-preview.ipynb`. Existing issue/spec covers live activity; this is visual exploration before changing the production projection. Same DOM row updates through running, retrying, completed, failed and unknown; fixed-width markers, neutral checks, reduced-motion support. No model calls, server writes or production code changes. Numbering test-migration permission remains pending and is unrelated to this UI preview.


## Dynamic operation lines — approved implementation

Owner approved finishing the dynamic log view only. Implement the validated prototype as a latest-state projection of existing activity data, without changing Engine or protocol. Preserve all safe metadata, unknown-state semantics, raw bounded history and independent candidates. Presentation test migrations reflect this explicitly approved layout change; Engine snapshot migration remains pending.

Dynamic view outcome: 62 activity tests passed; full Client gates green (ruff, formatting, pyright, full pytest with 95% threshold, notebook checks, build and distribution). Initial lint failure in description complexity was fixed by extracting stage wording; no thresholds weakened. Existing presentation assertions migrated under the approved dynamic-view scope; history/order/loss/privacy assertions preserved. Actual Client widget verified in Jupyter with simulated structured events, live replay, running spinner and completed checks; no provider requests. Preview: `.docs/OME-1135/Dynamic-log-widget.ipynb`.

Wisdom review: reuse the existing bounded latest-operation index rather than adding another state machine or dependency. No Engine/public schema/report change. Explicit parentage is the only basis for stage labels and suppression; failures and unknown outcomes remain visible. All rendered text is escaped. Scroll ownership stays in the persistent widget; inner HTML is refreshed as a unit, so this does not promise stable individual DOM nodes. Role attribution and pending Engine numbering migration remain out of scope. Draft/In Progress retained. Commit: `feat(client): update activity lines in place` (Refs: OME-1135).

## Active case in candidate status

Owner approved adding the explicit active case position to the table status (Answering · Case 3/5), while leaving the Cases column unchanged. Reuse safe stage facts; never derive current position from completion counts. Concurrent stages retain their own labels; missing positions preserve the existing stage-only label. Add regression coverage, run Client gates, keep #983 draft.


Owner correction: status stays stage-only (Answering); the Cases cell displays the explicit active position (3 / 5). Completed-case accounting remains unchanged internally and remains the fallback when no fresh numbered stage is available. Concurrent positions remain distinct; no inference from arrival order. This supersedes the status-label proposal above.

Active Cases cell outcome: five new tests cover explicit active positions, concurrent candidate isolation, missing numbering, stale/terminal records and unchanged completed accounting. All Client gates green, including append-only, full coverage, notebooks/build/distribution. Initial test fixture used an incompatible SimpleNamespace; replaced with the real typed candidate-progress model. Prior tests unchanged. Wisdom review: reuses validated stage facts and freshness policy, no new durable state or Engine dependency. Status stays stage-only; only fresh explicit positions override the Cases presentation. Missing numbering preserves the existing fallback. Draft #983 retained.

## Inline row disclosure

Owner approved an inline chevron, whole-row click/keyboard expansion, and logs nested inside the same candidate boundary. Use the existing native toggle as a full-row hit target over the noninteractive summary, preserving widget expansion state and scroll roots without JavaScript or new dependencies. Shared border encloses summary and details. Verify real Jupyter pointer/keyboard behavior and independent expansion, then Client gates.


Owner requested timestamps: show a quiet HH:MM:SS UTC first-observed time per operation, fixed across updates. Full date and timezone in tooltip; bounded index evicts with latest operation. Invalid calendar dates must not break rendering. Duplicate Grading lines remain distinct operations pending Engine case-level grouping.

Inline disclosure verified in live Jupyter: far-right summary click, Space keyboard toggle, independent candidate expansion and scroll without collapse. Native toggle remains accessible; logs share the row border. Initial full Client gates passed. Timestamp regression tests passed after RED: fixed across revisions, eviction with operation, and out-of-range calendar fallback. Visual preview verified using production widgets and simulated events; no provider calls. Full gates rerunning for timestamp addition.

Owner requested completed wording: Answered, Graded and Scores aggregated on success; active and failure wording remain distinct. Same dynamic operation line and timestamp.

Past-tense change: seven new outcome-wording cases passed after RED; all 78 activity tests green. Migrated only prior presentation assertions for the owner-requested wording using the explicit append-only exception; behavioral, ordering, history and failure assertions preserved. Full Client gates running on final code.

Final outcome: all Client gates green on disclosure, timestamps and past-tense wording. Visual checks passed in production Jupyter widgets. Wisdom review: no new frontend dependency or execution behavior; timestamps are per-operation first observation, not fabricated start times, and share eviction with the bounded latest index. Draft status retained.
