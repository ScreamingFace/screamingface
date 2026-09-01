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

## Still open — and now with a shipped consequence

`OME-1002` shipped the report-intake service (PR #754) **without** resolving this. It took
the `QueueSink` route for every deployment, so no product code holds a Linear credential
today. But `OME-1009` also shipped `LinearSink` itself
(`apps/report-intake/src/report_intake/delivery/linear_sink.py`) plus its four `Settings`
fields, including `linear_api_key: SecretStr`.

That adapter is **inert by construction, and deliberately so.** Its module docstring states
the position outright: rule 9 governs *selecting* the adapter, this file does not select it,
the amendment has not been made, and this pass does not make it. It is reachable only when an
operator sets `REPORT_INTAKE_TICKET_SINK=linear`, `build_sink` refuses to start such a
deployment without an API key and a team id, and every deployment today keeps the `queue`
default (service spec §9).

So this ticket is not overtaken by events — it is the gate on a capability that now exists
and cannot be switched on. Deciding it either unlocks `LinearSink` (and makes a long-lived
Linear API key a real secret class for this repo, with an owner for rotation) or confirms
`QueueSink` permanently, in which case `LinearSink` and its settings should be removed rather
than left as dormant code implying a decision that was never taken.

Canonical artifacts:

- Spec: `docs/spec/2026-08-22-observability-traceability-review.md` (§5, §6 Phase 3)
- Adapter: `apps/report-intake/src/report_intake/delivery/linear_sink.py`
