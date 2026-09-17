---
id: OME-890
linear_url: https://linear.app/openmined/issue/OME-890/stop-engine-runs-that-keep-spending-after-their-client-dies
status: In Progress
type: Feature
priority: High
labels: [screamingface-engine, agentic, autonomous]
created: 2026-08-19
closed:
---

# Stop Engine runs that keep spending after their client dies

Tie a run's lifetime to its audience. When a topic's last WebSocket subscriber disconnects,
a grace window opens. If no subscriber returns before it closes, the Engine stops the run
through the existing idempotent `JobRunner.stop`, and the run terminates as a clean
`Terminated(stopped)`.

Before this, the 428 gate proved an audience existed when the run started and nothing asked
again. A client that died before it could send `ai.url4.stop` — `kill -9`, a Jupyter kernel
restart, laptop sleep, a network partition — left the run issuing paid model calls until
`job_deadline_s` (16 h), holding one of `local_max_concurrent_runs` slots and the gateway's
per-provider slots throughout.

Canonical artifacts:

- Spec: `docs/spec/2026-08-19-OME-890-orphan-run-reaper.md`
- Plan: `docs/plan/2026-08-19-OME-890-orphan-run-reaper.md`
- Ledger: `docs/work/2026-08-19-OME-890-orphan-run-reaper.md`

Reassigned from @khoa to @ionesio on 2026-08-19 by agreement between them.

Scope notes carried from the issue: gateway client-disconnect awareness stays with OME-886.
The SDK's missing single-candidate `DELETE /` fallback is not needed — the reaper closes every
orphan path including that one. Multi-replica liveness (a shared `SubscriberGate` backed by
NATS consumer interest) is a separate follow-up; the reaper targets today's single-replica
deployment and logs that assumption at startup.
