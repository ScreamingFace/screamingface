---
id: OME-1088
linear_url: https://linear.app/openmined/issue/OME-1088/add-the-durable-run-queue-workqueue-stream-dedupe-publish-durable-pull
status: planned
type: task
priority: high
labels:
  - screamingface-engine
  - agentic
  - autonomous
created: 2026-09-02
closed:
---

# Add the durable run queue

A dedicated JetStream stream with `retention=WorkQueue`, file storage, and 3 replicas, consumed by a durable pull consumer. Publishing with `Nats-Msg-Id` set to the topic makes the broker dedupe a resubmission itself, preserving today's `JobAlreadyExists` meaning with no lookup table. Two traps must close here: the orphan sweeper would delete a stream inside the `url4-cloud_` prefix, and `_consumer_config()` always returns `AckPolicy.NONE`, which is correct for the event streams and wrong for a queue.

Spec: `docs/spec/2026-09-02-OME-1086-queue-worker-pool-runner.md`
Plan: `docs/plan/2026-09-02-OME-1086-queue-worker-pool-runner.md`
