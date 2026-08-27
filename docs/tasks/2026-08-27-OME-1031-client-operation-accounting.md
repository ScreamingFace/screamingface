---
id: OME-1031
linear_url: https://linear.app/openmined/issue/OME-1031/decode-and-render-per-operation-evaluation-accounting
status: backlog
type: task
priority: P2
labels: [py-screamingface, autonomous, agentic]
created: 2026-08-27
closed:
---

# Decode and render per-operation evaluation accounting

Python Client implementation child of OME-901. Decode accounting on Candidate `CaseOperation` and
grading `Evidence`, expose computed exact-only summaries, and render the completed-Report SFDS
operation breakdown without changing score calculation or the live evaluation widget.

The Client regression suite must pin the existing boundary in one run: detailed generic live
events reach `on_event`, while the terminal outcome/Report retains only root usage until the new
retained semantic projection is decoded. CorrectiveLoop's unprojected nested work must remain an
explicit remainder rather than be assigned to a member or role.

Populate `MemberResult.usage` where exact, keep `MemberResult.duration_ms` null, label the existing
Gateway latency as Provider time, and reconcile exact remainder for cost only.

Blocked by OME-1030 and by explicit approval of
`docs/plan/2026-08-27-OME-901-operation-accounting.md`.

Spec: `docs/spec/2026-08-27-OME-901-operation-accounting.md`.
Parent: OME-901.
