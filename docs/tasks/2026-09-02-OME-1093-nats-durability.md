---
id: OME-1093
linear_url: https://linear.app/openmined/issue/OME-1093/make-nats-durable-and-highly-available-for-the-run-queue
status: planned
type: task
priority: high
labels:
  - screamingface-engine
  - human
  - deferred
created: 2026-09-02
closed:
---

# Make NATS durable and highly available for the run queue

Infrastructure work — lands in `OpenMined/infrastructure`, not this monorepo. Today NATS is `nats.enabled=false`, single-replica, and memory-backed, which is survivable while it carries only transient per-run event streams and is not survivable once it carries the work queue: a memory-backed broker loses every enqueued run on restart, and one replica makes it a single point of failure for the whole submission path. Needs file-backed JetStream on a PersistentVolume, 3 replicas, `num_replicas: 3` on the work-queue stream, and a failure-injection drill proving an enqueued run survives a broker restart.

Spec: `docs/spec/2026-09-02-OME-1086-queue-worker-pool-runner.md`
Plan: `docs/plan/2026-09-02-OME-1086-queue-worker-pool-runner.md`
