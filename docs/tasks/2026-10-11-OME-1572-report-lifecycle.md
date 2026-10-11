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
