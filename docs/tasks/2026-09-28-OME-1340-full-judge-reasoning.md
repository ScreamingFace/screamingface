---
id: OME-1340
linear_url: https://linear.app/openmined/issue/OME-1340/the-notebook-report-cuts-a-judges-reasoning-off-after-400-characters
status: in_progress
type: improvement
priority: medium
labels: [client-sf, agentic, autonomous]
parent: OME-1299
created: 2026-09-25
closed:
---

# The notebook report cuts a judge's reasoning off after 400 characters

The report clipped a criterion's reasoning at 400 characters with nothing holding the rest.
It now keeps that preview and adds a collapsed "full reasoning" block with the whole
escaped text, line breaks kept; short reasoning renders unchanged. Ships before `OME-1339`,
which makes imported boards' ~2,800-character reasoning reach the report.

- 2026-09-25: filed.
- 2026-09-28: verified on main (54 of 268 HealthBench reasonings over 400); ticket updated;
  implementation on branch `OME-1340-full-judge-reasoning`.
