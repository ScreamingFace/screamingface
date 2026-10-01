---
id: OME-1163
linear_url: https://linear.app/openmined/issue/OME-1163
status: Backlog
priority: High
labels: [screamingface-engine, agentic, design-session]
created: 2026-09-09
closed:
---

# engine-provider-admission

Existing child of OME-886. Owner approved implementation and separate draft PRs on
2026-09-30. Linear remains the status authority; no ticket is closed by this work.

Preserve the reviewed Engine implementation: declare phase budgets, cap by caller deadline, share the existing two-attempt retry loop, and retain spend uncertainty after transport loss. Base directly on main; merge and deploy Gateway first.
