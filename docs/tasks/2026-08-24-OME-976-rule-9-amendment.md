---
id: OME-976
linear_url: https://linear.app/openmined/issue/OME-976/amend-rule-9-so-product-code-may-call-the-linear-api
status: backlog
type: decision
priority: 3
labels: [repo, agentic, design-session, decision]
created: 2026-08-24
closed:
---

# Amend rule 9 so product code may call the Linear API

Hard prerequisite for `OME-973`, created by the 2026-08-24 decision that all reports go to
private Linear with no public issues. Rule 9 ("API tokens / raw GraphQL are forbidden")
names no subject and on its literal wording forbids the intake service from calling
`issueCreate`. Either amend it — scoping it explicitly to agent behaviour and stating how a
deployed service may hold a Linear credential — or decline and ship `QueueSink`, where an
agent files via MCP during triage (async, no ticket id back to the reporter). If amended,
record it in the spec the way the traceback-posture amendment was.

Canonical artifacts:

- Spec: `docs/spec/2026-08-22-observability-traceability-review.md` (§5, §6 Phase 3)
