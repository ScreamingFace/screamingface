---
id: OME-946
linear_url: https://linear.app/openmined/issue/OME-946/retain-failed-run-evidence-skip-the-60-s-subject-purge-for-failed-runs
status: in_review
type: improvement
priority: 2
labels: [screamingface-engine, agentic, autonomous]
created: 2026-08-22
closed:
---

# Retain failed-run evidence: skip the 60 s subject purge for failed runs

Re-scoped 2026-10-01 (Job TTL half obsolete since runner Jobs were retired; per-run streams
replaced by the shared `url4-events` stream): both reclaim paths (`worker/supervisor.py`
`_schedule_reclaim`, `runner/main.py` `run_and_reclaim`) skip the purge when the subject's
terminal frame is `failed`/`timed_out`, leaving it to the stream's 24 h `max_age`
(`discard=OLD` on 1 GiB may evict sooner — documented). Successful runs keep the 60 s purge.
Ledger: `docs/work/2026-10-01-retain-failed-run-evidence.md`.

Original scope (history):

Stopgap until the Phase 2 OTLP exporter provides real durability: Runner Job
`ttlSecondsAfterFinished` 120 s → 3600 s; failed runs skip the explicit `finally` stream
deletion and are reaped server-side by a ~24 h per-stream MaxAge. Successful runs keep the
60 s reclamation (cost + prompt exposure). Chart knobs + AIDEV-NOTE in house style.

Canonical artifacts:

- Spec: `docs/spec/2026-08-22-observability-traceability-review.md`
