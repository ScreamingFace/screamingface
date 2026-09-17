---
id: OME-980
linear_url: https://linear.app/openmined/issue/OME-980/fix-the-healthbench-preparation-success-summary
status: in_progress
type: task
priority: high
labels:
  - screamingface-engine
  - agentic
  - autonomous
  - task
created: 2026-08-25
closed:
---

# Fix the HealthBench preparation success summary

Keep the audit field named `declared_worst30_cases` and repair the family CLI's stale lookup so
successful HealthBench asset preparation reports its counts instead of raising `KeyError` after
the assets have already been written.
