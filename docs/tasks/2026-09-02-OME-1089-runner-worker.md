---
id: OME-1089
linear_url: https://linear.app/openmined/issue/OME-1089/add-the-runner-worker-slot-pool-subprocess-supervision-deadlines-drain
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

# Add the runner worker

A new `worker` mode of the existing CLI: a slot pool that claims runs from the queue and forks the existing run entrypoint as a supervised child process, so the crash domain stays one run and `runner/main.py` is untouched. The worker owns the hard deadline wall that replaces `activeDeadlineSeconds`, the in-progress heartbeats that keep a 16-hour run from looking abandoned, and the drain path. Each child must be spawned under its own `RLIMIT_AS`, or a single over-allocating run triggers a Pod OOM and kills its co-tenants — which would void the reason for choosing subprocess isolation.

Spec: `docs/spec/2026-09-02-OME-1086-queue-worker-pool-runner.md`
Plan: `docs/plan/2026-09-02-OME-1086-queue-worker-pool-runner.md`
