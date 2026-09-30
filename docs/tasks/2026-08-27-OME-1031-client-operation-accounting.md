---
id: OME-1031
linear_url: https://linear.app/openmined/issue/OME-1031/render-per-operation-evaluation-accounting-in-completed-reports
status: in_progress
type: task
priority: P2
labels: [client-sf, autonomous, agentic]
created: 2026-08-27
closed:
---

# Render per-operation evaluation accounting in completed Reports

Python Client implementation child of OME-901. Use decoded accounting on Candidate `CaseOperation` and
grading `Evidence`, expose computed exact-only summaries, and render the completed-Report SFDS
operation breakdown without changing score calculation or the live evaluation widget.

The Client regression suite must pin the existing boundary in one run: detailed generic live
events reach `on_event`, while the completed Report's breakdown uses retained semantic records.
CorrectiveLoop's unprojected nested work must remain an
explicit remainder rather than be assigned to a member or role.

Populate `MemberResult.usage` where exact, keep `MemberResult.duration_ms` null, label the existing
Gateway latency as Provider time, and reconcile exact remainder for cost only.

Engine retention (OME-1030) and Client decoding (OME-1032) are delivered.

2026-09-28: implementing the remaining derived views and completed-report table, plus an offline
review notebook. User requested a draft PR. Ledger: `docs/work/2026-09-28-report-accounting.md`.

Spec: `docs/spec/2026-08-27-OME-901-operation-accounting.md`.
Parent: OME-901.
