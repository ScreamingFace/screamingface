---
id: OME-1087
linear_url: https://linear.app/openmined/issue/OME-1087/correct-the-jobrunner-capacity-contract-in-the-streaming-port
status: planned
type: task
priority: medium
labels:
  - url4-python-sdk
  - agentic
  - autonomous
created: 2026-09-02
closed:
---

# Correct the JobRunner capacity contract in the streaming port

`JobRunnerAtCapacity`'s docstring claims a cluster-backed runner never raises it. That sentence is false, and OME-1064 named it as the reason the 503 + `Retry-After` backpressure path was disabled for the one runner that needed it. Rewrite the docstring so it states the real rule — any substrate with a finite declared ceiling raises it — and record in the `JobStatus` docstring that `scheduled` already means queued, so nobody adds a `queued` member later.

Spec: `docs/spec/2026-09-02-OME-1086-queue-worker-pool-runner.md`
Plan: `docs/plan/2026-09-02-OME-1086-queue-worker-pool-runner.md`
