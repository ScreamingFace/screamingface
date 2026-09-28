---
id: OME-938
linear_url: https://linear.app/openmined/issue/OME-938/carry-gateway-call-id-on-every-aigateway-log-line
status: done
type: null
priority: 2
labels: [aigateway, agentic, autonomous]
created: 2026-09-10
closed: 2026-09-10
---

# Carry `gateway_call_id` on every aigateway log line

Rung 3 of the correlation ladder, and a Phase 0 child (`OME-935`) that Phase 1 depends on.
Before this the id reached exactly one log line, so an operator holding an id from a response
body could find the line announcing it and nothing about what the call did.

A ContextVar bound per request by pure-ASGI middleware, plus a log-record factory that stamps
the bound id onto every record created inside that scope, rendered through a `%(call_context)s`
slot the way the Engine renders `%(run_context)s`.

Three things worth knowing before touching this area:

- **The factory is shared.** Redaction and correlation both own
  `logging.setLogRecordFactory`. Idempotence is about the wrapper CHAIN, not the outermost
  factory — a top-only guard made the two installers wrap each other without bound until
  creating one log record overflowed the stack.
- **The id is minted in middleware, not in the taxonomy plugin.** The plugin is gated by
  `AIGW_TAXONOMY_ENABLED`, so minting there made correlation a side effect of usage accounting.
- **`session.py`'s redundant-looking `gateway_call_id=` interpolation is load-bearing.** Two
  prior tests assert on `record.getMessage()`, and the context prefix is added by the Formatter.

Ledger: `docs/work/2026-09-10-OME-938-gateway-call-id-every-line.md`
