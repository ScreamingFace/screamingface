---
id: OME-750
linear_url: https://linear.app/openmined/issue/OME-750/scoreboard-ships-python-313-but-tests-only-312
status: in_progress
type: task
priority: P2
labels: [scoreboard, agentic, autonomous, task]
created: 2026-08-04
closed:
---

`OME-747` moved `apps/scoreboard/Dockerfile` to Python 3.13 on both build stages, but
`scoreboard-tests.yml` still pins a scalar `python-version: "3.12"` (no matrix) — so
scoreboard now ships an interpreter version its CI never tests, unlike aigateway and
url4-cloud which both run a `["3.12", "3.13"]` matrix. Found by the `OME-749` ignore
audit's `ci_matrix` probe.

Fix: extend `scoreboard-tests.yml`'s `test` job to the same `["3.12", "3.13"]` matrix
shape as its siblings.
