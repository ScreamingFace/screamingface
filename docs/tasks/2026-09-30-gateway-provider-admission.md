---
id: OME-1162
linear_url: https://linear.app/openmined/issue/OME-1162
status: In Review
priority: High
labels: [aigateway, agentic, design-session]
created: 2026-09-09
closed:
---

# gateway-provider-admission

Existing child of OME-886. Owner approved implementation and separate draft PRs on
2026-09-30. Linear remains the status authority; no ticket is closed by this work.

Check monotonic admission/caller deadlines after acquiring capacity. Run dispatch in the request task and let the disconnect watcher cancel that task immediately. Preserve classified errors, logging, and slot cleanup.
