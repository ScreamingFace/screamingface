---
id: OME-1069
linear_url: https://linear.app/openmined/issue/OME-1069/runner-traceability-logging-layer
status: in_progress
type: task
priority: medium
labels:
  - screamingface-engine
  - agentic
  - autonomous
  - task
created: 2026-09-01
closed:
---

# Runner traceability and logging layer (k8s mode)

Give the run-mode Job process a structured, correlated logging layer: every process log line
carries the run's `topic` and W3C `trace_id`, the runner logs its lifecycle (boot, world
resolution, start, terminal outcome, summary), and the final summary line is the operator's
one-stop answer for a Job's logs. The CloudEvents stream remains the source of truth; the
process logs point at it.

NOTE: the Linear issue must be filed by the owner (Linear MCP is not available in this
session — MCP-uncovered operations are owner actions in the Linear UI). Labels per
`.claude/task-board.local.md`: landing `screamingface-engine`, `actor=agentic`,
`who-acts=autonomous`, `type=task`.
