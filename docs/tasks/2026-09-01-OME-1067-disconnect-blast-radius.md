---
id: OME-1067
linear_url: https://linear.app/openmined/issue/OME-1067/cancel-only-the-affected-run-when-a-stream-disconnects
status: planned
type: bug
priority: 2
labels: [py-screamingface, agentic, autonomous]
created: 2026-09-01
closed:
---

# Cancel only the affected run when a stream disconnects

Parent: `OME-1064`. Independent of the capacity work.

`_sweep_after_disconnect()` calls `cancel_active()`, which stops every capability in
`self._active_tokens`. In the 2026-09-01 incident one lost socket failed all nine candidates,
including one that had already completed 100 of 100 cases.

Split the two intents: one stream lost past its reconnect budget cancels only that run;
client shutdown or explicit abort keeps today's sweep-everything semantics. A run already
terminal is never cancelled retroactively.

Spec §4.4. Plan unit 2.
