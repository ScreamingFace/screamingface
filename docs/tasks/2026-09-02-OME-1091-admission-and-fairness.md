---
id: OME-1091
linear_url: https://linear.app/openmined/issue/OME-1091/admit-runs-on-queue-depth-and-fair-schedule-them-per-caller
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

# Admit runs on queue depth and fair-schedule them per caller

Admission moves from namespace quota headroom to queue depth, keeping the reservation counter OME-1065 built because the read-modify-write race survives the change of resource. `Retry-After` becomes a drain estimate instead of a hard-coded 1. Fairness lands as per-caller subjects with round-robin pull plus a per-caller in-flight cap — the run-level half of OME-908 — and a spawn-time io budget; dynamic rebalancing via a parent-held gate stays a declared follow-up.

Spec: `docs/spec/2026-09-02-OME-1086-queue-worker-pool-runner.md`
Plan: `docs/plan/2026-09-02-OME-1086-queue-worker-pool-runner.md`
