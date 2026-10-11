---
id: OME-1572
linear_url: https://linear.app/openmined/issue/OME-1572/track-interrupted-saved-reports-and-show-notebook-recovery-guidance
status: in_progress
type: feature
priority: high
labels: [client-sf, agentic, autonomous]
created: 2026-10-11
---

# Track interrupted saved reports and show notebook recovery guidance

Fifth/final SDK slice from #1156 after #1241, #1269, #1345 and #1347 merged. Parent epic OME-1294. Separate Engine/runtime artifact persistence #1217 remains outside this slice.

Track evaluation, JSON export, notebook display and explicit recovery in saved manifests. Show the shared informational notice once per saved evaluation/store at notebook startup for this Engine if the unfinished owner demonstrably exited. Include explicit sf.reports.get guidance without automatic recovery or model calls.

Preserve legacy silence, healthy/active/headless/inaccessible-owner silence, current partial reports and corrupt-sibling safeguards, overlapping operations and cancelled recovery across both stores. Optional metadata/display failures must not abort useful SDK operations, and marker paths cannot follow symlinks outside evaluations.

Spec/plan/work: docs/{spec,plan,work}/2026-10-11-report-lifecycle.md. Before/after fixture screenshots: docs/screenshots/2026-10-11-report-lifecycle/. All SDK gates pass (96% coverage), 48 new regression cases pass, and both independent reviews have zero remaining findings. Draft prepared for owner review.

Draft #1348 follow-up: keep the prepared evaluation scope active while saved Candidate recovery/export/display completes. Preserve candidates_failed settlement, cancellation/unexpected errors, transport cleanup and interrupted Candidate operations. Added 23 regressions; all 71 lifecycle/notice cases and full SDK gates pass (96.18% coverage), with zero remaining Standards/Spec review findings.

Draft #1348 shared-store follow-up: coordinated POSIX updates preserve live foreign evaluation ownership and all outstanding owners remain discoverable after death, including older markers and overlapping presentation. Sync/async all-corrupt evaluation selection now runs inside recovery tracking and settles handled failure ready; existing saved-key errors remain unchanged. Added 14 real-process/selection regressions, bringing focused lifecycle/notice coverage to 85 cases. All final SDK gates pass (96.18% coverage); Standards and Spec reviews have zero remaining findings. Existing tests and UI unchanged.
