---
id: OME-1049
linear_url: https://linear.app/openmined/issue/OME-1049/close-the-remaining-uvicorn-log-surfaces-that-leak-a-capability-ticket
status: in_review
type: bug
priority: high
labels: [client-sf, agentic, autonomous]
created: 2026-08-31
---

# Close the remaining uvicorn log surfaces that leak a capability ticket

Follow-up to OME-990. `uvicorn.error` logged the WebSocket handshake path with its query
string, and the Engine's WS URL is `/ws?ticket=<token>` — a live capability credential was
written to `runtime.log` on every attach. A logger-level filter now strips the query string
from every path argument on `uvicorn.error`; `run_scoreboard()` now passes
`access_log=False` like the embedded servers.

- 2026-10-01: implemented on branch `bershadsky/ome-1049-close-the-remaining-uvicorn-log-surfaces-that-leak-a`,
  ledger `docs/work/2026-10-01-uvicorn-ws-ticket-log.md`; PR opened, In Review.
