---
id: OME-940
linear_url: https://linear.app/openmined/issue/OME-940/log-engine-run-identity-and-terminal-evidence-on-the-control-plane
status: backlog
type: improvement
priority: 2
labels: [screamingface-engine, agentic, autonomous]
created: 2026-08-22
closed:
---

# Log engine run identity and terminal evidence on the control plane

Two serve-mode log lines that survive the frame stream's 60 s post-run deletion: at
schedule `{trace_id, topic_digest, job_name}` (the correspondence is recorded nowhere
today); at termination `{trace_id, topic_digest, outcome, TerminatedData.error,
close_code, dropped_logs, backlog_hwm}` from the end-of-run self-diagnostics frames.
Never the raw topic — it is a bearer capability; digest only.

Canonical artifacts:

- Spec: `docs/spec/2026-08-22-observability-traceability-review.md`
