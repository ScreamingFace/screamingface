---
id: OME-973
linear_url: https://linear.app/openmined/issue/OME-973/decide-the-shape-of-a-report-intake-service-in-apps
status: backlog
type: decision
priority: 3
labels: [repo, agentic, design-session]
created: 2026-08-24
closed:
---

# Decide the shape of a report-intake service in apps/

**Pre-decision — nothing approved, nothing built.** Direction captured 2026-08-24: a very
small FastAPI service under `apps/` that accepts an error report and delivers it directly
to Linear or to GitHub, so the reporter needs no account of their own.

Open fork: GitHub App → issue → Linear sync (no Linear credential, rule 9 untouched) vs
direct Linear API (needs rule 9 amended in writing first). Blocked by `OME-967` — until
the client mints and retains a trace id, the service would accept reports that join to
nothing.

Canonical artifacts:

- Spec: `docs/spec/2026-08-22-observability-traceability-review.md` (§6 Phase 3)
