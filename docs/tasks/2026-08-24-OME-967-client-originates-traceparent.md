---
id: OME-967
linear_url: https://linear.app/openmined/issue/OME-967/originate-the-traceparent-in-the-client-and-surface-trace-id-to-the
status: in_progress
type: null
priority: 2
labels: [py-screamingface, agentic, autonomous]
created: 2026-08-24
closed:
---

# Originate the traceparent in the client and surface `trace_id` to the user

The keystone of the correlation roadmap (epic `OME-935`). The trace id was minted inside the
Runner Job and never returned, and the client sent no trace context at all — so every failure
*before the first frame* (capability mint, run start, WS handshake) had no id of any kind and
was unjoinable to evidence forever. That class is a large share of what users actually hit.

The client now mints a W3C trace context **before its first outbound call** and sends it on
all three legs. The Engine already adopts an inbound traceparent and fails soft to minting
its own, so no server change was needed.

Three decisions worth carrying forward:

1. **The id lives on `ScreamingFaceError`, not on `ExecutionError` alone.** The failures this
   ticket exists to make joinable raise `EngineUnavailableError` and `AuthenticationError`;
   narrowing the field to `ExecutionError` would have missed exactly them.
2. **It is stamped on `_RunOutcome` by the transport, not the contract layer** — the contract
   decodes what the Engine sent, while this id is what the client minted.
3. **Minting is local, not a dependency.** `packages/screamingface` does not depend on `url4`
   or an OTel SDK; `_engine/trace.py` is ~20 lines and the W3C shape is pinned by tests on
   both sides.

Deliberately out of scope, and filed rather than smuggled in: url4's hardcoded `_SAMPLED`
re-stamping an inbound `-00` as `-01`, and the engine discarding inbound span ids.

**Not delivered from the original filing:** surfacing the id in `runtime.log` lines. The
issue names it under "The work" but not under "Verify", and it is server-side runtime
logging rather than client origination — see the ledger's Deviations.

Ledger: `docs/work/2026-09-01-OME-967-client-originates-traceparent.md`.
Spec: `docs/spec/2026-08-22-observability-traceability-review.md` (§4, §6 keystone).
