---
id: OME-941
linear_url: https://linear.app/openmined/issue/OME-941/surface-terminateddataerror-and-trace-id-on-the-engine-http-get-path
status: backlog
type: improvement
priority: 3
labels: [screamingface-engine, agentic, autonomous]
created: 2026-08-22
closed:
---

# Surface TerminatedData.error and trace_id on the engine HTTP GET path

`_terminal_response` discards `TerminatedData.error{code,message,permanent}` — a sync HTTP
caller gets a bare `502 "the run failed"` while the real detail existed on the soon-deleted
stream. Surface the allowlisted error code, scrubbed message, and trace_id in the problem
response. Never the topic; never raw provider bodies.

Canonical artifacts:

- Spec: `docs/spec/2026-08-22-observability-traceability-review.md`
