---
id: OME-990
linear_url: https://linear.app/openmined/issue/OME-990/runtimelog-records-user-prompts-in-cleartext
status: in_progress
type: null
priority: 2
labels: [py-screamingface, agentic, autonomous]
created: 2026-08-25
closed:
---

# runtime.log records user prompts in cleartext

A local run starts as `GET /?q=<url4 expression>`, and a url4 expression is prompt-bearing by
construction. The local runtime served via uvicorn with `access_log` at its default `True`, so
uvicorn's access line wrote the full query string — the user's prompt — into
`~/.screamingface/runtime.log`, retained across 5 × 10 MiB rotations and tailed by
`screamingface logs`. `runtime.log` was also written `0644` while `runtime.json` beside it is
deliberately `0600`.

Fix, in two parts:

1. `access_log=False` in `_server()`, the shared factory for the gateway and the Engine. The
   test asserts the **whole sweep** rather than one server: uvicorn clears the
   `uvicorn.access` handlers only for the Config being constructed at that moment, and each
   later Config re-runs `dictConfig` and re-creates them.
2. `_open_private()` in `runtime_logging.py`, used by both the initial open and `_rotate`, so
   the log is created `0600` and an existing world-readable log is tightened on reopen.

**Necessary, not sufficient.** An adversarial review established that `runtime.log` is the
process's entire stdout+stderr sink, that `uvicorn.error` still logs the WS path including
`?ticket=<capability JWT>`, that rotated backups keep their old mode and contents, and that
`LITELLM_LOG=DEBUG` turns the file into a full prompt transcript. Those are recorded as
follow-ups in the ledger, not fixed here.

First rung of the observability programme (epic `OME-935`), sequenced ahead of every
tracing-wiring change because Phase 3 ends in "attach your logs to a report".

Ledger: `docs/work/2026-08-31-OME-990-runtime-access-log-off.md`.
PR: #780.
