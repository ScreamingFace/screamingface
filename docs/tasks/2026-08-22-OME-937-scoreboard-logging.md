---
id: OME-937
linear_url: https://linear.app/openmined/issue/OME-937/fix-scoreboard-logging-configure-a-handler-and-honor-scoreboard-log
status: backlog
type: improvement
priority: 3
labels: [scoreboard, agentic, autonomous]
created: 2026-08-22
closed:
---

# Fix scoreboard logging: configure a handler and honor SCOREBOARD_LOG_LEVEL

Create `scoreboard/logs.py` copying the engine's `logs.py` pattern (the documented
`logging.lastResort` fix); call `configure()` from `main.py` and the CLI/job entrypoints.
Makes the already-charted `SCOREBOARD_LOG_LEVEL` govern the app's own loggers, not just
uvicorn's. Stdlib only.

Canonical artifacts:

- Spec: `docs/spec/2026-08-22-observability-traceability-review.md`
