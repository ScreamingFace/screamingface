---
id: OME-946
linear_url: https://linear.app/openmined/issue/OME-946/retain-failed-run-evidence-raise-job-ttl-and-keep-failed-nats-streams
status: backlog
type: improvement
priority: 2
labels: [screamingface-engine, agentic, autonomous]
created: 2026-08-22
closed:
---

# Retain failed-run evidence: raise Job TTL and keep failed NATS streams 24h

Stopgap until the Phase 2 OTLP exporter provides real durability: Runner Job
`ttlSecondsAfterFinished` 120 s → 3600 s; failed runs skip the explicit `finally` stream
deletion and are reaped server-side by a ~24 h per-stream MaxAge. Successful runs keep the
60 s reclamation (cost + prompt exposure). Chart knobs + AIDEV-NOTE in house style.

Canonical artifacts:

- Spec: `docs/spec/2026-08-22-observability-traceability-review.md`
