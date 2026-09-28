---
id: OME-1254
linear_url: https://linear.app/openmined/issue/OME-1254/flag-class-based-test-files-in-code-review
status: done
type: task
priority: P3
labels: [repo, agentic, autonomous, task]
created: 2026-09-22
closed: 2026-09-22
---

# Flag class-based test files in code review

The repo's test convention is plain `test_` functions (252/260 engine unit test
files; SDK, scoreboard, and url4 suites are all function-style), but the review
agent has no rule for it, so class-based test files pass review unflagged. Two
style islands exist (engine contracteval/spine family; aigateway
`usage_accounting/`), each seeded by one work-train and copied by neighbours —
most recently the `#1004`/`#1005` migration goldens, flattened on owner request.

Deliverable: one Lane-7 bullet in `.claude/agents/sf-code-review.md` — new test
files use plain `test_` functions; fire at Minor; never retro-flag existing
class-style files. Lands via PR per the agent file's ownership rule.
