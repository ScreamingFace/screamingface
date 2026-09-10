---
id: OME-1171
linear_url: https://linear.app/openmined/issue/OME-1171/merge-the-safe-dependabot-backlog-and-publish-an-owner-triage
status: done
type: task
priority: High
labels: [repo, agentic, autonomous, task]
created: 2026-09-10
closed: 2026-09-10
---

# Merge the safe Dependabot backlog and publish an owner triage

18 open Dependabot PRs, oldest 2026-09-01, nine of them security updates including two
unauthenticated-RCE advisories for Next.js. Merge the 10 that are lockfile-only transitive bumps
with green CI; hand the 7 that edit a manifest or move a framework version to their CODEOWNER; and
replace #803 rather than merge it, since it trips a deliberate LiteLLM runtime guard covering
security logic. Zero open PRs is not the target — CODEOWNERS is advisory here, and closing without
a schema-valid `ignore:` would just have Dependabot recreate them. Details: Linear issue; how:
ledger `docs/work/2026-09-10-OME-1171-dependabot-backlog.md`; triage for owners:
`docs/plan/2026-09-10-dependabot-backlog-triage.md`.
