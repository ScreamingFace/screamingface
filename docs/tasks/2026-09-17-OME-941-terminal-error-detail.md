---
id: OME-941
linear_url: https://linear.app/openmined/issue/OME-941/surface-terminateddataerror-and-trace-id-on-the-engine-http-get-path
status: done
type: task
priority: medium
labels: [screamingface-engine]
parent: OME-935
created: 2026-09-17
closed: 2026-09-17
---

# Surface TerminatedData.error and trace_id on the engine HTTP GET path

`rest/routes.py` `_terminal_response` reads only `terminated.data.status` and maps it through a
fixed problem table, so a synchronous `GET /` caller gets a bare `502 "the run failed"` while the
real `TerminatedData.error{code,message,permanent}` and the run's trace id sat on the
about-to-be-purged stream.

Scope:

- Report the run's error code, message and `permanent` flag, plus its `trace_id`, as RFC 9457
  extension members on the problem response.
- Sanitise: a closed allowlist of engine-authored error codes; a code off the list collapses to
  `internal_error` and its message is dropped, because `ErrorInfo.message` is `str(exc)` and can
  carry provider text verbatim.
- The topic is a bearer capability and is never rendered. No provider body passes through raw.

Ledger: `docs/work/2026-09-17-OME-941-terminal-error-detail.md`.
