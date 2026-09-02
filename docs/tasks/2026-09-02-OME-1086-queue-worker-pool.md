---
id: OME-1086
linear_url: https://linear.app/openmined/issue/OME-1086/execute-runs-on-a-fixed-worker-pool-pulling-from-a-durable-queue
status: in_progress
type: task
priority: high
labels:
  - screamingface-engine
  - agentic
  - autonomous
created: 2026-09-02
closed:
---

# Execute runs on a fixed worker pool pulling from a durable queue

Cross-cutting epic. Job-per-run makes the Pod count a variable the client chooses, against a quota and a node the operator fixed — the collision OME-1064 recorded as 23 minutes of silent non-execution. A fixed pool of worker Pods pulling from a durable NATS WorkQueue stream makes the Pod count constant and declared, and gives admission one authority instead of five. Seven sub-issues: OME-1087 the port contract, OME-1088 the queue, OME-1089 the worker, OME-1090 status and cancellation, OME-1091 admission and fairness, OME-1092 the chart cutover, OME-1093 NATS durability.

Spec: `docs/spec/2026-09-02-OME-1086-queue-worker-pool-runner.md`
Plan: `docs/plan/2026-09-02-OME-1086-queue-worker-pool-runner.md`
