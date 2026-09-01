---
id: OME-973
linear_url: https://linear.app/openmined/issue/OME-973/decide-the-shape-of-a-report-intake-service-in-apps
status: done
type: decision
priority: 3
labels: [repo, agentic, design-session]
created: 2026-08-24
closed: 2026-08-26
---

# Decide the shape of a report-intake service in apps/

**Decided and closed 2026-08-26.** Direction captured 2026-08-24: a very small FastAPI
service under `apps/` that accepts an error report and files it, so the reporter needs no
account of their own.

**Sink decided (owner, 2026-08-24): direct to private Linear. No public issues.** The
GitHub-App-to-public-issue option was dropped, along with `.github/ISSUE_TEMPLATE` as a
reporting surface. Everything a reporter submits lands in the private Linear workspace.

Two constraints recorded at decision time were subsequently overtaken by implementation:

- The `OME-967` dependency (the client must mint and retain a trace id, or reports join to
  nothing) was **downgraded to a degradation rather than a blocker** by the implementation
  plan: `correlation` is all-nullable, so a report without a trace id is weaker, not
  invalid. Until `OME-967` lands, reports join on *(endpoint, approximate timestamp)* only.
- The rule-9 fork (`OME-976`) was *sidestepped*, not resolved: the plan shipped the
  `TicketSink` port with `QueueSink` as the v1 adapter, so no deployment holds a Linear
  credential. `LinearSink` was later added in the same epic but is **inert by
  construction** — selecting it still requires the amendment, and **`OME-976` remains
  open.**

Implemented as epic `OME-1002` (PR #754), spec `OME-1004`, plan `OME-1015`.

Canonical artifacts:

- Spec: `docs/spec/2026-08-22-observability-traceability-review.md` (§6 Phase 3)
- Service spec: `docs/spec/2026-08-26-OME-1004-report-intake-service.md`
- Plan: `docs/plan/2026-08-26-OME-1002-report-intake-implementation.md`
