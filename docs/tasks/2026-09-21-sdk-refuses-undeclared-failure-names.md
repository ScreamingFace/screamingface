---
id: OME-1235
linear_url: https://linear.app/openmined/issue/OME-1235/refuse-undeclared-failure-names-in-the-sdk-and-pin-its-list-to-the
status: Backlog
type: task
priority: Medium
labels: [py-screamingface, agentic, autonomous]
created: 2026-09-21
closed:
parent: OME-1233
blocked_by: [OME-1234]
---

# Refuse undeclared failure names in the SDK and pin its list to the engine's

SDK half of the OME-1233 epic. Mirror the declared failure-name list in
`packages/screamingface` (`_report_primitives.py` — deliberate duplication, the house
pattern for `FailureStage` and `CaseStatus`), refuse undeclared names on the SDK
`Failure` model, and bind the two copies with one conformance test so a name added on
one side and forgotten on the other fails loudly. Document the list for report
consumers.

Blocked by OME-1234 — the declared list must exist before the SDK can mirror it.

Full spec, evidence, and diagrams: the OME-1233 issue body.
